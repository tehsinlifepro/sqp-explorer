#!/usr/bin/env python3
"""Keyword-level Supabase tables from the raw SQP masters (ALL queries, both regions):
  query_summary     (region × query)        — searchable/rankable list + trend + our share
  query_month       (region × query × month)— 12-mo trend for a selected query
  query_asin_month  (region × query × asin × month) — which of our ASINs win the query
Run: python3 build_keyword_tables.py
"""
import pandas as pd, numpy as np, os
CA=os.path.expanduser("~/Downloads/SQP Analysis Canada")
OUT=os.path.expanduser("~/Downloads/sqp-explorer/data_export"); os.makedirs(OUT,exist_ok=True)
import sys, re
sys.path.insert(0, os.path.join(CA,"5_Pipeline")); from sqp_config import REGEX
CRX={c:re.compile(rx,re.I) for c,rx in REGEX.items() if c!='Other'}  # intent filters for on-category validation
GRAIN=os.environ.get('GRAIN','month'); PKEY='month' if GRAIN=='month' else 'week'; MSUF='' if GRAIN=='month' else '_weekly'
MASTERS={"CA":os.path.join(CA,"4_Data",f"LifePro_CA_SQP{MSUF}_master.csv"),
         "US":os.path.join(CA,"USA SQP","4_Data",f"LifePro_US_SQP{MSUF}_master.csv")}
NUM=['search_query_volume','total_query_impression_count','total_click_count','total_cart_add_count',
 'total_purchase_count','asin_impression_count','asin_click_count','asin_cart_add_count','asin_purchase_count',
 'total_median_purchase_price_amount','asin_impression_share','asin_click_share','asin_purchase_share']

