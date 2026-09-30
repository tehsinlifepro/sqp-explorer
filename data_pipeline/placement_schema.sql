-- Sprint 4: SP placement data (Top-of-Search vs Product pages vs Rest of Search). Canada / Vendor Central.
create table if not exists ad_placement_month (
  region text, program text, month text, campaign_id bigint, placement_type text, bidding_strategy text,
  impressions bigint, clicks bigint, spend numeric, orders bigint, sales numeric,
  primary key (region, program, month, campaign_id, placement_type));
alter table ad_placement_month enable row level security;
drop policy if exists sel_auth on ad_placement_month;
create policy sel_auth on ad_placement_month for select to authenticated using (true);
grant select on ad_placement_month to authenticated;

create or replace view v_placement_family_month with (security_invoker=on) as
  select p.region, p.month, coalesce(nullif(m.manual_family,''),m.auto_family) as family, p.placement_type,
    sum(p.impressions) impressions, sum(p.clicks) clicks, round(sum(p.spend),2) spend,
    sum(p.orders) orders, round(sum(p.sales),2) sales
  from ad_placement_month p left join campaign_map m on p.program=m.program and p.campaign_id=m.campaign_id
  group by 1,2,3,4;
grant select on v_placement_family_month to authenticated;
