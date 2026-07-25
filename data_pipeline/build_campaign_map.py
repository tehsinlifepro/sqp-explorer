#!/usr/bin/env python3
"""Recompute SP campaign → family AUTO mapping from the advertised-product report (spend-weighted).

RULE (per Tehsin): an SP campaign auto-maps to a family only if a SINGLE family accounts for
>= 80% of the campaign's advertised-product ad spend. Campaigns whose spend is spread across
families — e.g. "[Brand] All Products - Lifepro" (advertises 17 ASINs across families) — are left
UNMAPPED so they can be mapped by hand in the Campaign Map tab (to a family, or to "Brand Level").
Never overwrites a manual_family edit.

Part of the MONTHLY Ads refresh (DB lane): needs Azure (allowlisted Mac IP) + Supabase.
Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/build_campaign_map.py
"""
import os, pandas as pd, psycopg2
DOM = 0.80  # dominance threshold

def azure():
    return psycopg2.connect(host=os.environ['AZURE_PG_HOST'], port=os.environ.get('AZURE_PG_PORT', '5432'),
        user=os.environ['AZURE_PG_USER'], password=os.environ['AZURE_PG_PASSWORD'],
        dbname=os.environ['AZURE_PG_DB'], sslmode='require', connect_timeout=30)
def supa():
    return psycopg2.connect(host=os.environ['PGHOST'], port=os.environ.get('PGPORT', '5432'),
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        dbname=os.environ.get('PGDATABASE', 'postgres'), sslmode='require', connect_timeout=30)

# 1. advertised-product spend per (campaign, asin)
az = azure(); ac = az.cursor()
ac.execute("""select campaign_id, advertised_asin, sum(spend) spend
  from ads_sponsored_products_advertised_product where spend is not null group by 1,2""")
ap = pd.DataFrame(ac.fetchall(), columns=['campaign_id', 'asin', 'spend']); az.close()
ap['campaign_id'] = ap['campaign_id'].astype('int64')
ap['spend'] = pd.to_numeric(ap['spend'], errors='coerce').fillna(0)

# 2. advertised ASIN -> family (CA catalog)
sp = supa(); sc = sp.cursor()
sc.execute("select asin, family from catalog where region='CA'")
cat = dict(sc.fetchall())
ap['family'] = ap['asin'].map(cat)

# 3. per-campaign dominant-family spend share
tot = ap.groupby('campaign_id')['spend'].sum()
famsp = ap.dropna(subset=['family']).groupby(['campaign_id', 'family'])['spend'].sum().reset_index()
top = famsp.loc[famsp.groupby('campaign_id')['spend'].idxmax()].set_index('campaign_id')
known = set(tot.index)

def decide(cid):
    if cid not in known or tot[cid] <= 0:
        return (None, None)              # no advertised-product data → leave as-is
    if cid in top.index:
        share = float(top.loc[cid, 'spend']) / float(tot[cid])
        return (top.loc[cid, 'family'], share) if share >= DOM else (None, share)
    return (None, 0.0)                    # spend exists but none maps to a catalog family

# 4. apply to Supabase campaign_map (SP rows)
sc.execute("select campaign_id from campaign_map where program='SP'")
sp_ids = [r[0] for r in sc.fetchall()]
mapped = unmapped = skipped = 0
for cid in sp_ids:
    fam, share = decide(cid)
    if share is None:                    # no data → don't touch
        skipped += 1; continue
    if fam:
        sc.execute("update campaign_map set auto_family=%s, status='mapped' where program='SP' and campaign_id=%s", (fam, cid)); mapped += 1
    else:
        sc.execute("update campaign_map set auto_family=NULL, status='unmapped' where program='SP' and campaign_id=%s", (cid,)); unmapped += 1
# retire any leftover auto 'Brand Level' from the old name-based pass → unmapped (Brand Level stays a MANUAL choice)
sc.execute("update campaign_map set auto_family=NULL, status='unmapped' where auto_family='Brand Level' and coalesce(manual_family,'')=''")
sp.commit()
print(f"SP dominance rule (>= {DOM:.0%} one family): {mapped} mapped, {unmapped} unmapped, {skipped} skipped (no ad-product data)")

# report the flagship brand campaign + spend now left unmapped
sc.execute("select campaign_name, auto_family, status, round(spend) from campaign_map where campaign_name ilike '%All Products - Lifepro%'")
print("brand example:", sc.fetchall())
sc.execute("select count(*), coalesce(round(sum(spend)),0) from campaign_map where program='SP' and status='unmapped' and coalesce(manual_family,'')=''")
print("SP unmapped now: {} campaigns, C${:,.0f} spend awaiting manual mapping".format(*sc.fetchone()))
sp.close()
