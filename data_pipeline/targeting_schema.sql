-- Sprint 3: targeting-level SP data (the "wasted ad spend table" + harvest). Canada / Vendor Central.
create table if not exists ad_targeting (
  region text, program text, month text, campaign_id bigint, ad_group_id text,
  keyword_type text, match_type text, targeting text, keyword_bid numeric,
  impressions bigint, clicks bigint, spend numeric, orders bigint, sales numeric,
  primary key (region, program, month, campaign_id, ad_group_id, targeting, match_type));
alter table ad_targeting enable row level security;
drop policy if exists sel_auth on ad_targeting;
create policy sel_auth on ad_targeting for select to authenticated using (true);
grant select on ad_targeting to authenticated;

-- targeting rows with their campaign's family (for the wasted-spend view; month-interactive in the UI)
create or replace view v_targeting_enriched with (security_invoker=on) as
  select t.region, t.program, t.month, coalesce(nullif(m.manual_family,''),m.auto_family) as family,
    t.keyword_type, t.match_type, t.targeting, t.keyword_bid,
    t.impressions, t.clicks, t.spend, t.orders, t.sales,
    t.campaign_id, t.ad_group_id, m.campaign_name
  from ad_targeting t left join campaign_map m on t.program=m.program and t.campaign_id=m.campaign_id;

-- harvest: SP customer search terms that CONVERT but are NOT yet an exact target (all-time; a cumulative recommendation)
create or replace view v_ad_harvest with (security_invoker=on) as
  select a.region, coalesce(nullif(m.manual_family,''),m.auto_family) as family, a.customer_search_term as term,
    round(sum(a.spend),2) spend, round(sum(a.sales),2) sales, sum(a.orders) orders, sum(a.clicks) clicks
  from ad_searchterm a
  join campaign_map m on a.program=m.program and a.campaign_id=m.campaign_id
  where a.program='SP'
  group by 1,2,3
  having sum(a.orders) >= 1
    and not exists (select 1 from ad_targeting t
      where t.region=a.region and lower(t.targeting)=lower(a.customer_search_term) and t.match_type ilike 'exact');

grant select on v_targeting_enriched, v_ad_harvest to authenticated;
