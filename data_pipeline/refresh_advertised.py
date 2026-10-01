#!/usr/bin/env python3
"""Monthly advertised-product refresh: Azure SP advertised-product report -> Supabase ad_asin_month.

ASIN-level ad attribution for variation science: per advertised ASIN, ad clicks/orders (-> ad CVR) and
halo (other-SKU sales). Lets you advertise the highest-CVR child and see which children carry the halo.

ACCUMULATOR: upsert on the PK — never truncate. Needs Azure + Supabase. Part of refresh_db.sh.
Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/refresh_advertised.py
"""
import os, psycopg2
from psycopg2.extras import execute_values
REGION = 'CA'
# GRAIN switch: 'month' (default) → ad_asin_month; 'week' → ad_asin_week (ISO Monday week-start).
GRAIN = os.environ.get('GRAIN', 'month')
PEXPR = "to_char(date,'YYYY-MM')" if GRAIN == 'month' else "date_trunc('week',date)::date"
TBL   = 'ad_asin_month' if GRAIN == 'month' else 'ad_asin_week'
PCOL  = 'month' if GRAIN == 'month' else 'week'
PTYPE = 'text' if GRAIN == 'month' else 'date'

def azure():
    return psycopg2.connect(host=os.environ['AZURE_PG_HOST'], port=os.environ.get('AZURE_PG_PORT', '5432'),
        user=os.environ['AZURE_PG_USER'], password=os.environ['AZURE_PG_PASSWORD'],
        dbname=os.environ['AZURE_PG_DB'], sslmode='require', connect_timeout=40)
def supa():
    return psycopg2.connect(host=os.environ['PGHOST'], port=os.environ.get('PGPORT', '5432'),
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        dbname=os.environ.get('PGDATABASE', 'postgres'), sslmode='require', connect_timeout=40)

SQL = f"""select campaign_id::bigint, coalesce(advertised_asin,''), {PEXPR} as {PCOL},
    sum(impressions)::bigint, sum(clicks)::bigint, round(sum(spend)::numeric,2),
    sum("7_day_total_orders")::bigint, round(sum("7_day_total_sales")::numeric,2),
    round(sum("7_day_advertised_sku_sales")::numeric,2), round(sum("7_day_other_sku_sales")::numeric,2)
  from ads_sponsored_products_advertised_product
  where campaign_id is not null and date is not null
  group by campaign_id, coalesce(advertised_asin,''), {PEXPR}"""

az = azure(); ac = az.cursor(); ac.execute(SQL)
rows = [(REGION, 'SP', period, cid, asin, impr, clk, spend, orders, sales, adv, other)
        for cid, asin, period, impr, clk, spend, orders, sales, adv, other in ac.fetchall()]
az.close()
print(f"  Azure SP advertised-product: {len(rows):,} (campaign×asin×{PCOL}) rows")

sp = supa(); sc = sp.cursor()
sc.execute(f"""create table if not exists {TBL} (
  region text, program text, {PCOL} {PTYPE}, campaign_id bigint, advertised_asin text,
  impressions bigint, clicks bigint, spend numeric, orders bigint, sales numeric,
  adv_sku_sales numeric, other_sku_sales numeric,
  primary key (region, program, {PCOL}, campaign_id, advertised_asin));""")
execute_values(sc, f"""insert into {TBL}
  (region,program,{PCOL},campaign_id,advertised_asin,impressions,clicks,spend,orders,sales,adv_sku_sales,other_sku_sales) values %s
  on conflict (region,program,{PCOL},campaign_id,advertised_asin) do update set
    impressions=excluded.impressions, clicks=excluded.clicks, spend=excluded.spend,
    orders=excluded.orders, sales=excluded.sales, adv_sku_sales=excluded.adv_sku_sales,
    other_sku_sales=excluded.other_sku_sales""",
  rows, page_size=5000)
sp.commit()
sc.execute(f"select min({PCOL}),max({PCOL}),count(*),count(distinct advertised_asin) from {TBL}")
print(f"  {TBL}:", sc.fetchone())
sp.close()
print("✓ refresh_advertised complete (accumulator: upserted)")
