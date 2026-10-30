#!/usr/bin/env python3
"""Competition Watch (WS3): subcategory market share incl. competitors, via Keepa monthlySold.

Flow per region (US=domain1, CA=domain3):
  1. Pull OUR catalog ASINs (Keepa product) -> each ASIN's leaf subcategory + brand + monthlySold.
  2. Per our `category`, pick the dominant Keepa leaf subcategory (catId).
  3. bestsellers(catId) -> top ASINs; take top TOP_N.
  4. Pull those ASINs (product) -> brand + monthlySold (+bsr/price/rating).
  5. Aggregate units by brand -> share of subcategory; keep ranked brands (>=10 surfaced).
  6. Write competition_asin + competition_brand (region,category). Gated: --write.

Keepa cost: product=1 tok/ASIN (batched 100), bestsellers=50 tok. Raw responses cached locally
(keepa_client) so re-runs don't re-spend. Dry-run by DEFAULT (prints plan + token estimate).

Usage: python3 data_pipeline/build_competition.py [--write] [--top N] [--regions US,CA]
"""
import os, sys, datetime, collections
import psycopg2
from psycopg2.extras import execute_values, Json
import keepa_client as K

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRITE = "--write" in sys.argv
TOP_N = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 40
REGIONS = (sys.argv[sys.argv.index("--regions") + 1].split(",") if "--regions" in sys.argv else ["US", "CA"])
DOMAIN = {"US": 1, "CA": 6}  # Keepa domain codes: 1=US, 2=UK, 3=DE, 4=FR, 5=JP, 6=CA, 8=IT. (NOT 3=DE / 8=IT for CA.)
TODAY = datetime.date.today()

def sb():
    e = {}
    for line in open(os.path.join(ROOT, ".secrets", "supabase.env")):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1); e[k.strip()] = v.strip().strip('"').strip("'")
    return psycopg2.connect(host="aws-0-us-east-1.pooler.supabase.com", port=5432,
        user="postgres.vhrzfsceziyqbrwwwhxv", password=e["PGPASSWORD"], dbname="postgres",
        sslmode="require", connect_timeout=60)

def price_of(p):
    st = (p.get("stats") or {}).get("current") or []
    for i in (1, 0, 10):  # NEW, AMAZON, NEW_FBM (Keepa prices in cents)
        if i < len(st) and st[i] and st[i] > 0:
            return round(st[i] / 100.0, 2)
    return None

def bsr_of(p):
    st = (p.get("stats") or {}).get("current") or []
    return st[3] if len(st) > 3 and st[3] and st[3] > 0 else None

def rating_of(p):
    st = (p.get("stats") or {}).get("current") or []
    r = st[16] if len(st) > 16 and st[16] and st[16] > 0 else None
    rc = st[17] if len(st) > 17 and st[17] and st[17] > 0 else None
    return (round(r / 10.0, 1) if r else None), (rc if rc else None)

def main():
    con = sb(); cur = con.cursor()
    cur.execute("select region, asin, category, brand from catalog where asin is not null")
    cat_rows = cur.fetchall()
    by_region = collections.defaultdict(list)
    for region, asin, category, brand in cat_rows:
        by_region[region].append((asin, category or "Uncategorized", (brand or "").strip()))
    print(f"MODE: {'WRITE' if WRITE else 'DRY-RUN'} | TOP_N={TOP_N} | regions={REGIONS}\n")

    asin_rows, brand_rows = [], []
    for region in REGIONS:
        dom = DOMAIN[region]; mine = by_region.get(region, [])
        our_asins = [a for a, _, _ in mine]
        our_set = set(our_asins)
        our_cat = {a: c for a, c, _ in mine}
        print(f"=== {region} (domain {dom}) — {len(our_asins)} catalog ASINs ===")
        # 1. our ASINs -> leaf catId per our-category
        ours, tl = K.product(our_asins, domain=dom)
        leafvote = collections.defaultdict(collections.Counter)
        for p in ours:
            cid, cname = K.leaf_category(p)
            if cid: leafvote[our_cat.get(p.get("asin"), "Uncategorized")][(cid, cname)] += 1
        # 2. dominant leaf per category
        cat_leaf = {c: votes.most_common(1)[0][0] for c, votes in leafvote.items() if votes}
        print(f"  tokensLeft~{tl} | categories->leaf: " + "; ".join(f"{c}->{nm}({cid})" for c,(cid,nm) in cat_leaf.items()))
        # 3-5. per category: bestsellers -> top ASINs -> products -> brand aggregation
        for category, (cid, cname) in cat_leaf.items():
            try:
                alist, tl = K.bestsellers(cid, domain=dom)
            except Exception as ex:
                print(f"  [{category}] bestsellers failed: {ex}"); continue
            top = list(dict.fromkeys(alist[:TOP_N] + [a for a in our_asins if our_cat.get(a) == category]))
            prods, tl = K.product(top, domain=dom)
            brand_units = collections.Counter(); brand_asins = collections.Counter(); brand_ours = {}
            for p in prods:
                a = p.get("asin"); b = (p.get("brand") or "Unknown").strip() or "Unknown"
                units = p.get("monthlySold") or 0
                rating, rc = rating_of(p)
                asin_rows.append((region, category, a, b, units, bsr_of(p), price_of(p), rating, rc, a in our_set, TODAY))
                brand_units[b] += units; brand_asins[b] += 1
                brand_ours[b] = brand_ours.get(b, False) or (a in our_set)
            total = sum(brand_units.values()) or 1
            ranked = brand_units.most_common()
            print(f"  [{category}] {cname}: {len(prods)} ASINs, {len(brand_units)} brands, {total:,} units/mo | tokensLeft~{tl}")
            for rnk, (b, u) in enumerate(ranked, 1):
                brand_rows.append((region, category, b, u, brand_asins[b], round(u / total, 4), brand_ours[b], rnk, TODAY))
            for b, u in ranked[:8]:
                tag = " (OURS)" if brand_ours[b] else ""
                print(f"       {u/total*100:5.1f}%  {b[:28]:28}{tag}  {u:,} units")

    print(f"\nTOTAL rows: competition_asin={len(asin_rows)}  competition_brand={len(brand_rows)}")
    if WRITE and brand_rows:
        c = con.cursor()
        c.execute("delete from competition_asin where region = any(%s)", (REGIONS,))
        execute_values(c, "insert into competition_asin (region,category,asin,brand,monthly_sold,bsr,price,rating,review_count,is_ours,updated) values %s on conflict (region,category,asin) do update set brand=excluded.brand,monthly_sold=excluded.monthly_sold,bsr=excluded.bsr,price=excluded.price,rating=excluded.rating,review_count=excluded.review_count,is_ours=excluded.is_ours,updated=excluded.updated", asin_rows, page_size=1000)
        c.execute("delete from competition_brand where region = any(%s)", (REGIONS,))
        execute_values(c, "insert into competition_brand (region,category,brand,units_monthly,asin_count,share,is_ours,rnk,updated) values %s on conflict (region,category,brand) do update set units_monthly=excluded.units_monthly,asin_count=excluded.asin_count,share=excluded.share,is_ours=excluded.is_ours,rnk=excluded.rnk,updated=excluded.updated", brand_rows, page_size=1000)
        con.commit()
        print(f"  -> wrote {len(asin_rows)} competition_asin, {len(brand_rows)} competition_brand rows")
    con.close()
    print("\nDONE." + ("" if WRITE else "  (dry-run — re-run with --write after competition_schema.sql is applied)"))

if __name__ == "__main__":
    main()
