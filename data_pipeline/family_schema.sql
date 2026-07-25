-- Family Explorer tables. Run after the other schemas.
create table if not exists family_niche_month (
  region text, family text, month text,
  niche_volume bigint, niche_market_impressions bigint, niche_market_purchases bigint,
  our_purchases bigint, our_impressions bigint, our_clicks bigint, n_queries int,
  our_niche_purchase_share numeric, our_niche_impr_share numeric,
  primary key (region, family, month)
);
create table if not exists family_kw_composition (
  region text, family text, month text, keyword text, volume bigint,
  primary key (region, family, month, keyword)
);
create table if not exists family_top_keywords (
  region text, family text, search_query text,
  latest_volume bigint, our_purchases_12mo bigint, our_purchase_share numeric, trend text,
  primary key (region, family, search_query)
);
create index if not exists idx_fnm_rf on family_niche_month(region, family);
create index if not exists idx_fkc_rf on family_kw_composition(region, family);
create index if not exists idx_ftk_rf on family_top_keywords(region, family);
alter table family_niche_month enable row level security;
alter table family_kw_composition enable row level security;
alter table family_top_keywords enable row level security;
do $$ declare t text;
begin
  foreach t in array array['family_niche_month','family_kw_composition','family_top_keywords'] loop
    execute format('drop policy if exists "read for authenticated" on %I;', t);
    execute format('create policy "read for authenticated" on %I for select to authenticated using (true);', t);
  end loop;
end $$;
