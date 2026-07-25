#!/usr/bin/env python3
"""On-demand assist: suggest a family for currently-UNMAPPED campaigns (writes manual_family).

Resolution order per campaign (all overridable in the Campaign Map tab; never overwrites an existing
manual_family):
  1. advertised-product spend, single family >= 65% (region-agnostic ASIN->family)   -> that family
  2. campaign-name family token (LP-<Family>_...  or  "<Product> - <ASIN>") matched to a
     canonical family                                                                  -> that family
  3. brand / umbrella by name ([brand], all products, ...)                             -> 'Brand Level'
  4. otherwise                                                                          -> leave unmapped
Set env DRY_RUN=1 to only print proposals without writing. Needs Azure + Supabase.
Run: set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/suggest_campaign_families.py
"""
import os, re, pandas as pd, psycopg2
LEAD = 0.65
DRY = os.environ.get('DRY_RUN') == '1'
BRAND_RE = re.compile(r'\[brand\]|all products?|all vibration|portfolio|catalog|brand awareness|brand defen', re.I)

def azure():
    return psycopg2.connect(host=os.environ['AZURE_PG_HOST'], port=os.environ.get('AZURE_PG_PORT', '5432'),
        user=os.environ['AZURE_PG_USER'], password=os.environ['AZURE_PG_PASSWORD'],
        dbname=os.environ['AZURE_PG_DB'], sslmode='require', connect_timeout=40)
def supa():
    return psycopg2.connect(host=os.environ['PGHOST'], port=os.environ.get('PGPORT', '5432'),
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        dbname=os.environ.get('PGDATABASE', 'postgres'), sslmode='require', connect_timeout=40)

sp = supa(); sc = sp.cursor()
sc.execute("""select program, campaign_id, campaign_name, round(spend) spend from campaign_map
  where coalesce(nullif(manual_family,''), auto_family) is null order by spend desc nulls last""")
unmapped = sc.fetchall()
sc.execute("select distinct family from catalog"); FAMS = [r[0] for r in sc.fetchall()]
sc.execute("select asin, family from catalog")              # region-agnostic asin -> family
CAT = {}
for a, f in sc.fetchall(): CAT.setdefault(a, f)

norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())
FAM_NORM = {norm(f): f for f in FAMS}
def match_token(name):
    m = re.match(r'\s*LP-([A-Za-z0-9]+)_', name or '') or re.match(r'\s*(?:\[[^\]]+\]\s*)?([A-Za-z0-9 ]+?)\s*-\s*B0', name or '')
    if not m: return None
    n = norm(m.group(1))
    if len(n) < 4: return None
    if n in FAM_NORM: return FAM_NORM[n]
    cands = [f for k, f in FAM_NORM.items() if len(k) >= 4 and (n.startswith(k) or k.startswith(n) or k in n)]
    return max(cands, key=len) if cands else None

# advertised-product spend split by family (region-agnostic)
ids = tuple(str(c[1]) for c in unmapped) or ('0',)
az = azure(); ac = az.cursor()
ac.execute("""select campaign_id, advertised_asin, sum(spend) spend
  from ads_sponsored_products_advertised_product where spend is not null and campaign_id in %s group by 1,2""", (ids,))
ap = pd.DataFrame(ac.fetchall(), columns=['campaign_id', 'asin', 'spend']); az.close()
ap['campaign_id'] = ap['campaign_id'].astype(str); ap['spend'] = pd.to_numeric(ap['spend'], errors='coerce').fillna(0)
ap['family'] = ap['asin'].map(CAT)
def dom(cid):
    d = ap[ap.campaign_id == cid]; tot = d.spend.sum()
    if tot <= 0: return None, 0
    fam = d.dropna(subset=['family']).groupby('family').spend.sum().sort_values(ascending=False)
    if fam.empty: return None, 0
    return fam.index[0], fam.iloc[0] / tot

by_spend, by_name, by_brand, left = [], [], [], []
for prog, cid, name, spend in unmapped:
    spend = float(spend or 0); cid = str(cid)
    top, ts = dom(cid)
    if top and ts >= LEAD:
        by_spend.append((prog, cid, name, spend, top, f"spend {ts:.0%}"))
    elif (tok := match_token(name)):
        by_name.append((prog, cid, name, spend, tok, "name"))
    elif BRAND_RE.search(name or ''):
        by_brand.append((prog, cid, name, spend, 'Brand Level', "brand-name"))
    else:
        left.append((prog, cid, name, spend, None, "spread/unknown"))

def apply(rows):
    for prog, cid, name, spend, fam, how in rows:
        if not DRY:
            sc.execute("update campaign_map set manual_family=%s where program=%s and campaign_id=%s", (fam, prog, cid))
apply(by_spend); apply(by_name); apply(by_brand)
if not DRY: sp.commit()

M = lambda x: f"C${x:,.0f}"
def show(title, rows):
    print(f"\n=== {title}  [{len(rows)}, {M(sum(r[3] for r in rows))}] ===")
    for prog, cid, name, spend, fam, how in rows:
        print(f"  {M(spend):>9}  {prog}  → {str(fam):<16} ({how})  {name[:52]}")
print("DRY RUN — nothing written.\n" if DRY else "APPLIED to manual_family (overridable in-app).\n")
show("by advertised spend (>=65%)", by_spend)
show("by campaign name → canonical family", by_name)
show("→ Brand Level", by_brand)
show("LEFT for you", left)
print(f"\nResolved: {M(sum(r[3] for g in (by_spend, by_name, by_brand) for r in g))} · left: {M(sum(r[3] for r in left))}")
sp.close()
