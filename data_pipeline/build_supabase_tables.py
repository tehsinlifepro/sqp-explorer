#!/usr/bin/env python3
"""Build Supabase-ready tables from the local SQP masters (both regions), using the same
core-niche logic as the QC'd category reports. Outputs CSVs for import into Supabase/Postgres:
  catalog, category_month, family_summary, asin_month
Run: python3 build_supabase_tables.py
"""
import pandas as pd, numpy as np, os, sys
CA=os.path.expanduser("~/Downloads/SQP Analysis Canada")
sys.path.insert(0, os.path.join(CA,"5_Pipeline")); from sqp_config import REGEX
OUT=os.path.expanduser("~/Downloads/sqp-explorer/data_export"); os.makedirs(OUT,exist_ok=True)

MASTERS={"CA":os.path.join(CA,"4_Data","LifePro_CA_SQP_master.csv"),
         "US":os.path.join(CA,"USA SQP","4_Data","LifePro_US_SQP_master.csv")}
NUM=['search_query_volume','total_query_impression_count','total_click_count','total_cart_add_count',
 'total_purchase_count','asin_impression_count','asin_click_count','asin_cart_add_count','asin_purchase_count',
 'total_median_purchase_price_amount','asin_median_purchase_price_amount']
def wavg(v,w):
    v=pd.to_numeric(v,errors='coerce');w=pd.to_numeric(w,errors='coerce').fillna(0)
    m=v.notna()&(w>0); return round(float(np.average(v[m],weights=w[m])),2) if m.any() else None

catalog=[]; cat_month=[]; fam_sum=[]; asin_month=[]
for region,path in MASTERS.items():
    df=pd.read_csv(path)
    for c in NUM: df[c]=pd.to_numeric(df[c],errors='coerce')
    df['month']=pd.to_datetime(df['start_date']).dt.to_period('M').astype(str)
    MONTHS=sorted(df['month'].unique())
    # catalog
    meta_cols=[c for c in ['brand','model','sku','family','category','ppc_listing','product_manager'] if c in df.columns]
    cat=df.drop_duplicates('asin')[['asin']+meta_cols].copy(); cat['region']=region
    catalog.append(cat)
    for category in sorted(df['category'].dropna().unique()):
        rx=REGEX.get(category); d=df[df.category==category]
        dcc=d[d.search_query.str.contains(rx,case=False,na=False,regex=True)] if rx else d
        mkt=dcc[['search_query','month','search_query_volume','total_query_impression_count','total_click_count',
                 'total_cart_add_count','total_purchase_count','total_median_purchase_price_amount']].drop_duplicates(['search_query','month'])
        # category_month
        for m in MONTHS:
            b=mkt[mkt.month==m]; fam=dcc[dcc.month==m]
            if b.empty and fam.empty: continue
            mi=b.total_query_impression_count.sum();mc=b.total_click_count.sum();mca=b.total_cart_add_count.sum();mp=b.total_purchase_count.sum()
            fi=fam.asin_impression_count.sum();fc=fam.asin_click_count.sum();fca=fam.asin_cart_add_count.sum();fp=fam.asin_purchase_count.sum()
            op=wavg(fam.asin_median_purchase_price_amount,fam.asin_purchase_count); npx=wavg(b.total_median_purchase_price_amount,b.total_purchase_count)
            cat_month.append(dict(region=region,category=category,month=m,core_queries=int(b.search_query.nunique()),
                market_search_volume=int(b.search_query_volume.sum()),market_impressions=int(mi),market_clicks=int(mc),
                market_cart_adds=int(mca),market_purchases=int(mp),market_cvr=round(mp/mc,4) if mc else None,
                our_impressions=int(fi),our_clicks=int(fc),our_cart_adds=int(fca),our_purchases=int(fp),
                our_impr_share=round(fi/mi,4) if mi else None,our_click_share=round(fc/mc,4) if mc else None,
                our_atc_share=round(fca/mca,4) if mca else None,our_purchase_share=round(fp/mp,4) if mp else None,
                our_cvr=round(fp/fc,4) if fc else None,niche_median_price=npx,our_median_price=op,
                price_vs_niche=round(op/npx-1,4) if (op and npx) else None))
        # family_summary
        for f in sorted(dcc.family.dropna().unique()):
            p=dcc[dcc.family==f]
            tot=int(p.asin_purchase_count.sum());clk=int(p.asin_click_count.sum());imp=int(p.asin_impression_count.sum())
            qs=p.groupby('month')['search_query'].apply(set)
            mktp=sum(mkt[(mkt.month==mm)&(mkt.search_query.isin(qs.get(mm,set())))].total_purchase_count.sum() for mm in MONTHS)
            fmly=[]
            for m in MONTHS:
                pm=p[p.month==m]; fmly.append(int(pm.asin_purchase_count.sum()))
            f3=np.mean(fmly[:3]);l3=np.mean(fmly[-3:]);g=(l3-f3)/f3 if f3>0 else None
            traj="growing" if (g is not None and g>0.15) else "declining" if (g is not None and g<-0.15) else "flat"
            fam_sum.append(dict(region=region,category=category,family=f,asins=int(p.asin.nunique()),
                impressions=imp,clicks=clk,purchases_12mo=tot,blended_cvr=round(tot/clk,4) if clk else None,
                mkt_share_in_its_queries=round(tot/mktp,4) if mktp else None,growth=round(g,4) if g is not None else None,trajectory=traj))
        # asin_month (core counts + all-query purchases)
        for a in dcc.asin.unique():
            pa=dcc[dcc.asin==a]; paa=d[d.asin==a]; fam_name=pa.family.iloc[0] if len(pa) else None
            for m in MONTHS:
                pm=pa[pa.month==m]; pmall=paa[paa.month==m]
                if pm.empty and pmall.empty: continue
                asin_month.append(dict(region=region,asin=a,category=category,family=fam_name,month=m,
                    impressions=int(pm.asin_impression_count.sum()),clicks=int(pm.asin_click_count.sum()),
                    cart_adds=int(pm.asin_cart_add_count.sum()),purchases=int(pm.asin_purchase_count.sum()),
                    purchases_all_query=int(pmall.asin_purchase_count.sum())))

pd.concat(catalog,ignore_index=True).to_csv(os.path.join(OUT,"catalog.csv"),index=False)
pd.DataFrame(cat_month).to_csv(os.path.join(OUT,"category_month.csv"),index=False)
pd.DataFrame(fam_sum).to_csv(os.path.join(OUT,"family_summary.csv"),index=False)
pd.DataFrame(asin_month).to_csv(os.path.join(OUT,"asin_month.csv"),index=False)
print("Wrote CSVs to", OUT)
for n,df_ in [("catalog",pd.concat(catalog)),("category_month",pd.DataFrame(cat_month)),
              ("family_summary",pd.DataFrame(fam_sum)),("asin_month",pd.DataFrame(asin_month))]:
    print(f"  {n:<16} rows={len(df_):,}")
# sanity check vs known QC'd values
am=pd.DataFrame(asin_month)
chk=am[(am.region=='US')&(am.asin=='B07P5GV3VX')&(am.month=='2026-06')]
print("\nSanity: US B07P5GV3VX 2026-06 core purchases =", int(chk.purchases.iloc[0]), "(expected 2779)")
cm=pd.DataFrame(cat_month)
chk2=cm[(cm.region=='CA')&(cm.category=='Vibration Plate')&(cm.month=='2026-06')]
print("Sanity: CA Vibration Plate 2026-06 our_purchases =", int(chk2.our_purchases.iloc[0]), "(expected 428)")
