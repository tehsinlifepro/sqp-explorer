#!/usr/bin/env python3
"""Family-level tables for the Family Explorer (both regions, all queries):
  family_niche_month  (region × family × month) — niche size + our share, over time
  family_kw_composition (region × family × month × keyword) — top-8 keywords + 'Other' (stacked area)
  family_top_keywords (region × family × query) — top 30 keywords for the family
Run: python3 build_family_tables.py
"""
import pandas as pd, numpy as np, os
CA=os.path.expanduser("~/Downloads/SQP Analysis Canada")
OUT=os.path.expanduser("~/Downloads/sqp-explorer/data_export"); os.makedirs(OUT,exist_ok=True)
GRAIN=os.environ.get('GRAIN','month'); PKEY='month' if GRAIN=='month' else 'week'; MSUF='' if GRAIN=='month' else '_weekly'
MASTERS={"CA":os.path.join(CA,"4_Data",f"LifePro_CA_SQP{MSUF}_master.csv"),
         "US":os.path.join(CA,"USA SQP","4_Data",f"LifePro_US_SQP{MSUF}_master.csv")}
NUMC=['search_query_volume','total_query_impression_count','total_purchase_count',
      'asin_impression_count','asin_click_count','asin_purchase_count']

fnm_all=[]; comp_all=[]; ftk_all=[]
for region,path in MASTERS.items():
    df=pd.read_csv(path)
    for c in NUMC: df[c]=pd.to_numeric(df[c],errors='coerce')
    df['month']=(pd.to_datetime(df['start_date']).dt.to_period('M').astype(str) if GRAIN=='month'
                 else pd.to_datetime(df['start_date']).dt.to_period('W').apply(lambda p:p.start_time.date().isoformat()))
    df=df[df['search_query'].notna() & (df['search_query'].astype(str).str.strip()!='') & df['family'].notna()].copy()
    MONTHS=sorted(df['month'].unique()); f3,l3=set(MONTHS[:3]),set(MONTHS[-3:])

    # family × query × month (market metrics constant per query,month -> 'first'; our metrics summed)
    fqm=df.groupby(['family','search_query','month']).agg(
        volume=('search_query_volume','first'),
        market_impr=('total_query_impression_count','first'),
        market_pur=('total_purchase_count','first'),
        our_impr=('asin_impression_count','sum'),
        our_clk=('asin_click_count','sum'),
        our_pur=('asin_purchase_count','sum')).reset_index()

    # 1) family_niche_month
    fnm=fqm.groupby(['family','month']).agg(
        niche_volume=('volume','sum'), niche_market_impressions=('market_impr','sum'),
        niche_market_purchases=('market_pur','sum'), our_purchases=('our_pur','sum'),
        our_impressions=('our_impr','sum'), our_clicks=('our_clk','sum'),
        n_queries=('search_query','nunique')).reset_index()
    fnm['our_niche_purchase_share']=(fnm.our_purchases/fnm.niche_market_purchases.replace(0,np.nan)).round(4)
    fnm['our_niche_impr_share']=(fnm.our_impressions/fnm.niche_market_impressions.replace(0,np.nan)).round(4)
    fnm.insert(0,'region',region); fnm_all.append(fnm)

    # per (family,query) rollups for ranking + trend
    agg=fqm.groupby(['family','search_query']).agg(
        vol_12mo=('volume','sum'), our_pur_12mo=('our_pur','sum'), mkt_pur_12mo=('market_pur','sum')).reset_index()
    latest=fqm.sort_values('month').groupby(['family','search_query']).tail(1)[['family','search_query','volume']] \
        .rename(columns={'volume':'latest_volume'})
    v_f3=fqm[fqm.month.isin(f3)].groupby(['family','search_query']).volume.mean().rename('vf')
    v_l3=fqm[fqm.month.isin(l3)].groupby(['family','search_query']).volume.mean().rename('vl')
    agg=agg.merge(latest,on=['family','search_query']).merge(v_f3,on=['family','search_query'],how='left').merge(v_l3,on=['family','search_query'],how='left')
    def trend(r):
        if pd.notna(r.vl) and pd.isna(r.vf): return 'Emerging'
        if pd.notna(r.vf) and pd.isna(r.vl): return 'Fading'
        if pd.notna(r.vf) and pd.notna(r.vl) and r.vf>0:
            ch=(r.vl-r.vf)/r.vf; return 'Rising' if ch>=.25 else 'Declining' if ch<=-.25 else 'Stable'
        return 'Stable'
    agg['trend']=agg.apply(trend,axis=1)
    agg['our_purchase_share']=(agg.our_pur_12mo/agg.mkt_pur_12mo.replace(0,np.nan)).round(4)

    # 2) family_top_keywords — top 30 per family by our purchases then volume
    ftk=agg.sort_values(['family','our_pur_12mo','vol_12mo'],ascending=[True,False,False]).groupby('family').head(30)
    ftk=ftk[['family','search_query','latest_volume','our_pur_12mo','our_purchase_share','trend']].copy()
    ftk.columns=['family','search_query','latest_volume','our_purchases_12mo','our_purchase_share','trend']
    ftk.insert(0,'region',region); ftk_all.append(ftk)

    # 3) family_kw_composition — top 8 queries by 12mo volume per family + 'Other'
    top8=agg.sort_values(['family','vol_12mo'],ascending=[True,False]).groupby('family').head(8)[['family','search_query']]
    top8k=set(map(tuple,top8.values))
    fqm['is_top']=[ (f,q) in top8k for f,q in zip(fqm.family,fqm.search_query) ]
    comp_top=fqm[fqm.is_top][['family','month','search_query','volume']].rename(columns={'search_query':'keyword'})
    sum_top=comp_top.groupby(['family','month']).volume.sum().rename('t').reset_index()
    other=fnm[['family','month','niche_volume']].merge(sum_top,on=['family','month'],how='left')
    other['volume']=(other.niche_volume-other.t.fillna(0)).clip(lower=0); other['keyword']='Other'
    comp=pd.concat([comp_top,other[['family','month','keyword','volume']]],ignore_index=True)
    comp.insert(0,'region',region); comp_all.append(comp)

