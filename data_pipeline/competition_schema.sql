-- Competition Watch (WS3) tables. Idempotent. Applied via apply_sql.py (gated prod write).
-- RLS mirrors the project convention (sel_auth: SELECT to authenticated).

-- Raw Keepa response cache so re-runs never re-spend tokens (also an audit trail).
create table if not exists keepa_raw (
  domain int, kind text, key text, payload jsonb, fetched_at timestamptz default now(),
  primary key (domain, kind, key));

-- Per-ASIN competitor snapshot (our ASINs + discovered competitors), per region+category.
create table if not exists competition_asin (
  region text, category text, asin text, brand text,
  monthly_sold bigint, bsr int, price numeric, rating real, review_count int,
  is_ours boolean default false, updated date,
  primary key (region, category, asin));

-- Per-brand subcategory market share (the headline table the tab reads).
create table if not exists competition_brand (
  region text, category text, brand text,
  units_monthly bigint, asin_count int, share numeric, is_ours boolean default false,
  rnk int, updated date,
  primary key (region, category, brand));

-- Enrichment columns on competition_brand (free + tiny-surcharge Keepa signals, per brand's lead ASIN).
alter table competition_brand add column if not exists rating real;
alter table competition_brand add column if not exists review_count int;
alter table competition_brand add column if not exists price numeric;
alter table competition_brand add column if not exists oos_pct real;
alter table competition_brand add column if not exists rank_drops int;
alter table competition_brand add column if not exists amazon_on boolean;
alter table competition_brand add column if not exists bb_amazon boolean;

-- Subcategory BSR rank history (Serpstat-style multi-line trend), per brand's representative ASIN.
create table if not exists competition_rank_history (
  region text, category text, brand text, asin text, date date, bsr int,
  primary key (region, category, asin, date));

do $$
declare t text;
begin
  foreach t in array array['keepa_raw','competition_asin','competition_brand','competition_rank_history'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists sel_auth on %I', t);
    execute format('create policy sel_auth on %I for select to authenticated using (true)', t);
    execute format('grant select on %I to authenticated', t);
  end loop;
end $$;
