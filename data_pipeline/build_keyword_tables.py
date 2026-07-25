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
MASTERS={"CA":os.path.join(CA,"4_Data","LifePro_CA_SQP_master.csv"),
         "US":os.path.join(CA,"USA SQP","4_Data","LifePro_US_SQP_master.csv")}
NUM=['search_query_volume','total_query_impression_count','total_click_count','total_cart_add_count',
 'total_purchase_count','asin_impression_count','asin_click_count','asin_cart_add_count','asin_purchase_count',
 'total_median_purchase_price_amount','asin_impression_share','asin_click_share','asin_purchase_share']

qsum=[]; qmon=[]; qam=[]
for region,path in MASTERS.items():
    df=pd.read_csv(path)
    for c in NUM:
        if c in df.columns: df[c]=pd.to_numeric(df[c],errors='coerce')
    df['month']=pd.to_datetime(df['start_date']).dt.to_period('M').astype(str)
    df=df[df['search_query'].notna() & (df['search_query'].astype(str).str.strip()!='')].copy()  # drop blank queries
    MONTHS=sorted(df['month'].unique()); f3,l3=set(MONTHS[:3]),set(MONTHS[-3:])

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

    # top category per query (by our purchases, fallback impressions)
    cat=(df.groupby(['search_query','category']).agg(p=('asin_purchase_count','sum'),
        i=('asin_impression_count','sum')).reset_index()
        .sort_values(['search_query','p','i'],ascending=[True,False,False])
        .drop_duplicates('search_query').set_index('search_query')['category'])

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
        if pl and not pf: trend='Emerging'
        elif pf and not pl: trend='Fading'
        elif pd.notna(volf) and pd.notna(voll) and volf>0:
            ch=(voll-volf)/volf; trend='Rising' if ch>=0.25 else 'Declining' if ch<=-0.25 else 'Stable'
        else: trend='Stable'
        rows.append(dict(region=region,search_query=q,top_category=cat.get(q,'—'),
            latest_volume=int(latest.search_query_volume),
            avg_volume=int(round(qd.search_query_volume.mean())),
            our_purchases_12mo=int(qd.our_purchases.sum()),
            our_purchase_share=round(our_l3/mkt_l3,4) if mkt_l3 else None,
            growth=round((voll-volf)/volf,4) if (pd.notna(volf) and pd.notna(voll) and volf>0) else None,
            months_present=int(qd.month.nunique()),trend=trend))
    qsum.append(pd.DataFrame(rows))

pd.concat(qsum,ignore_index=True).to_csv(os.path.join(OUT,"query_summary.csv"),index=False)
pd.concat(qmon,ignore_index=True).to_csv(os.path.join(OUT,"query_month.csv"),index=False)
pd.concat(qam,ignore_index=True).to_csv(os.path.join(OUT,"query_asin_month.csv"),index=False)
for n in ["query_summary","query_month","query_asin_month"]:
    print(f"  {n:<18} rows={sum(1 for _ in open(os.path.join(OUT,n+'.csv')))-1:,}")
# sanity
qs=pd.concat(qsum)
r=qs[(qs.region=='US')&(qs.search_query=='vibration plate')]
if len(r): print("\nSanity US 'vibration plate':",r[['latest_volume','our_purchase_share','trend']].to_dict('records'))
