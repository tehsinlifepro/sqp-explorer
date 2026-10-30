#!/usr/bin/env python3
"""Build US campaign_map (campaign -> family) so every ads tab can group US ads by family,
mirroring the CA build_campaign_map.py 80%-dominance rule. Preserves any manual_family.

Source of family spend: Supabase ad_asin_month (US) + catalog (US). campaign_name pulled from the
USA Reason source. Upserts campaign_map rows with region='US'. Dry-run by default; --write to load.
"""
import os, sys, collections, psycopg2
from psycopg2.extras import execute_values
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRITE = "--write" in sys.argv
ACCT = "LifePro Fitness"

def env(fn):
    d = {}
    for line in open(os.path.join(ROOT, ".secrets", fn)):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1); d[k.strip()] = v.strip().strip('"').strip("'")
    return d

e = env("supabase.env"); ue = env("usa-reason.env")
sb = psycopg2.connect(host="aws-0-us-east-1.pooler.supabase.com", port=5432, user="postgres.vhrzfsceziyqbrwwwhxv",
    password=e["PGPASSWORD"], dbname="postgres", sslmode="require", connect_timeout=60)
cur = sb.cursor()
# family map from catalog US
cur.execute("select asin, family from catalog where region='US' and asin is not null")
fam = {a: f for a, f in cur.fetchall() if f}
# per-campaign, per-asin spend/sales from the loaded US advertised-product facts
cur.execute("select campaign_id, advertised_asin, sum(spend), sum(sales) from ad_asin_month where region='US' group by campaign_id, advertised_asin")
rows = cur.fetchall()
# campaign_name from source
us = psycopg2.connect(host=ue["USA_REASON_PGHOST"], port=5432, dbname=ue["USA_REASON_PGDATABASE"],
    user=ue["USA_REASON_PGUSER"], password=ue["USA_REASON_PGPASSWORD"], sslmode="require", connect_timeout=60)
uc = us.cursor()
uc.execute("""select campaign_id::bigint, max(campaign_name) from public.ads_sponsored_products_advertised_product
  where ads_account_name=%s and campaign_id ~ '^[0-9]+$' group by campaign_id::bigint""", (ACCT,))
cname = {cid: nm for cid, nm in uc.fetchall()}
uc.close(); us.close()

camp_spend = collections.defaultdict(float); camp_sales = collections.defaultdict(float)
camp_famspend = collections.defaultdict(lambda: collections.defaultdict(float))
camp_asins = collections.defaultdict(set)
for cid, asin, spend, sales in rows:
    camp_spend[cid] += float(spend or 0); camp_sales[cid] += float(sales or 0)
    camp_asins[cid].add(asin)
    f = fam.get(asin)
    if f: camp_famspend[cid][f] += float(spend or 0)

# preserve existing manual_family
cur.execute("select campaign_id, manual_family from campaign_map where region='US' and coalesce(manual_family,'')<>''")
manual = dict(cur.fetchall())

out = []
auto_n = 0
for cid in camp_spend:
    tot = camp_spend[cid] or 1
    best_fam, best_ratio = None, 0
    for f, sp in camp_famspend[cid].items():
        if sp / tot > best_ratio: best_fam, best_ratio = f, sp / tot
    auto = best_fam if best_ratio >= 0.8 else None
    if auto: auto_n += 1
    status = 'auto' if auto else 'unmapped'
    out.append(('US', 'SP', cid, cname.get(cid, ''), '', auto, 'advertised_product', status,
                round(camp_spend[cid], 2), round(camp_sales[cid], 2), len(camp_asins[cid]), manual.get(cid)))

print(f"US campaigns: {len(out)} | auto-mapped (>=80% one family): {auto_n} | unmapped: {len(out)-auto_n}")
print("sample:", out[0] if out else None)
if WRITE and out:
    execute_values(cur, """insert into campaign_map
      (region,program,campaign_id,campaign_name,asin,auto_family,source,status,spend,sales,terms,manual_family)
      values %s on conflict (program,campaign_id) do update set
      campaign_name=excluded.campaign_name, auto_family=excluded.auto_family, source=excluded.source,
      status=excluded.status, spend=excluded.spend, sales=excluded.sales, terms=excluded.terms""", out, page_size=1000)
    sb.commit(); print(f"  -> wrote {len(out)} US campaign_map rows")
cur.close(); sb.close()
print("DONE." + ("" if WRITE else "  (dry-run — --write to load)"))
