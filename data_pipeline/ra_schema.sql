-- Sprint 2: Retail-Analytics total sales (the TACOS denominator). Canada / Vendor Central only.
-- ordered_rev = Amazon.ca ordered (retail) revenue = "total sales" for TACOS (ad_spend / ordered_rev).
-- NOTE: shipped_cogs is Amazon's cost (the vendor's payment), NOT LifePro's product COGS — so it is
-- stored for reference but must NOT be shown as LifePro gross margin (real margin = the Blended sheet).
create table if not exists ra_sales_month (
  region text, asin text, month text,
  ordered_rev numeric, shipped_rev numeric, shipped_cogs numeric,
  ordered_units bigint, shipped_units bigint,
  primary key (region, asin, month));
alter table ra_sales_month enable row level security;
drop policy if exists sel_auth on ra_sales_month;
create policy sel_auth on ra_sales_month for select to authenticated using (true);
grant select on ra_sales_month to authenticated;

-- family-level total sales (ra ⋈ catalog family)
create or replace view v_ra_family_month with (security_invoker=on) as
  select r.region, c.family, r.month,
    round(sum(r.ordered_rev),2) ordered_rev, round(sum(r.shipped_rev),2) shipped_rev,
    round(sum(r.shipped_cogs),2) shipped_cogs, sum(r.ordered_units) ordered_units
  from ra_sales_month r join catalog c on c.region=r.region and c.asin=r.asin
  where c.family is not null
  group by 1,2,3;

-- ad spend/sales per family-month, collapsed across program (SP+SB)
create or replace view v_ad_fam_month_all with (security_invoker=on) as
  select region, family, month, round(sum(spend),2) ad_spend, round(sum(sales),2) ad_sales, sum(orders) ad_orders
  from v_ad_family_month where family is not null group by 1,2,3;

-- TACOS join: total sales ⋈ ad spend (full outer so a family with sales-but-no-ads, or ads-but-no-sales, still shows)
create or replace view v_tacos_family_month with (security_invoker=on) as
  select coalesce(s.region,a.region) as region, coalesce(s.family,a.family) as family, coalesce(s.month,a.month) as month,
    coalesce(s.ordered_rev,0) ordered_rev, coalesce(s.shipped_rev,0) shipped_rev, coalesce(s.shipped_cogs,0) shipped_cogs,
    coalesce(a.ad_spend,0) ad_spend, coalesce(a.ad_sales,0) ad_sales, coalesce(a.ad_orders,0) ad_orders
  from v_ra_family_month s full join v_ad_fam_month_all a
    on a.region=s.region and a.family=s.family and a.month=s.month;
grant select on v_ra_family_month, v_ad_fam_month_all, v_tacos_family_month to authenticated;
