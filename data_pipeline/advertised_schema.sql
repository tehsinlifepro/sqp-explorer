-- Sprint 6: SP advertised-product (ASIN-level) data — variation science. Canada / Vendor Central.
create table if not exists ad_asin_month (
  region text, program text, month text, campaign_id bigint, advertised_asin text,
  impressions bigint, clicks bigint, spend numeric, orders bigint, sales numeric,
  adv_sku_sales numeric, other_sku_sales numeric,
  primary key (region, program, month, campaign_id, advertised_asin));
alter table ad_asin_month enable row level security;
drop policy if exists sel_auth on ad_asin_month;
create policy sel_auth on ad_asin_month for select to authenticated using (true);
grant select on ad_asin_month to authenticated;

-- per advertised ASIN per month, with catalog family/model (aggregate across campaigns)
create or replace view v_ad_asin_month with (security_invoker=on) as
  select a.region, a.month, a.advertised_asin as asin, c.family, c.model,
    sum(a.impressions) impressions, sum(a.clicks) clicks, round(sum(a.spend),2) spend,
    sum(a.orders) orders, round(sum(a.sales),2) sales,
    round(sum(a.adv_sku_sales),2) adv_sku_sales, round(sum(a.other_sku_sales),2) other_sku_sales
  from ad_asin_month a left join catalog c on c.region=a.region and c.asin=a.advertised_asin
  group by 1,2,3,4,5;
grant select on v_ad_asin_month to authenticated;
