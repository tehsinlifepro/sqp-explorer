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
