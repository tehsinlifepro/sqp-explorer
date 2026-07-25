-- Keyword-level tables for the Keyword Explorer. Run after supabase_schema.sql.
create extension if not exists pg_trgm;

create table if not exists query_summary (
  region text, search_query text, top_category text,
  latest_volume bigint, avg_volume bigint, our_purchases_12mo bigint,
  our_purchase_share numeric, growth numeric, months_present int, trend text,
  primary key (region, search_query)
);
create table if not exists query_month (
  region text, search_query text, month text,
  search_query_volume bigint, market_impressions bigint, market_clicks bigint, market_cart_adds bigint,
  market_purchases bigint, market_median_price numeric,
  our_impressions bigint, our_clicks bigint, our_cart_adds bigint, our_purchases bigint,
  our_impr_share numeric, our_click_share numeric, our_purchase_share numeric,
  primary key (region, search_query, month)
);
create table if not exists query_asin_month (
  region text, search_query text, asin text, category text, family text, month text,
  search_query_volume bigint, asin_impressions bigint, asin_clicks bigint, asin_cart_adds bigint,
  asin_purchases bigint, asin_impr_share numeric, asin_click_share numeric, asin_purchase_share numeric,
  primary key (region, search_query, asin, month)
);

create index if not exists idx_qs_search_trgm on query_summary using gin (search_query gin_trgm_ops);
create index if not exists idx_qs_region_vol on query_summary(region, latest_volume desc);
create index if not exists idx_qs_region_trend on query_summary(region, trend);
create index if not exists idx_qs_region_cat on query_summary(region, top_category);
create index if not exists idx_qm_region_q on query_month(region, search_query);
create index if not exists idx_qam_region_q on query_asin_month(region, search_query);

alter table query_summary    enable row level security;
alter table query_month      enable row level security;
alter table query_asin_month enable row level security;
do $$ declare t text;
begin
  foreach t in array array['query_summary','query_month','query_asin_month'] loop
    execute format('drop policy if exists "read for authenticated" on %I;', t);
    execute format('create policy "read for authenticated" on %I for select to authenticated using (true);', t);
  end loop;
end $$;
