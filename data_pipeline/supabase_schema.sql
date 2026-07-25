-- SQP Explorer — Supabase / Postgres schema
-- Run this in the Supabase SQL editor BEFORE importing the CSVs from data_export/.
-- Access model: PUBLIC app, gated by a shared login (the "code").
--   RLS grants SELECT only to authenticated users, so the anon key alone returns nothing.
--   You create ONE shared auth user (see README); its password IS the access code.

create table if not exists catalog (
  region text, asin text, brand text, model text, sku text,
  family text, category text, ppc_listing text, product_manager text,
  primary key (region, asin)
);
create table if not exists category_month (
  region text, category text, month text,
  core_queries int, market_search_volume bigint, market_impressions bigint,
  market_clicks bigint, market_cart_adds bigint, market_purchases bigint, market_cvr numeric,
  our_impressions bigint, our_clicks bigint, our_cart_adds bigint, our_purchases bigint,
  our_impr_share numeric, our_click_share numeric, our_atc_share numeric, our_purchase_share numeric,
  our_cvr numeric, niche_median_price numeric, our_median_price numeric, price_vs_niche numeric,
  primary key (region, category, month)
);
create table if not exists family_summary (
  region text, category text, family text, asins int,
  impressions bigint, clicks bigint, purchases_12mo bigint,
  blended_cvr numeric, mkt_share_in_its_queries numeric, growth numeric, trajectory text,
  primary key (region, category, family)
);
create table if not exists asin_month (
  region text, asin text, category text, family text, month text,
  impressions bigint, clicks bigint, cart_adds bigint, purchases bigint, purchases_all_query bigint,
  primary key (region, asin, month)
);

create index if not exists idx_cm_region_cat on category_month(region, category);
create index if not exists idx_fs_region_cat on family_summary(region, category);
create index if not exists idx_am_region_asin on asin_month(region, asin);
create index if not exists idx_am_region_cat on asin_month(region, category);
create index if not exists idx_cat_region_cat on catalog(region, category);

-- ---- Row Level Security: authenticated-only reads (the shared-login gate) ----
alter table catalog          enable row level security;
alter table category_month   enable row level security;
alter table family_summary   enable row level security;
alter table asin_month       enable row level security;

do $$
declare t text;
begin
  foreach t in array array['catalog','category_month','family_summary','asin_month'] loop
    execute format('drop policy if exists "read for authenticated" on %I;', t);
    execute format('create policy "read for authenticated" on %I for select to authenticated using (true);', t);
  end loop;
end $$;

-- Nothing is granted to the anon role, so an un-logged-in visitor sees zero rows.
-- To ROTATE the access code: change the shared user's password in Supabase → Authentication → Users.
