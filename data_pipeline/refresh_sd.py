#!/usr/bin/env python3
"""Monthly Sponsored Display refresh: Azure SD campaign report -> Supabase sd_campaign_month.

Upper-funnel / brand-building lens: spend, sales, new-to-brand sales & orders, detail-page views (DPV),
add-to-cart (ATC), view-through sales. Account level (SD campaigns aren't in the SP/SB campaign_map).

ACCUMULATOR: upsert on the PK — never truncate. Needs Azure + Supabase. Part of refresh_db.sh.
Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/refresh_sd.py
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

SQL = """select campaign_id::bigint, max(campaign_name), to_char(date,'YYYY-MM') as month,
    sum(impressions)::bigint, sum(clicks)::bigint, round(sum(spend)::numeric,2),
    round(sum("14_day_total_sales")::numeric,2), sum("14_day_total_orders")::bigint,
    round(sum("14_day_new_to_brand_sales")::numeric,2), sum("14_day_new_to_brand_orders")::bigint,
    sum("14_day_dpv")::bigint, sum(add_to_cart)::bigint, round(sum("view_attributed_sales_14d")::numeric,2)
  from ads_sponsored_display_campaign
  where campaign_id is not null and date is not null
  group by campaign_id, to_char(date,'YYYY-MM')"""

az = azure(); ac = az.cursor(); ac.execute(SQL)
rows = [(REGION, month, cid, clean(cname), impr, clk, spend, sales, orders, ntbs, ntbo, dpv, atc, vsales)
        for cid, cname, month, impr, clk, spend, sales, orders, ntbs, ntbo, dpv, atc, vsales in ac.fetchall()]
az.close()
print(f"  Azure SD campaigns: {len(rows):,} (campaign×month) rows")

sp = supa(); sc = sp.cursor()
sc.execute("""create table if not exists sd_campaign_month (
  region text, month text, campaign_id bigint, campaign_name text,
  impressions bigint, clicks bigint, spend numeric, sales numeric, orders bigint,
  ntb_sales numeric, ntb_orders bigint, dpv bigint, atc bigint, view_sales numeric,
  primary key (region, month, campaign_id));""")
execute_values(sc, """insert into sd_campaign_month
  (region,month,campaign_id,campaign_name,impressions,clicks,spend,sales,orders,ntb_sales,ntb_orders,dpv,atc,view_sales) values %s
  on conflict (region,month,campaign_id) do update set
    campaign_name=excluded.campaign_name, impressions=excluded.impressions, clicks=excluded.clicks,
    spend=excluded.spend, sales=excluded.sales, orders=excluded.orders, ntb_sales=excluded.ntb_sales,
    ntb_orders=excluded.ntb_orders, dpv=excluded.dpv, atc=excluded.atc, view_sales=excluded.view_sales""",
  rows, page_size=5000)
sp.commit()
sc.execute("select min(month),max(month),count(*) from sd_campaign_month")
print("  sd_campaign_month:", sc.fetchone())
sp.close()
print("✓ refresh_sd complete (accumulator: upserted)")
