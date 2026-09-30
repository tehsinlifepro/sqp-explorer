-- Sprint 7: Sponsored Display (upper funnel — new-to-brand, DPV, ATC, view-through). Canada / Vendor Central.
-- Account-level: SD campaigns aren't in campaign_map (that's SP/SB), so SD is shown at account level.
create table if not exists sd_campaign_month (
  region text, month text, campaign_id bigint, campaign_name text,
  impressions bigint, clicks bigint, spend numeric, sales numeric, orders bigint,
  ntb_sales numeric, ntb_orders bigint, dpv bigint, atc bigint, view_sales numeric,
  primary key (region, month, campaign_id));
alter table sd_campaign_month enable row level security;
drop policy if exists sel_auth on sd_campaign_month;
create policy sel_auth on sd_campaign_month for select to authenticated using (true);
grant select on sd_campaign_month to authenticated;

create or replace view v_sd_month with (security_invoker=on) as
  select region, month, round(sum(spend),2) spend, sum(impressions) impressions, sum(clicks) clicks,
    round(sum(sales),2) sales, sum(orders) orders, round(sum(ntb_sales),2) ntb_sales, sum(ntb_orders) ntb_orders,
    sum(dpv) dpv, sum(atc) atc, round(sum(view_sales),2) view_sales
  from sd_campaign_month group by 1,2;
grant select on v_sd_month to authenticated;
