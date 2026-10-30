#!/usr/bin/env python3
"""Load US Amazon ads (USA Reason Azure DB) into the Supabase ad_*/sd_* tables with region='US',
mirroring the Canada pipeline exactly. US schema is a superset of CA; every CA target maps 1:1.

- Source: USA Reason public.ads_* (.secrets/usa-reason.env). MULTI-TENANT but US sells ALL brands → NO account filter (D-005).
- Target: Supabase via pooler (.secrets/supabase.env PGPASSWORD).
- Dry-run by DEFAULT (reads source, prints QC, writes NOTHING). Pass --write to load Supabase.
- ad_searchterm/_week have no PK → delete-where-region+insert (NOT truncate). Others upsert on PK.

Usage: python3 data_pipeline/refresh_ads_us.py            # dry-run QC
       python3 data_pipeline/refresh_ads_us.py --write     # actually load prod
"""
import os, sys, psycopg2
from psycopg2.extras import execute_values

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCT = None  # D-005: US sells/advertises ALL brands — no account filter (was "LifePro Fitness")
REGION = "US"
WRITE = "--write" in sys.argv

def _env(fn):
    d = {}
    for line in open(os.path.join(ROOT, ".secrets", fn)):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1); d[k.strip()] = v.strip().strip('"').strip("'")
    return d

def us_conn():
    e = _env("usa-reason.env")
    return psycopg2.connect(host=e["USA_REASON_PGHOST"], port=e.get("USA_REASON_PGPORT", "5432"),
        dbname=e["USA_REASON_PGDATABASE"], user=e["USA_REASON_PGUSER"], password=e["USA_REASON_PGPASSWORD"],
        sslmode="require", connect_timeout=60)

def sb_conn():
    e = _env("supabase.env")
    return psycopg2.connect(host="aws-0-us-east-1.pooler.supabase.com", port=5432,
        user="postgres.vhrzfsceziyqbrwwwhxv", password=e["PGPASSWORD"], dbname="postgres",
        sslmode="require", connect_timeout=60)

def pexpr(grain):
    return "to_char(date,'YYYY-MM')" if grain == "month" else "date_trunc('week',date)::date"

# campaign_id is text numeric in US; guard against '' / non-numeric before ::bigint
CID_OK = "campaign_id ~ '^[0-9]+$'"

def lane_searchterm(grain):
    px = pexpr(grain)
    sp = f"""select 'US','SP', {px} as period, campaign_id::bigint, customer_search_term,
        sum(impressions), sum(clicks), round(sum(spend)::numeric,2),
        round(sum("7_day_total_sales")::numeric,2), sum("7_day_total_orders"), sum("7_day_total_units"),
        round(sum("7_day_advertised_sku_sales")::numeric,2), null::real, null::real
      from public.ads_sponsored_products_search_term
      where date is not null and {CID_OK} and customer_search_term is not null
      group by campaign_id::bigint, customer_search_term, {px}"""
    sb = f"""select 'US','SB', {px} as period, campaign_id::bigint, customer_search_term,
        sum(impressions), sum(clicks), round(sum(spend)::numeric,2),
        round(sum("14_day_total_sales")::numeric,2), sum("14_day_total_orders"), null::bigint,
        round(sum("14_day_same_sku_sales")::numeric,2),
        round(avg(search_term_impression_share)::numeric,4), round(avg(search_term_impression_rank)::numeric,1)
      from public.ads_sponsored_brands_search_term
      where date is not null and {CID_OK} and customer_search_term is not null
      group by campaign_id::bigint, customer_search_term, {px}"""
    cols = ["region","program",("month" if grain=="month" else "week"),"campaign_id","customer_search_term",
            "impressions","clicks","spend","sales","orders","units","adv_sku_sales","impr_share","impr_rank"]
    return ("ad_searchterm" if grain=="month" else "ad_searchterm_week"), cols, None, [(sp,[]),(sb,[])]

def lane_asin(grain):
    px = pexpr(grain)
    q = f"""select 'US','SP', {px} as period, campaign_id::bigint, coalesce(advertised_asin,''),
        sum(impressions), sum(clicks), round(sum(spend)::numeric,2),
        sum("7_day_total_orders"), round(sum("7_day_total_sales")::numeric,2),
        round(sum("7_day_advertised_sku_sales")::numeric,2), round(sum("7_day_other_sku_sales")::numeric,2)
      from public.ads_sponsored_products_advertised_product
      where date is not null and {CID_OK}
      group by campaign_id::bigint, coalesce(advertised_asin,''), {px}"""
    pc = "month" if grain=="month" else "week"
    cols = ["region","program",pc,"campaign_id","advertised_asin","impressions","clicks","spend","orders","sales","adv_sku_sales","other_sku_sales"]
    pk = ["region","program",pc,"campaign_id","advertised_asin"]
    return ("ad_asin_month" if grain=="month" else "ad_asin_week"), cols, pk, [(q,[])]

