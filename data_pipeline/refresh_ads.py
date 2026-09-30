#!/usr/bin/env python3
"""Monthly Ads refresh: Azure (Canada Vendor Central ad reports) → Supabase ad_searchterm + campaign_map.

Rebuilds both tables from the source of truth (Azure keeps full history, so a full rebuild is correct):
  - ad_searchterm : per (region, program, month, campaign_id, customer_search_term) impressions/clicks/spend/sales/orders
                    SP sales+orders = 7-day window; SB = 14-day (the only window SB exposes).
  - campaign_map  : one row per (program, campaign_id) with campaign_name + spend/sales/terms.
                    PRESERVES existing manual_family edits. auto_family is left blank here — run
                    build_campaign_map.py afterwards to (re)apply the 80%-advertised-spend dominance rule.

Needs Azure + Supabase. Part of the monthly DB lane (Mac launchd → refresh_db.sh).
Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/refresh_ads.py
"""
import os, re, psycopg2
from psycopg2.extras import execute_values
REGION = 'CA'
clean = lambda s: re.sub(r'[\r\n\t\x00]', ' ', s).strip() if s else s

def azure():
    return psycopg2.connect(host=os.environ['AZURE_PG_HOST'], port=os.environ.get('AZURE_PG_PORT', '5432'),
        user=os.environ['AZURE_PG_USER'], password=os.environ['AZURE_PG_PASSWORD'],
        dbname=os.environ['AZURE_PG_DB'], sslmode='require', connect_timeout=40)
def supa():
    return psycopg2.connect(host=os.environ['PGHOST'], port=os.environ.get('PGPORT', '5432'),
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        dbname=os.environ.get('PGDATABASE', 'postgres'), sslmode='require', connect_timeout=40)

# ── 1. pull + aggregate from Azure (SQL does the grouping) ────────────────────
# Widened (Sprint 1): + units, advertised-SKU sales (halo base), and SB Top-of-Search impression share/rank.
# Column order matches the fetch-loop unpack below: cid,cname,term,month,impr,clk,spend,sales,orders,units,adv_sku_sales,impr_share,impr_rank.
SP_SQL = '''select campaign_id::bigint, max(campaign_name), customer_search_term, to_char(date,'YYYY-MM'),
    sum(impressions)::bigint, sum(clicks)::bigint, round(sum(spend)::numeric,2),
    round(sum("7_day_total_sales")::numeric,2), sum("7_day_total_orders")::bigint,
    sum("7_day_total_units")::bigint, round(sum("7_day_advertised_sku_sales")::numeric,2),
    null::real, null::real
  from ads_sponsored_products_search_term
  where campaign_id is not null and customer_search_term is not null
  group by campaign_id, customer_search_term, to_char(date,'YYYY-MM')'''
# SB exposes only a 14-day window and no units; it DOES expose search-term impression share/rank.
SB_SQL = '''select campaign_id::bigint, max(campaign_name), customer_search_term, to_char(date,'YYYY-MM'),
    sum(impressions)::bigint, sum(clicks)::bigint, round(sum(spend)::numeric,2),
    round(sum("14_day_total_sales")::numeric,2), sum("14_day_total_orders")::bigint,
    null::bigint, round(sum("14_day_same_sku_sales")::numeric,2),
    round(avg(search_term_impression_share)::numeric,4)::real, round(avg(search_term_impression_rank)::numeric,1)::real
  from ads_sponsored_brands_search_term
  where campaign_id is not null and customer_search_term is not null
  group by campaign_id, customer_search_term, to_char(date,'YYYY-MM')'''

az = azure(); ac = az.cursor()
rows = []            # ad_searchterm rows
for prog, sql in (('SP', SP_SQL), ('SB', SB_SQL)):
    ac.execute(sql)
    for cid, cname, term, month, impr, clk, spend, sales, orders, units, adv, ishare, irank in ac.fetchall():
        rows.append((REGION, prog, month, cid, clean(term), impr, clk, spend, sales, orders, units, adv, ishare, irank, clean(cname)))
    print(f"  Azure {prog}: {len([r for r in rows if r[1]==prog]):,} (campaign×term×month) rows")
az.close()

# ── 2. preserve existing manual_family, then rebuild both tables ──────────────
sp = supa(); sc = sp.cursor()
sc.execute("select program, campaign_id, manual_family from campaign_map where coalesce(manual_family,'')<>''")
manual = {(p, c): m for p, c, m in sc.fetchall()}
print(f"  preserving {len(manual)} manual_family mappings")

# ad_searchterm
sc.execute("truncate ad_searchterm")
execute_values(sc, """insert into ad_searchterm
  (region,program,month,campaign_id,customer_search_term,impressions,clicks,spend,sales,orders,
   units,adv_sku_sales,impr_share,impr_rank) values %s""",
  [r[:14] for r in rows], page_size=5000)

# campaign_map skeleton (one row per program,campaign_id)
cm = {}
for region, prog, month, cid, term, impr, clk, spend, sales, orders, units, adv, ishare, irank, cname in rows:
    k = (prog, cid)
    x = cm.get(k)
    if not x: x = cm[k] = {'campaign_name': cname, 'spend': 0.0, 'sales': 0.0, 'terms': set()}
    if cname: x['campaign_name'] = cname
    x['spend'] += float(spend or 0); x['sales'] += float(sales or 0); x['terms'].add(term)
sc.execute("truncate campaign_map")
execute_values(sc, """insert into campaign_map
  (region,program,campaign_id,campaign_name,asin,auto_family,source,status,spend,sales,terms,manual_family) values %s""",
  [(REGION, prog, cid, v['campaign_name'], None, None, 'advertised_product' if prog == 'SP' else 'sb',
    'unmapped', round(v['spend'], 2), round(v['sales'], 2), len(v['terms']), manual.get((prog, cid)))
   for (prog, cid), v in cm.items()], page_size=2000)
sp.commit()

sc.execute("select program, count(*), round(sum(spend)) , round(sum(sales)), sum(orders) from ad_searchterm group by program")
print("ad_searchterm loaded:")
for r in sc.fetchall(): print("  ", r)
sc.execute("select count(*) from campaign_map"); print("campaign_map rows:", sc.fetchone()[0], f"({len(manual)} manual preserved)")
sp.close()
print("✓ refresh_ads complete — now run build_campaign_map.py for SP auto_family (dominance rule)")
