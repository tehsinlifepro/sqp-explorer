#!/usr/bin/env python3
"""Monthly targeting refresh: Azure SP targeting report -> Supabase ad_targeting.

The "wasted ad spend table" source: per (campaign, ad_group, keyword_type, match_type, targeting, month)
impressions/clicks/spend/orders/sales + the current bid. Enables the Optimize tab's wasted-spend view
(spend, 0 orders -> cut/negate) and feeds the harvest anti-join (converting term not yet EXACT).

ACCUMULATOR: upsert on the PK — never truncate (rolling source, same golden rule as SQP/RA).
Needs Azure + Supabase. Part of the monthly DB lane (refresh_db.sh).
Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/refresh_targeting.py
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

# keyword_type is max()'d (not grouped) so a (campaign,ad_group,target,match_type,month) key can't emit two
# rows for one PK and abort the upsert page; date filtered to keep month non-null.
SQL = """select campaign_id::bigint, coalesce(ad_group_id::text,''),
    max(coalesce(keyword_type,'')), coalesce(match_type,''), coalesce(targeting,''),
    max(keyword_bid), to_char(date,'YYYY-MM') as month,
    sum(impressions)::bigint, sum(clicks)::bigint, round(sum(spend)::numeric,2),
    sum("7_day_total_orders")::bigint, round(sum("7_day_total_sales")::numeric,2)
  from ads_sponsored_products_targeting
  where campaign_id is not null and date is not null
  group by campaign_id, coalesce(ad_group_id::text,''),
    coalesce(match_type,''), coalesce(targeting,''), to_char(date,'YYYY-MM')"""

az = azure(); ac = az.cursor(); ac.execute(SQL)
rows = [(REGION, 'SP', month, cid, agid, clean(ktype), clean(mtype), clean(tgt), bid, impr, clk, spend, orders, sales)
        for cid, agid, ktype, mtype, tgt, bid, month, impr, clk, spend, orders, sales in ac.fetchall()]
az.close()
print(f"  Azure SP targeting: {len(rows):,} (campaign×ad_group×target×month) rows")

sp = supa(); sc = sp.cursor()
sc.execute("""create table if not exists ad_targeting (
  region text, program text, month text, campaign_id bigint, ad_group_id text,
  keyword_type text, match_type text, targeting text, keyword_bid numeric,
  impressions bigint, clicks bigint, spend numeric, orders bigint, sales numeric,
  primary key (region, program, month, campaign_id, ad_group_id, targeting, match_type));""")
execute_values(sc, """insert into ad_targeting
  (region,program,month,campaign_id,ad_group_id,keyword_type,match_type,targeting,keyword_bid,
   impressions,clicks,spend,orders,sales) values %s
  on conflict (region,program,month,campaign_id,ad_group_id,targeting,match_type) do update set
    keyword_type=excluded.keyword_type, keyword_bid=excluded.keyword_bid,
    impressions=excluded.impressions, clicks=excluded.clicks, spend=excluded.spend,
    orders=excluded.orders, sales=excluded.sales""",
  rows, page_size=5000)
sp.commit()
sc.execute("select min(month),max(month),count(*) from ad_targeting")
print("  ad_targeting:", sc.fetchone())
sp.close()
print("✓ refresh_targeting complete (accumulator: upserted)")
