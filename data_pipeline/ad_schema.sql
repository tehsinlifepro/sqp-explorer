create table if not exists campaign_map (
  region text, program text, campaign_id bigint, campaign_name text, asin text,
  auto_family text, source text, status text, spend numeric, sales numeric, terms int,
  manual_family text, primary key (program, campaign_id));
create table if not exists ad_searchterm (
  region text, program text, month text, campaign_id bigint, customer_search_term text,
  impressions bigint, clicks bigint, spend numeric, sales numeric, orders bigint);
create index if not exists idx_ast_prog_camp on ad_searchterm(program, campaign_id);
create index if not exists idx_ast_rpm on ad_searchterm(region, program, month);
create index if not exists idx_ast_term_trgm on ad_searchterm using gin (customer_search_term gin_trgm_ops);
alter table campaign_map  enable row level security;
alter table ad_searchterm enable row level security;
drop policy if exists sel_auth on campaign_map; create policy sel_auth on campaign_map for select to authenticated using (true);
drop policy if exists upd_auth on campaign_map; create policy upd_auth on campaign_map for update to authenticated using (true) with check (true);
drop policy if exists sel_auth on ad_searchterm; create policy sel_auth on ad_searchterm for select to authenticated using (true);
grant select, update on campaign_map to authenticated;
grant select on ad_searchterm to authenticated;
create or replace view v_ad_family_month with (security_invoker=on) as
 select a.region,a.program,a.month, coalesce(nullif(m.manual_family,''),m.auto_family) as family,
   sum(a.impressions) impressions, sum(a.clicks) clicks, round(sum(a.spend),2) spend,
   round(sum(a.sales),2) sales, sum(a.orders) orders, count(distinct a.customer_search_term) terms
 from ad_searchterm a left join campaign_map m on a.program=m.program and a.campaign_id=m.campaign_id
 group by 1,2,3,4;
create or replace view v_ad_family_searchterm with (security_invoker=on) as
 select a.region,a.program,a.month, coalesce(nullif(m.manual_family,''),m.auto_family) as family,
   a.customer_search_term, sum(a.impressions) impressions, sum(a.clicks) clicks, round(sum(a.spend),2) spend,
   round(sum(a.sales),2) sales, sum(a.orders) orders
 from ad_searchterm a left join campaign_map m on a.program=m.program and a.campaign_id=m.campaign_id
 group by 1,2,3,4,5;
grant select on v_ad_family_month, v_ad_family_searchterm to authenticated;
