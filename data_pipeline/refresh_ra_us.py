#!/usr/bin/env python3
"""US Retail-Analytics sales -> Supabase ra_sales_month/week (region='US') — the TACOS denominator.
Mirrors refresh_ra.py (CA). Source: USA Reason public.retail_analytics_sales (single-tenant, LifePro
Vendor Central), distributor_view='Manufacturing'. Scoped to our US catalog ASINs. Upsert on PK.
month: period='MONTHLY' -> to_char(date,'YYYY-MM'); week: period='DAILY' bucketed to ISO-Monday (matches ad_*_week keys).
Usage: python3 data_pipeline/refresh_ra_us.py [--write]
"""
import os, sys, psycopg2
from psycopg2.extras import execute_values
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRITE = "--write" in sys.argv
def env(fn):
    d={}
    for line in open(os.path.join(ROOT,".secrets",fn)):
        line=line.strip()
        if "=" in line and not line.startswith("#"):
            k,v=line.split("=",1); d[k.strip()]=v.strip().strip('"').strip("'")
    return d
se=env("supabase.env"); ue=env("usa-reason.env")
sb=psycopg2.connect(host="aws-0-us-east-1.pooler.supabase.com",port=5432,user="postgres.vhrzfsceziyqbrwwwhxv",password=se["PGPASSWORD"],dbname="postgres",sslmode="require",connect_timeout=60)
sc=sb.cursor(); sc.execute("select asin from catalog where region='US' and asin is not null"); our=[r[0] for r in sc.fetchall()]
us=psycopg2.connect(host=ue["USA_REASON_PGHOST"],port=5432,dbname=ue["USA_REASON_PGDATABASE"],user=ue["USA_REASON_PGUSER"],password=ue["USA_REASON_PGPASSWORD"],sslmode="require",connect_timeout=60)
uc=us.cursor()
for grain in ("month","week"):
    tbl = "ra_sales_month" if grain=="month" else "ra_sales_week"
    pcol = "month" if grain=="month" else "week"
    if grain=="month":
        where="period='MONTHLY'"; px="to_char(date,'YYYY-MM')"
    else:
        where="period='DAILY'"; px="date_trunc('week',date)::date"
    uc.execute(f"""select asin, {px} as period,
        round(sum(ordered_revenue)::numeric,2), round(sum(shipped_revenue)::numeric,2),
        round(sum(shipped_cogs)::numeric,2), sum(ordered_units)::bigint, sum(shipped_units)::bigint
      from public.retail_analytics_sales
      where {where} and distributor_view='Manufacturing' and asin = any(%s) and date is not null
      group by asin, {px}""",(our,))
    rows=[('US',)+r for r in uc.fetchall()]
    tot=sum((r[3] or 0) for r in rows)
    print(f"  {tbl}: {len(rows)} rows, ordered_rev total ${float(tot):,.0f}")
    if rows: print(f"     sample: {rows[0]}")
    if WRITE and rows:
        execute_values(sc, f"""insert into {tbl} (region,asin,{pcol},ordered_rev,shipped_rev,shipped_cogs,ordered_units,shipped_units)
          values %s on conflict (region,asin,{pcol}) do update set ordered_rev=excluded.ordered_rev,
          shipped_rev=excluded.shipped_rev, shipped_cogs=excluded.shipped_cogs,
          ordered_units=excluded.ordered_units, shipped_units=excluded.shipped_units""", rows, page_size=1000)
        sb.commit(); print(f"     -> wrote {len(rows)} rows to {tbl}")
uc.close(); us.close(); sc.close(); sb.close()
print("DONE." + ("" if WRITE else "  (dry-run)"))