qsum=[]; qmon=[]; qam=[]
for region,path in MASTERS.items():
    df=pd.read_csv(path)
    for c in NUM:
        if c in df.columns: df[c]=pd.to_numeric(df[c],errors='coerce')
    df['month']=(pd.to_datetime(df['start_date']).dt.to_period('M').astype(str) if GRAIN=='month'
                 else pd.to_datetime(df['start_date']).dt.to_period('W').apply(lambda p:p.start_time.date().isoformat()))
    df=df[df['search_query'].notna() & (df['search_query'].astype(str).str.strip()!='')].copy()  # drop blank queries
    MONTHS=sorted(df['month'].unique())
    _w=max(1,min(3,len(MONTHS)//2)); f3,l3=set(MONTHS[:_w]),set(MONTHS[-_w:])  # non-overlapping windows (works at 4mo)

    # query_asin_month (drill: which ASIN wins the query)
    a=df[['search_query','asin','category','family','month','search_query_volume',
          'asin_impression_count','asin_click_count','asin_cart_add_count','asin_purchase_count',
          'asin_impression_share','asin_click_share','asin_purchase_share']].copy()
    a.insert(0,'region',region)
    a.columns=['region','search_query','asin','category','family','month','search_query_volume',
        'asin_impressions','asin_clicks','asin_cart_adds','asin_purchases',
        'asin_impr_share','asin_click_share','asin_purchase_share']
    qam.append(a)

    # market per (query,month) — dedup; our per (query,month) — sum across our ASINs
    mkt=df.drop_duplicates(['search_query','month'])[['search_query','month','search_query_volume',
        'total_query_impression_count','total_click_count','total_cart_add_count','total_purchase_count',
        'total_median_purchase_price_amount']]
    our=df.groupby(['search_query','month']).agg(our_impressions=('asin_impression_count','sum'),
        our_clicks=('asin_click_count','sum'),our_cart_adds=('asin_cart_add_count','sum'),
        our_purchases=('asin_purchase_count','sum')).reset_index()
    qm=mkt.merge(our,on=['search_query','month'])
    qm.rename(columns={'total_query_impression_count':'market_impressions','total_click_count':'market_clicks',
        'total_cart_add_count':'market_cart_adds','total_purchase_count':'market_purchases',
        'total_median_purchase_price_amount':'market_median_price'},inplace=True)
    qm['our_impr_share']=(qm.our_impressions/qm.market_impressions.replace(0,np.nan)).round(4)
    qm['our_click_share']=(qm.our_clicks/qm.market_clicks.replace(0,np.nan)).round(4)
    qm['our_purchase_share']=(qm.our_purchases/qm.market_purchases.replace(0,np.nan)).round(4)
    qm.insert(0,'region',region)
    qmon.append(qm)

    # top category per query: rank our-present categories by our purchases, then keep the first
    # whose intent regex the query actually matches; else any category regex; else 'Other'.
    # (Stops broad terms like "vibrator"/"fitness equipment" from being bucketed into a category.)
    _catg=(df.groupby(['search_query','category']).agg(p=('asin_purchase_count','sum'),
        i=('asin_impression_count','sum')).reset_index()
        .sort_values(['search_query','p','i'],ascending=[True,False,False]))
    _cand=_catg.groupby('search_query')['category'].apply(list)
    def assign_cat(q):
        s=str(q)
        for c in _cand.get(q,[]):
            rx=CRX.get(c)
            if rx and rx.search(s): return c
        for c,rx in CRX.items():
            if rx.search(s): return c
        return 'Other'

    # query_summary per query
    g=qm.groupby('search_query')
    rows=[]
    for q,qd in g:
        qd=qd.sort_values('month')
        volf=qd[qd.month.isin(f3)].search_query_volume.mean()
        voll=qd[qd.month.isin(l3)].search_query_volume.mean()
        pf=qd.month.isin(f3).any(); pl=qd.month.isin(l3).any()
        latest=qd.iloc[-1]
        our_l3=qd[qd.month.isin(l3)].our_purchases.sum()
        mkt_l3=qd[qd.month.isin(l3)].market_purchases.sum()
        VF=50  # volume floor: only flag Emerging/Fading for keywords with real demand (not long-tail churn)
        if pl and not pf: trend='Emerging' if (voll or 0)>=VF else 'Stable'
        elif pf and not pl: trend='Fading' if (volf or 0)>=VF else 'Stable'
        elif pd.notna(volf) and pd.notna(voll) and volf>0:
            ch=(voll-volf)/volf; trend='Rising' if ch>=0.25 else 'Declining' if ch<=-0.25 else 'Stable'
        else: trend='Stable'
        rows.append(dict(region=region,search_query=q,top_category=assign_cat(q),
            latest_volume=int(latest.search_query_volume),
            avg_volume=int(round(qd.search_query_volume.mean())),
            our_purchases_12mo=int(qd.our_purchases.sum()),
            our_purchase_share=round(our_l3/mkt_l3,4) if mkt_l3 else None,
            growth=round((voll-volf)/volf,4) if (pd.notna(volf) and pd.notna(voll) and volf>0) else None,
            months_present=int(qd.month.nunique()),trend=trend))
    qsum.append(pd.DataFrame(rows))

def _out(frames, table):
    d=pd.concat(frames,ignore_index=True)
    if GRAIN=='week' and 'month' in d.columns: d=d.rename(columns={'month':'week'})
    d.to_csv(os.path.join(OUT,f"{table}.csv"),index=False); return d
_out(qsum, "query_summary"+('' if GRAIN=='month' else '_week'))
_out(qmon, f"query_{PKEY}")
_out(qam, f"query_asin_{PKEY}")
for n in ([f"query_{PKEY}",f"query_asin_{PKEY}","query_summary"+('' if GRAIN=='month' else '_week')]):
    print(f"  {n:<18} rows={sum(1 for _ in open(os.path.join(OUT,n+'.csv')))-1:,}")
# sanity
qs=pd.concat(qsum)
r=qs[(qs.region=='US')&(qs.search_query=='vibration plate')]
if len(r): print("\nSanity US 'vibration plate':",r[['latest_volume','our_purchase_share','trend']].to_dict('records'))
