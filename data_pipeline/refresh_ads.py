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
# GRAIN switch: 'month' (default) writes ad_searchterm + rebuilds campaign_map; 'week' writes
# ad_searchterm_week keyed by ISO Monday week-start date and leaves the shared campaign_map alone.
GRAIN = os.environ.get('GRAIN', 'month')
PEXPR = "to_char(date,'YYYY-MM')" if GRAIN == 'month' else "date_trunc('week',date)::date"
AST   = 'ad_searchterm' if GRAIN == 'month' else 'ad_searchterm_week'
PCOL  = 'month' if GRAIN == 'month' else 'week'
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
SP_SQL = f'''select campaign_id::bigint, max(campaign_name), customer_search_term, {PEXPR},
    sum(impressions)::bigint, sum(clicks)::bigint, round(sum(spend)::numeric,2),
    round(sum("7_day_total_sales")::numeric,2), sum("7_day_total_orders")::bigint,
    sum("7_day_total_units")::bigint, round(sum("7_day_advertised_sku_sales")::numeric,2),
    null::real, null::real
  from ads_sponsored_products_search_term
  where campaign_id is not null and customer_search_term is not null
  group by campaign_id, customer_search_term, {PEXPR}'''
# SB exposes only a 14-day window and no units; it DOES expose search-term impression share/rank.
SB_SQL = f'''select campaign_id::bigint, max(campaign_name), customer_search_term, {PEXPR},
    sum(impressions)::bigint, sum(clicks)::bigint, round(sum(spend)::numeric,2),
    round(sum("14_day_total_sales")::numeric,2), sum("14_day_total_orders")::bigint,
    null::bigint, round(sum("14_day_same_sku_sales")::numeric,2),
    round(avg(search_term_impression_share)::numeric,4)::real, round(avg(search_term_impression_rank)::numeric,1)::real
  from ads_sponsored_brands_search_term
  where campaign_id is not null and customer_search_term is not null
  group by campaign_id, customer_search_term, {PEXPR}'''

az = azure(); ac = az.cursor()
rows = []            # ad_searchterm rows (period = month-string or week-start date per GRAIN)
for prog, sql in (('SP', SP_SQL), ('SB', SB_SQL)):
    ac.execute(sql)
    for cid, cname, term, period, impr, clk, spend, sales, orders, units, adv, ishare, irank in ac.fetchall():
        rows.append((REGION, prog, period, cid, clean(term), impr, clk, spend, sales, orders, units, adv, ishare, irank, clean(cname)))
    print(f"  Azure {prog}: {len([r for r in rows if r[1]==prog]):,} (campaign×term×{PCOL}) rows")
az.close()

# ── 2. rebuild the searchterm table for this grain ────────────────────────────
sp = supa(); sc = sp.cursor()
# self-create the weekly twin so a standalone GRAIN=week run works even before ad_week_schema.sql is applied
if GRAIN == 'week':
    sc.execute("""create table if not exists ad_searchterm_week (
      region text, program text, week date, campaign_id bigint, customer_search_term text,
      impressions bigint, clicks bigint, spend numeric, sales numeric, orders bigint,
      units bigint, adv_sku_sales numeric, impr_share real, impr_rank real);""")
sc.execute(f"truncate {AST}")
execute_values(sc, f"""insert into {AST}
  (region,program,{PCOL},campaign_id,customer_search_term,impressions,clicks,spend,sales,orders,
   units,adv_sku_sales,impr_share,impr_rank) values %s""",
  [r[:14] for r in rows], page_size=5000)

# campaign_map is grain-independent (one row per program,campaign_id) — rebuilt in the MONTHLY run
# only, preserving manual_family. The weekly run reuses the same campaign_map via the weekly views.
if GRAIN == 'month':
    sc.execute("select program, campaign_id, manual_family from campaign_map where coalesce(manual_family,'')<>''")
    manual = {(p, c): m for p, c, m in sc.fetchall()}
    print(f"  preserving {len(manual)} manual_family mappings")
    cm = {}
    for region, prog, period, cid, term, impr, clk, spend, sales, orders, units, adv, ishare, irank, cname in rows:
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

sc.execute(f"select program, count(*), round(sum(spend)), round(sum(sales)), sum(orders) from {AST} group by program")
print(f"{AST} loaded:")
for r in sc.fetchall(): print("  ", r)
if GRAIN == 'month':
    sc.execute("select count(*) from campaign_map"); print("campaign_map rows:", sc.fetchone()[0])
    print("✓ refresh_ads complete — now run build_campaign_map.py for SP auto_family (dominance rule)")
else:
    print("✓ refresh_ads (weekly) complete — ad_searchterm_week loaded (campaign_map untouched)")
sp.close()