FNM=pd.concat(fnm_all,ignore_index=True)
for col in ['niche_volume','niche_market_impressions','niche_market_purchases','our_purchases','our_impressions','our_clicks','n_queries']:
    FNM[col]=FNM[col].fillna(0).round().astype(int)
COMP=pd.concat(comp_all,ignore_index=True); COMP['volume']=COMP['volume'].fillna(0).round().astype(int)
FTK=pd.concat(ftk_all,ignore_index=True)
for col in ['latest_volume','our_purchases_12mo']:
    FTK[col]=FTK[col].fillna(0).round().astype(int)
if GRAIN=='week':
    FNM=FNM.rename(columns={'month':'week'}); COMP=COMP.rename(columns={'month':'week'})
_ftksuf='' if GRAIN=='month' else '_week'
FNM.to_csv(os.path.join(OUT,f"family_niche_{PKEY}.csv"),index=False)
COMP.to_csv(os.path.join(OUT,f"family_kw_composition{_ftksuf}.csv"),index=False)
FTK.to_csv(os.path.join(OUT,f"family_top_keywords{_ftksuf}.csv"),index=False)
for n in [f"family_niche_{PKEY}",f"family_kw_composition{_ftksuf}",f"family_top_keywords{_ftksuf}"]:
    print(f"  {n:<22} rows={sum(1 for _ in open(os.path.join(OUT,n+'.csv')))-1:,}")
fnm=pd.concat(fnm_all)
r=fnm[(fnm.region=='US')&(fnm.family=='Waver')].sort_values('month')
print("\nSanity US Waver niche (first/last month):")
print(r[['month','niche_volume','our_purchases','our_niche_purchase_share']].iloc[[0,-1]].to_string(index=False))
