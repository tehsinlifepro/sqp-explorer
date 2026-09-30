#!/usr/bin/env python3
"""Enrichment layer for the Organic Ranks + Ads deep-dive tabs.

Builds:
  1. kw_market            — Datarova "Keywords" tab: market Keyword Clicks/Sales L4W per (region,keyword)
  2. v_query_latest       — latest-month SQP impression/click/purchase share per (region,search_query)
  3. v_rank_kw_enriched   — rank_family_keyword + clicks_l4w + latest SQP volume   (Organic Ranks tab)
  4. v_ad_term_enriched   — ad family search terms + clicks_l4w + SQP volume + latest shares (Ads tab)
  5. campaign_map reclassify — brand/umbrella campaigns (by name) -> 'Brand Level' (overridable)

Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/build_enrich.py
"""
import os, pandas as pd, psycopg2
from psycopg2.extras import execute_values

KW_CSV = os.path.expanduser("~/Downloads/Datarova - Ranks & Keywords/Keywords.csv")
MKT = {"US": "US", "CA": "CA"}

def conn():
    return psycopg2.connect(host=os.environ["PGHOST"], port=os.environ.get("PGPORT", "5432"),
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"), sslmode="require", connect_timeout=25)

c = conn(); cur = c.cursor()

# ── 1. kw_market ──────────────────────────────────────────────────────────────
K = pd.read_csv(KW_CSV)
K.columns = [s.strip() for s in K.columns]
K = K.rename(columns={"Marketplace": "marketplace", "Keyword": "keyword",
                      "Keyword Clicks L4W": "clicks_l4w", "Keyword Sales L4W": "sales_l4w",
                      "Keyword Conversion": "conversion"})
K["region"] = K["marketplace"].map(MKT)
K = K[K.region.notna()].copy()
K["keyword"] = K["keyword"].astype(str).str.strip()
for col in ("clicks_l4w", "sales_l4w", "conversion"):
    K[col] = pd.to_numeric(K[col], errors="coerce")
# a keyword's market metrics are ~constant across projects → take the max per (region,keyword)
km = (K.groupby(["region", "keyword"], as_index=False)
        .agg(clicks_l4w=("clicks_l4w", "max"), sales_l4w=("sales_l4w", "max"),
             conversion=("conversion", "max")))
cur.execute("""create table if not exists kw_market(
  region text, keyword text, clicks_l4w bigint, sales_l4w bigint, conversion real,
  primary key(region,keyword));""")
cur.execute("truncate kw_market")
execute_values(cur, "insert into kw_market(region,keyword,clicks_l4w,sales_l4w,conversion) values %s",
    [(r.region, r.keyword,
      None if pd.isna(r.clicks_l4w) else int(r.clicks_l4w),
      None if pd.isna(r.sales_l4w) else int(r.sales_l4w),
      None if pd.isna(r.conversion) else float(r.conversion)) for r in km.itertuples(index=False)])
cur.execute("alter table kw_market enable row level security")
cur.execute("drop policy if exists sel_auth on kw_market")
cur.execute("create policy sel_auth on kw_market for select to authenticated using (true)")
cur.execute("grant select on kw_market to authenticated")
c.commit()
print(f"kw_market: {len(km):,} rows  ({km.region.value_counts().to_dict()})")

# ── 2-4. views ────────────────────────────────────────────────────────────────
cur.execute("""
create or replace view v_query_latest with (security_invoker=on) as
  select distinct on (region, search_query)
    region, search_query, month, search_query_volume,
    our_impr_share, our_click_share, our_purchase_share
  from query_month order by region, search_query, month desc;

create or replace view v_rank_kw_enriched with (security_invoker=on) as
  select k.region, k.family, k.keyword, k.latest_rank, k.best_rank, k.avg_rank,
         k.days_tracked, k.days_ranked, k.ac_badge, k.trend,
         m.clicks_l4w, q.latest_volume as sqp_volume,
         a.ad_spend, a.ad_orders
  from rank_family_keyword k
  left join kw_market m    on m.region=k.region and lower(m.keyword)=lower(k.keyword)
  left join query_summary q on q.region=k.region and lower(q.search_query)=lower(k.keyword)
  left join (select region, lower(customer_search_term) kw, round(sum(spend),2) ad_spend, sum(orders) ad_orders
             from ad_searchterm group by region, lower(customer_search_term)) a
         on a.region=k.region and a.kw=lower(k.keyword);

create or replace view v_ad_term_enriched with (security_invoker=on) as
  select t.region, t.program, t.month, t.family, t.customer_search_term as keyword,
         t.impressions, t.clicks, t.spend, t.sales, t.orders,
         m.clicks_l4w, ql.search_query_volume as sqp_volume,
         ql.our_impr_share, ql.our_click_share, ql.our_purchase_share,
         t.units, t.adv_sku_sales, t.impr_share as tos_impr_share, t.impr_rank as tos_impr_rank
  from v_ad_family_searchterm t
  left join kw_market m  on m.region=t.region and lower(m.keyword)=lower(t.customer_search_term)
  left join v_query_latest ql on ql.region=t.region and lower(ql.search_query)=lower(t.customer_search_term);

grant select on v_query_latest, v_rank_kw_enriched, v_ad_term_enriched to authenticated;
""")
c.commit()
print("views: v_query_latest, v_rank_kw_enriched, v_ad_term_enriched ✓")

# NOTE: campaign → family AUTO mapping is NOT done here. It lives in build_campaign_map.py
# (spend-weighted 80%-dominance rule, needs the Azure advertised-product report) and runs as part
# of the MONTHLY Ads refresh. This script stays Azure-free so it can run daily.

# ── verify enrichment coverage ────────────────────────────────────────────────
cur.execute("select count(*), count(clicks_l4w), count(sqp_volume) from v_rank_kw_enriched")
tot, wc, wv = cur.fetchone()
print(f"v_rank_kw_enriched: {tot:,} kw rows | with clicks_l4w={wc:,} | with SQP volume={wv:,}")
c.close()
print("✓ enrichment build complete")
