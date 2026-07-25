-- ============================================================================
-- rank_daily = the DURABLE ACCUMULATOR (permanent record of every rank snapshot).
-- The Datarova source only exposes a rolling ~30-day window, so we UPSERT each
-- pull into this table and NEVER truncate it. rank_family_day / rank_family_keyword
-- below are pure DERIVATIONS re-computed from the full accumulator on every refresh.
-- See data_pipeline/refresh_ranks.py.
-- ============================================================================
create table if not exists rank_daily (
  marketplace text, project text, keyword text, date date, ranked_asin text default '',
  organic_rank real, sponsored_rank real, ac_badge boolean,
  primary key (marketplace, project, keyword, date, ranked_asin));
create index if not exists idx_rank_daily_mkt_date on rank_daily(marketplace, date);
alter table rank_daily enable row level security;
do $$ begin
  execute 'drop policy if exists sel_auth on rank_daily';
  execute 'create policy sel_auth on rank_daily for select to authenticated using (true)';
end $$;
grant select on rank_daily to authenticated;

create table if not exists rank_family_day (
  region text, family text, date text,
  kw_tracked int, kw_ranked int, kw_top10 int, kw_top50 int, median_rank real,
  primary key (region, family, date));
create table if not exists rank_family_keyword (
  region text, family text, keyword text,
  latest_rank real, best_rank real, avg_rank real, days_tracked int, days_ranked int,
  ac_badge boolean, trend text,
  primary key (region, family, keyword));
create index if not exists idx_rfd_rf on rank_family_day(region, family);
create index if not exists idx_rfk_rf on rank_family_keyword(region, family);
alter table rank_family_day enable row level security;
alter table rank_family_keyword enable row level security;
do $$ declare t text; begin
 foreach t in array array['rank_family_day','rank_family_keyword'] loop
  execute format('drop policy if exists sel_auth on %I;', t);
  execute format('create policy sel_auth on %I for select to authenticated using (true);', t);
 end loop; end $$;
grant select on rank_family_day, rank_family_keyword to authenticated;
