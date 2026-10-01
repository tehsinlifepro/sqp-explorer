#!/usr/bin/env python3
"""Monthly Retail-Analytics refresh: Azure (Canada Vendor Central) -> Supabase ra_sales_month.

The TACOS denominator. Pulls MONTHLY / Manufacturing ordered+shipped revenue, COGS and units per ASIN
(distributor_view='Manufacturing' — 'Sourcing' is empty and would double-count). ordered_rev = the
Amazon.ca ordered (retail) revenue used as "total sales" for TACOS = ad_spend / ordered_rev.

ACCUMULATOR: upsert on (region,asin,month) — never truncate — so history is preserved even though the
source is a rolling window (same golden rule as the SQP month tables).

Needs Azure + Supabase. Part of the monthly DB lane (refresh_db.sh).
Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/refresh_ra.py
"""
import os, psycopg2
from psycopg2.extras import execute_values
REGION = 'CA'
# GRAIN switch: 'month' (default) upserts ra_sales_month from period='MONTHLY'; 'week' upserts
# ra_sales_week from period='DAILY' bucketed to ISO Monday week-start — DAILY (not Amazon's native
# Sunday-start WEEKLY rows) so retail weeks align with the Monday-start ad/organic weeks for TACOS.
GRAIN = os.environ.get('GRAIN', 'month')
TBL   = 'ra_sales_month' if GRAIN == 'month' else 'ra_sales_week'
PCOL  = 'month' if GRAIN == 'month' else 'week'
PERIOD_SRC = 'MONTHLY' if GRAIN == 'month' else 'DAILY'
PEXPR = "to_char(date,'YYYY-MM')" if GRAIN == 'month' else "date_trunc('week',date)::date"

def azure():
    return psycopg2.connect(host=os.environ['AZURE_PG_HOST'], port=os.environ.get('AZURE_PG_PORT', '5432'),
        user=os.environ['AZURE_PG_USER'], password=os.environ['AZURE_PG_PASSWORD'],
        dbname=os.environ['AZURE_PG_DB'], sslmode='require', connect_timeout=40)
def supa():
    return psycopg2.connect(host=os.environ['PGHOST'], port=os.environ.get('PGPORT', '5432'),
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        dbname=os.environ.get('PGDATABASE', 'postgres'), sslmode='require', connect_timeout=40)

SQL = f"""select asin, {PEXPR} as {PCOL},
    round(sum(ordered_revenue)::numeric,2), round(sum(shipped_revenue)::numeric,2),
    round(sum(shipped_cogs)::numeric,2), sum(ordered_units)::bigint, sum(shipped_units)::bigint
  from retail_analytics_sales
  where period='{PERIOD_SRC}' and distributor_view='Manufacturing' and asin is not null
  group by asin, {PEXPR}"""

az = azure(); ac = az.cursor(); ac.execute(SQL)
rows = [(REGION, asin, period, orev, srev, cogs, ou, su)
        for asin, period, orev, srev, cogs, ou, su in ac.fetchall()]
az.close()
print(f"  Azure retail_analytics_sales ({PERIOD_SRC}): {len(rows):,} (asin×{PCOL}) rows")

sp = supa(); sc = sp.cursor()
# ensure table exists (idempotent) before upsert
if GRAIN == 'month':
    sc.execute("""create table if not exists ra_sales_month (
      region text, asin text, month text, ordered_rev numeric, shipped_rev numeric, shipped_cogs numeric,
      ordered_units bigint, shipped_units bigint, primary key (region, asin, month));""")
else:
    sc.execute("""create table if not exists ra_sales_week (
      region text, asin text, week date, ordered_rev numeric, shipped_rev numeric, shipped_cogs numeric,
      ordered_units bigint, shipped_units bigint, primary key (region, asin, week));""")
execute_values(sc, f"""insert into {TBL}
  (region,asin,{PCOL},ordered_rev,shipped_rev,shipped_cogs,ordered_units,shipped_units) values %s
  on conflict (region,asin,{PCOL}) do update set
    ordered_rev=excluded.ordered_rev, shipped_rev=excluded.shipped_rev, shipped_cogs=excluded.shipped_cogs,
    ordered_units=excluded.ordered_units, shipped_units=excluded.shipped_units""",
  rows, page_size=2000)
sp.commit()
sc.execute(f"select min({PCOL}),max({PCOL}),count(*),count(distinct asin) from {TBL}")
print(f"  {TBL}:", sc.fetchone())
sp.close()
print("✓ refresh_ra complete (accumulator: upserted, history preserved)")
