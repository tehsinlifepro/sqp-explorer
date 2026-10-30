#!/usr/bin/env python3
"""Enrich competition_brand (top brands) with FREE + tiny-surcharge Keepa signals, per brand's lead ASIN:
rating, review_count, price, out-of-stock %, sales-rank-drops (velocity), Amazon-on-listing, Buy-Box-is-Amazon.
Keepa: product stats=90 (free) + rating=1 (+<=1) + buybox=1 (+2). Cached. --write to update Supabase.
Usage: python3 data_pipeline/build_competition_enrich.py [--write] [--rank N] [--regions US,CA]
"""
import os, sys, collections, psycopg2
from psycopg2.extras import execute_values
import keepa_client as K
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRITE = "--write" in sys.argv
RANK = int(sys.argv[sys.argv.index("--rank") + 1]) if "--rank" in sys.argv else 10
REGIONS = (sys.argv[sys.argv.index("--regions") + 1].split(",") if "--regions" in sys.argv else ["US", "CA"])
DOMAIN = {"US": 1, "CA": 6}
e = {}
for line in open(os.path.join(ROOT, ".secrets", "supabase.env")):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1); e[k.strip()] = v.strip().strip('"').strip("'")
c = psycopg2.connect(host="aws-0-us-east-1.pooler.supabase.com", port=5432, user="postgres.vhrzfsceziyqbrwwwhxv",
    password=e["PGPASSWORD"], dbname="postgres", sslmode="require", connect_timeout=60)
cur = c.cursor()
cur.execute("select region,category,brand,rnk from competition_brand where rnk<=%s and brand<>'Unknown'", (RANK,))
brands = cur.fetchall()
# lead ASIN per (region,category,brand) = max monthly_sold
cur.execute("select region,category,brand,asin,monthly_sold from competition_asin")
best = {}
for r, cat, b, a, u in cur.fetchall():
    k = (r, cat, b)
    if k not in best or (u or 0) > best[k][1]: best[k] = (a, u or 0)
updates = []
for region in REGIONS:
    lead = {}  # asin -> (region,category,brand)
    for r, cat, b, rk in brands:
        if r != region: continue
        a = best.get((r, cat, b), (None, 0))[0]
        if a: lead[a] = (r, cat, b)
    prods, tl = K.product(list(lead.keys()), domain=DOMAIN[region], stats=90, rating=1, buybox=1)
    pmap = {p.get("asin"): p for p in prods}
    for a, (r, cat, b) in lead.items():
        p = pmap.get(a)
        if not p: continue
        f = K.enrich_fields(p)
        updates.append((f["rating"], f["review_count"], f["price"], f["oos_pct"], f["rank_drops"],
                        f["amazon_on"], f["bb_amazon"], r, cat, b))
    print(f"  {region}: enriched {sum(1 for a in lead if a in pmap)}/{len(lead)} brands | tokensLeft~{tl}")
print(f"\nTOTAL brand rows to update: {len(updates)}")
if updates:
    print("  sample:", updates[0])
if WRITE and updates:
    cur.executemany("""update competition_brand set rating=%s, review_count=%s, price=%s, oos_pct=%s,
        rank_drops=%s, amazon_on=%s, bb_amazon=%s where region=%s and category=%s and brand=%s""", updates)
    c.commit(); print(f"  -> updated {len(updates)} competition_brand rows")
cur.close(); c.close()
print("DONE." + ("" if WRITE else "  (dry-run)"))