def lane_placement(grain):
    px = pexpr(grain)
    q = f"""select 'US','SP', {px} as period, campaign_id::bigint, coalesce(placement_type,''), max(campaign_bidding_strategy),
        sum(impressions), sum(clicks), round(sum(spend)::numeric,2),
        sum("7_day_total_orders"), round(sum("7_day_total_sales")::numeric,2)
      from public.ads_sponsored_products_campaign_placements
      where date is not null and {CID_OK}
      group by campaign_id::bigint, coalesce(placement_type,''), {px}"""
    pc = "month" if grain=="month" else "week"
    cols = ["region","program",pc,"campaign_id","placement_type","bidding_strategy","impressions","clicks","spend","orders","sales"]
    pk = ["region","program",pc,"campaign_id","placement_type"]
    return ("ad_placement_month" if grain=="month" else "ad_placement_week"), cols, pk, [(q,[])]

def lane_targeting(grain):
    px = pexpr(grain)
    q = f"""select 'US','SP', {px} as period, campaign_id::bigint, coalesce(ad_group_id::text,''),
        max(coalesce(keyword_type,'')), coalesce(match_type,''), coalesce(targeting,''), max(keyword_bid),
        sum(impressions), sum(clicks), round(sum(spend)::numeric,2),
        sum("7_day_total_orders"), round(sum("7_day_total_sales")::numeric,2)
      from public.ads_sponsored_products_targeting
      where date is not null and {CID_OK}
      group by campaign_id::bigint, coalesce(ad_group_id::text,''), coalesce(match_type,''), coalesce(targeting,''), {px}"""
    pc = "month" if grain=="month" else "week"
    cols = ["region","program",pc,"campaign_id","ad_group_id","keyword_type","match_type","targeting","keyword_bid","impressions","clicks","spend","orders","sales"]
    pk = ["region","program",pc,"campaign_id","ad_group_id","targeting","match_type"]
    return ("ad_targeting" if grain=="month" else "ad_targeting_week"), cols, pk, [(q,[])]

def lane_sd(grain):
    px = pexpr(grain)
    q = f"""select 'US', {px} as period, campaign_id::bigint, max(campaign_name),
        sum(impressions), sum(clicks), round(sum(spend)::numeric,2),
        round(sum("14_day_total_sales")::numeric,2), round(sum("14_day_total_orders"))::bigint,
        round(sum("14_day_new_to_brand_sales")::numeric,2), round(sum("14_day_new_to_brand_orders"))::bigint,
        sum("14_day_dpv")::bigint, sum(add_to_cart)::bigint, round(sum("view_attributed_sales_14d")::numeric,2)
      from public.ads_sponsored_display_campaign
      where date is not null and {CID_OK}
      group by campaign_id::bigint, {px}"""
    pc = "month" if grain=="month" else "week"
    cols = ["region",pc,"campaign_id","campaign_name","impressions","clicks","spend","sales","orders","ntb_sales","ntb_orders","dpv","atc","view_sales"]
    pk = ["region",pc,"campaign_id"]
    return ("sd_campaign_month" if grain=="month" else "sd_campaign_week"), cols, pk, [(q,[])]

LANES = [lane_searchterm, lane_asin, lane_placement, lane_targeting, lane_sd]

def main():
    us = us_conn(); sb = sb_conn() if WRITE else None
    print(f"MODE: {'WRITE (loading prod)' if WRITE else 'DRY-RUN (no writes)'} | account='{ACCT}' | region='{REGION}'\n")
    for grain in ("month", "week"):
        for lane in LANES:
            table, cols, pk, selects = lane(grain)
            rows = []
            uc = us.cursor()
            for sql, params in selects:
                uc.execute(sql, params); rows += uc.fetchall()
            uc.close()
            # QC: spend/sales indices
            si = cols.index("spend"); sl = cols.index("sales")
            tot_spend = sum((r[si] or 0) for r in rows); tot_sales = sum((r[sl] or 0) for r in rows)
            print(f"  {table:22} rows={len(rows):>7}  spend={float(tot_spend):>12,.0f}  sales={float(tot_sales):>13,.0f}")
            if rows:
                print(f"      sample: {rows[0]}")
            if WRITE and rows:
                c = sb.cursor()
                if pk is None:  # searchterm — replace region
                    c.execute(f"delete from {table} where region=%s", (REGION,))
                    execute_values(c, f"insert into {table} ({','.join(cols)}) values %s", rows, page_size=1000)
                else:
                    noncpk = [x for x in cols if x not in pk]
                    setc = ",".join(f"{x}=excluded.{x}" for x in noncpk)
                    execute_values(c, f"insert into {table} ({','.join(cols)}) values %s on conflict ({','.join(pk)}) do update set {setc}", rows, page_size=1000)
                sb.commit(); c.close()
                print(f"      -> wrote {len(rows)} rows to {table}")
    us.close()
    if sb: sb.close()
    print("\nDONE." + ("" if WRITE else "  (dry-run — re-run with --write to load Supabase)"))

if __name__ == "__main__":
    main()
