-- Sprint W2: weekly twins of the ad + retail (TACOS) tables & views.
-- Week key = ISO Monday-start week-start DATE (date_trunc('week',date)::date), identical to the
-- organic SQP _week tables and the ad weekly bucketing, so cross-source weekly joins align.
-- IMPORTANT: retail weeks are built from period='DAILY' (refresh_ra.py GRAIN=week), NOT Amazon's
-- native period='WEEKLY' rows (those are Sunday-start and would misalign with Monday-start ad weeks).
-- campaign_map is grain-independent (shared) — no weekly twin; weekly views join the same campaign_map.

create table if not exists ad_searchterm_week (
  region text, program text, week date, campaign_id bigint, customer_search_term text,
  impressions bigint, clicks bigint, spend numeric, sales numeric, orders bigint,
  units bigint, adv_sku_sales numeric, impr_share real, impr_rank real);
create index if not exists idx_astw_prog_camp on ad_searchterm_week(program, campaign_id);
create index if not exists idx_astw_rpw on ad_searchterm_week(region, program, week);
alter table ad_searchterm_week enable row level security;
drop policy if exists sel_auth on ad_searchterm_week;
create policy sel_auth on ad_searchterm_week for select to authenticated using (true);
grant select on ad_searchterm_week to authenticated;

create table if not exists ra_sales_week (
  region text, asin text, week date,
  ordered_rev numeric, shipped_rev numeric, shipped_cogs numeric,
  ordered_units bigint, shipped_units bigint,
  primary key (region, asin, week));
alter table ra_sales_week enable row level security;
drop policy if exists sel_auth on ra_sales_week;
create policy sel_auth on ra_sales_week for select to authenticated using (true);
grant select on ra_sales_week to authenticated;

-- ── weekly views (mirror the monthly views, period col = week) ────────────────
create or replace view v_ad_family_week with (security_invoker=on) as
 select a.region,a.program,a.week, coalesce(nullif(m.manual_family,''),m.auto_family) as family,
   sum(a.impressions) impressions, sum(a.clicks) clicks, round(sum(a.spend),2) spend,
   round(sum(a.sales),2) sales, sum(a.orders) orders, count(distinct a.customer_search_term) terms,
   sum(a.units) units, round(sum(a.adv_sku_sales),2) adv_sku_sales
 from ad_searchterm_week a left join campaign_map m on a.program=m.program and a.campaign_id=m.campaign_id
 group by 1,2,3,4;

create or replace view v_ad_family_searchterm_week with (security_invoker=on) as
 select a.region,a.program,a.week, coalesce(nullif(m.manual_family,''),m.auto_family) as family,
   a.customer_search_term, sum(a.impressions) impressions, sum(a.clicks) clicks, round(sum(a.spend),2) spend,
   round(sum(a.sales),2) sales, sum(a.orders) orders, sum(a.units) units,
   round(sum(a.adv_sku_sales),2) adv_sku_sales, max(a.impr_share) impr_share, min(a.impr_rank) impr_rank
 from ad_searchterm_week a left join campaign_map m on a.program=m.program and a.campaign_id=m.campaign_id
 group by 1,2,3,4,5;
grant select on v_ad_family_week, v_ad_family_searchterm_week to authenticated;

create or replace view v_ra_family_week with (security_invoker=on) as
  select r.region, c.family, r.week,
    round(sum(r.ordered_rev),2) ordered_rev, round(sum(r.shipped_rev),2) shipped_rev,
    round(sum(r.shipped_cogs),2) shipped_cogs, sum(r.ordered_units) ordered_units
  from ra_sales_week r join catalog c on c.region=r.region and c.asin=r.asin
  where c.family is not null
  group by 1,2,3;

create or replace view v_ad_fam_week_all with (security_invoker=on) as
  select region, family, week, round(sum(spend),2) ad_spend, round(sum(sales),2) ad_sales, sum(orders) ad_orders
  from v_ad_family_week where family is not null group by 1,2,3;

create or replace view v_tacos_family_week with (security_invoker=on) as
  select coalesce(s.region,a.region) as region, coalesce(s.family,a.family) as family, coalesce(s.week,a.week) as week,
    coalesce(s.ordered_rev,0) ordered_rev, coalesce(s.shipped_rev,0) shipped_rev, coalesce(s.shipped_cogs,0) shipped_cogs,
    coalesce(a.ad_spend,0) ad_spend, coalesce(a.ad_sales,0) ad_sales, coalesce(a.ad_orders,0) ad_orders
  from v_ra_family_week s full join v_ad_fam_week_all a
    on a.region=s.region and a.family=s.family and a.week=s.week;
grant select on v_ra_family_week, v_ad_fam_week_all, v_tacos_family_week to authenticated;
