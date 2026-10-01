-- Sprint W3: weekly twins of the SP detail tables (targeting / placement / advertised / SD) + views.
-- Week key = ISO Monday week-start DATE (date_trunc('week',date)::date), same as every other _week table.
-- Accumulators: the refresh_*.py GRAIN=week runs upsert on the week PK, never truncate. Views reuse the
-- grain-independent campaign_map / catalog. (Harvest stays lifetime — v_ad_harvest, no weekly twin.)

create table if not exists ad_targeting_week (
  region text, program text, week date, campaign_id bigint, ad_group_id text,
  keyword_type text, match_type text, targeting text, keyword_bid numeric,
  impressions bigint, clicks bigint, spend numeric, orders bigint, sales numeric,
  primary key (region, program, week, campaign_id, ad_group_id, targeting, match_type));
create table if not exists ad_placement_week (
  region text, program text, week date, campaign_id bigint, placement_type text, bidding_strategy text,
  impressions bigint, clicks bigint, spend numeric, orders bigint, sales numeric,
  primary key (region, program, week, campaign_id, placement_type));
create table if not exists ad_asin_week (
  region text, program text, week date, campaign_id bigint, advertised_asin text,
  impressions bigint, clicks bigint, spend numeric, orders bigint, sales numeric,
  adv_sku_sales numeric, other_sku_sales numeric,
  primary key (region, program, week, campaign_id, advertised_asin));
create table if not exists sd_campaign_week (
  region text, week date, campaign_id bigint, campaign_name text,
  impressions bigint, clicks bigint, spend numeric, sales numeric, orders bigint,
  ntb_sales numeric, ntb_orders bigint, dpv bigint, atc bigint, view_sales numeric,
  primary key (region, week, campaign_id));

do $$ declare t text; begin
 foreach t in array array['ad_targeting_week','ad_placement_week','ad_asin_week','sd_campaign_week'] loop
  execute format('alter table %I enable row level security;', t);
  execute format('drop policy if exists sel_auth on %I;', t);
  execute format('create policy sel_auth on %I for select to authenticated using (true);', t);
  execute format('grant select on %I to authenticated;', t);
 end loop; end $$;

-- ── weekly views (mirror the monthly views, period col = week) ────────────────
create or replace view v_targeting_enriched_week with (security_invoker=on) as
  select t.region, t.program, t.week, coalesce(nullif(m.manual_family,''),m.auto_family) as family,
    t.keyword_type, t.match_type, t.targeting, t.keyword_bid,
    t.impressions, t.clicks, t.spend, t.orders, t.sales,
    t.campaign_id, t.ad_group_id, m.campaign_name
  from ad_targeting_week t left join campaign_map m on t.program=m.program and t.campaign_id=m.campaign_id;

create or replace view v_placement_family_week with (security_invoker=on) as
  select p.region, p.week, coalesce(nullif(m.manual_family,''),m.auto_family) as family, p.placement_type,
    sum(p.impressions) impressions, sum(p.clicks) clicks, round(sum(p.spend),2) spend,
    sum(p.orders) orders, round(sum(p.sales),2) sales
  from ad_placement_week p left join campaign_map m on p.program=m.program and p.campaign_id=m.campaign_id
  group by 1,2,3,4;

create or replace view v_ad_asin_week with (security_invoker=on) as
  select a.region, a.week, a.advertised_asin as asin, c.family, c.model,
    sum(a.impressions) impressions, sum(a.clicks) clicks, round(sum(a.spend),2) spend,
    sum(a.orders) orders, round(sum(a.sales),2) sales,
    round(sum(a.adv_sku_sales),2) adv_sku_sales, round(sum(a.other_sku_sales),2) other_sku_sales
  from ad_asin_week a left join catalog c on c.region=a.region and c.asin=a.advertised_asin
  group by 1,2,3,4,5;

create or replace view v_sd_week with (security_invoker=on) as
  select region, week, round(sum(spend),2) spend, sum(impressions) impressions, sum(clicks) clicks,
    round(sum(sales),2) sales, sum(orders) orders, round(sum(ntb_sales),2) ntb_sales, sum(ntb_orders) ntb_orders,
    sum(dpv) dpv, sum(atc) atc, round(sum(view_sales),2) view_sales
  from sd_campaign_week group by 1,2;

grant select on v_targeting_enriched_week, v_placement_family_week, v_ad_asin_week, v_sd_week to authenticated;
