#!/usr/bin/env python3
"""Build US campaign_map (campaign -> family) with INFERENCE, for all brands (D-005).

Family assignment cascade per campaign:
  1. ASIN-dominance: >=80% of campaign ad-spend on advertised ASINs of one catalog family (CA/CA parity rule).
  2. ASIN-in-name: an ASIN parsed from the campaign name maps to a catalog family.
  3. Family-token: a catalog family (or model) name appears in the campaign name.
  4. Brand fallback: non-LifePro account (Petcove/Joyberri/Oaktiv/Culvani/Loft & Ivy) -> family = brand name.
  5. else unmapped.
Preserves manual_family. Upserts on campaign_map PK (program, campaign_id). Dry-run default; --write to load.
"""
import os, sys, re, collections, psycopg2
from psycopg2.extras import execute_values
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRITE = "--write" in sys.argv
ASINRE = re.compile(r'B0[A-Z0-9]{8}')

def env(fn):
    d={}
    for line in open(os.path.join(ROOT,".secrets",fn)):
        line=line.strip()
        if "=" in line and not line.startswith("#"):
            k,v=line.split("=",1); d[k.strip()]=v.strip().strip('"').strip("'")
    return d
e=env("supabase.env"); ue=env("usa-reason.env")
sb=psycopg2.connect(host="aws-0-us-east-1.pooler.supabase.com",port=5432,user="postgres.vhrzfsceziyqbrwwwhxv",password=e["PGPASSWORD"],dbname="postgres",sslmode="require",connect_timeout=60)
cur=sb.cursor()
cur.execute("select asin, family, model from catalog where region='US' and asin is not null")
fam={}; models=[]
for a,f,m in cur.fetchall():
    if f: fam[a]=f
    if m and len(m)>=4: models.append((m, f))
FAMS = sorted({f for f in fam.values()}, key=len, reverse=True)   # longest first
FAMS = [f for f in FAMS if len(f) >= 4]
cur.execute("select campaign_id, advertised_asin, sum(spend), sum(sales) from ad_asin_month where region='US' group by campaign_id, advertised_asin")
rows=cur.fetchall()
# campaign -> name + account (all brands now)
us=psycopg2.connect(host=ue["USA_REASON_PGHOST"],port=5432,dbname=ue["USA_REASON_PGDATABASE"],user=ue["USA_REASON_PGUSER"],password=ue["USA_REASON_PGPASSWORD"],sslmode="require",connect_timeout=60)
uc=us.cursor()
uc.execute("""select campaign_id::bigint, max(campaign_name), max(ads_account_name)
  from public.ads_sponsored_products_advertised_product where campaign_id ~ '^[0-9]+$' group by campaign_id::bigint""")
cmeta={cid:(nm or '', acc or '') for cid,nm,acc in uc.fetchall()}
uc.close(); us.close()

camp_spend=collections.defaultdict(float); camp_sales=collections.defaultdict(float)
camp_fs=collections.defaultdict(lambda: collections.defaultdict(float)); camp_asins=collections.defaultdict(set)
for cid, asin, spend, sales in rows:
    camp_spend[cid]+=float(spend or 0); camp_sales[cid]+=float(sales or 0); camp_asins[cid].add(asin)
    f=fam.get(asin)
    if f: camp_fs[cid][f]+=float(spend or 0)

def fam_from_name(nm):
    for a in ASINRE.findall(nm or ''):
        if a in fam: return fam[a]            # ASIN-in-name
    low=(nm or '').lower()
    for f in FAMS:                            # family-token
        if f.lower() in low: return f
    for m,f in models:                        # model-token
        if m.lower() in low and f: return f
    return None

cur.execute("select campaign_id, manual_family from campaign_map where region='US' and coalesce(manual_family,'')<>''")
manual=dict(cur.fetchall())
out=[]; how=collections.Counter()
for cid in camp_spend:
    nm, acc = cmeta.get(cid, ('',''))
    tot=camp_spend[cid] or 1
    bf,br=None,0
    for f,sp in camp_fs[cid].items():
        if sp/tot>br: bf,br=f,sp/tot
    if bf and br>=0.8: auto=bf; how['asin_dominance']+=1
    else:
        inf=fam_from_name(nm)
        if inf: auto=inf; how['name_inference']+=1
        elif acc and acc!='LifePro Fitness': auto=acc; how['brand_fallback']+=1
        else: auto=None; how['unmapped']+=1
    status='auto' if auto else 'unmapped'
    out.append(('US','SP',cid,nm,'',auto,'advertised_product',status,round(camp_spend[cid],2),round(camp_sales[cid],2),len(camp_asins[cid]),manual.get(cid)))
mapped=sum(1 for r in out if r[5])
print(f"US campaigns: {len(out)} | mapped: {mapped} ({mapped*100//max(len(out),1)}%) | breakdown: {dict(how)}")
if WRITE and out:
    execute_values(cur, """insert into campaign_map
      (region,program,campaign_id,campaign_name,asin,auto_family,source,status,spend,sales,terms,manual_family)
      values %s on conflict (program,campaign_id) do update set campaign_name=excluded.campaign_name,
      auto_family=excluded.auto_family, source=excluded.source, status=excluded.status,
      spend=excluded.spend, sales=excluded.sales, terms=excluded.terms""", out, page_size=1000)
    sb.commit(); print(f"  -> wrote {len(out)} US campaign_map rows")
cur.close(); sb.close()
print("DONE."+("" if WRITE else "  (dry-run)"))
