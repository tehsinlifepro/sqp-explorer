#!/usr/bin/env python3
"""Monthly placement refresh: Azure SP campaign-placements report -> Supabase ad_placement_month.

Placement performance (Top-of-Search / Product pages / Rest of Search) per campaign per month. This is the
REAL Top-of-Search source (SB search-term impression share is empty in Reason). Feeds the Ads tab's
placement-mix card: where spend goes and which placement converts.

ACCUMULATOR: upsert on the PK — never truncate. Needs Azure + Supabase. Part of refresh_db.sh.
Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/refresh_placements.py
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

SQL = """select campaign_id::bigint, coalesce(placement_type,''), max(campaign_bidding_strategy),
    to_char(date,'YYYY-MM') as month,
    sum(impressions)::bigint, sum(clicks)::bigint, round(sum(spend)::numeric,2),
    sum("7_day_total_orders")::bigint, round(sum("7_day_total_sales")::numeric,2)
  from ads_sponsored_products_campaign_placements
  where campaign_id is not null
  group by campaign_id, coalesce(placement_type,''), to_char(date,'YYYY-MM')"""

az = azure(); ac = az.cursor(); ac.execute(SQL)
rows = [(REGION, 'SP', month, cid, clean(ptype), clean(bid), impr, clk, spend, orders, sales)
        for cid, ptype, bid, month, impr, clk, spend, orders, sales in ac.fetchall()]
az.close()
print(f"  Azure SP placements: {len(rows):,} (campaign×placement×month) rows")

sp = supa(); sc = sp.cursor()
sc.execute("""create table if not exists ad_placement_month (
  region text, program text, month text, campaign_id bigint, placement_type text, bidding_strategy text,
  impressions bigint, clicks bigint, spend numeric, orders bigint, sales numeric,
  primary key (region, program, month, campaign_id, placement_type));""")
execute_values(sc, """insert into ad_placement_month
  (region,program,month,campaign_id,placement_type,bidding_strategy,impressions,clicks,spend,orders,sales) values %s
  on conflict (region,program,month,campaign_id,placement_type) do update set
    bidding_strategy=excluded.bidding_strategy, impressions=excluded.impressions, clicks=excluded.clicks,
    spend=excluded.spend, orders=excluded.orders, sales=excluded.sales""",
  rows, page_size=5000)
sp.commit()
sc.execute("select min(month),max(month),count(*) from ad_placement_month")
print("  ad_placement_month:", sc.fetchone())
sp.close()
print("✓ refresh_placements complete (accumulator: upserted)")
