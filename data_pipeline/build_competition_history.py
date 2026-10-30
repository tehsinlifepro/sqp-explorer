#!/usr/bin/env python3
"""Competition Watch — subcategory BSR rank HISTORY (Serpstat-style multi-line trend).
For the top N brands in each subcategory, pull their representative ASIN's Keepa salesRanks history
for the subcategory's leaf catId, downsample to weekly over the last ~6 months, write competition_rank_history.
Keepa: product history=1 = 1 token/ASIN (cached). Dry-run default; --write to load.
Usage: python3 data_pipeline/build_competition_history.py [--write] [--brands N] [--weeks W] [--regions US,CA]
"""
import os, sys, datetime, collections, psycopg2
from psycopg2.extras import execute_values
import keepa_client as K
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRITE="--write" in sys.argv
TOPB=int(sys.argv[sys.argv.index("--brands")+1]) if "--brands" in sys.argv else 8
WEEKS=int(sys.argv[sys.argv.index("--weeks")+1]) if "--weeks" in sys.argv else 26
REGIONS=(sys.argv[sys.argv.index("--regions")+1].split(",") if "--regions" in sys.argv else ["US","CA"])
DOMAIN={"US":1,"CA":6}
SINCE=datetime.date.today()-datetime.timedelta(weeks=WEEKS)
def sb():
    e={}
    for line in open(os.path.join(ROOT,".secrets","supabase.env")):
        line=line.strip()
        if "=" in line and not line.startswith("#"):
            k,v=line.split("=",1); e[k.strip()]=v.strip().strip('"').strip("'")
    return psycopg2.connect(host="aws-0-us-east-1.pooler.supabase.com",port=5432,user="postgres.vhrzfsceziyqbrwwwhxv",password=e["PGPASSWORD"],dbname="postgres",sslmode="require",connect_timeout=60)
con=sb(); cur=con.cursor()
cur.execute("select region, asin, category from catalog where region=any(%s) and asin is not null",(REGIONS,))
cat_rows=cur.fetchall()
# leaf catId per (region,category) from cached our-ASIN products (history=0, cached — no spend)
leaf={}
for region in REGIONS:
    ours=[a for r,a,c in cat_rows if r==region]
    our_cat={a:c for r,a,c in cat_rows if r==region}
    prods,_=K.product(ours, domain=DOMAIN[region], history=0)
    vote=collections.defaultdict(collections.Counter)
    for p in prods:
        cid,_=K.leaf_category(p)
        if cid: vote[our_cat.get(p.get("asin"),"?")][cid]+=1
    for c,v in vote.items():
        if v: leaf[(region,c)]=v.most_common(1)[0][0]
# top brands per (region,category) + each brand's top ASIN
cur.execute("select region,category,brand,rnk from competition_brand where rnk<=%s and brand<>'Unknown'",(TOPB,))
topbrands=collections.defaultdict(list)
for r,c,b,rk in cur.fetchall(): topbrands[(r,c)].append(b)
cur.execute("select region,category,brand,asin,monthly_sold from competition_asin")
best={}  # (r,c,brand)->(asin,units)
for r,c,b,a,u in cur.fetchall():
    k=(r,c,b)
    if k not in best or (u or 0)>best[k][1]: best[k]=(a,u or 0)
out=[]
for region in REGIONS:
    for (r,c),brands in list(topbrands.items()):
        if r!=region: continue
        cid=leaf.get((region,c))
        if not cid: continue
        pairs=[(b,best.get((r,c,b),(None,0))[0]) for b in brands]
        asins=[a for _,a in pairs if a]
        prods,tl=K.product(asins, domain=DOMAIN[region], history=1)
        pmap={p.get("asin"):p for p in prods}
        for b,a in pairs:
            p=pmap.get(a)
            if not p: continue
            hist=K.rank_history(p, cid, since_date=SINCE)
            # downsample weekly: last bsr per ISO-Monday week
            wk={}
            for dt,bsr in hist:
                ws=dt-datetime.timedelta(days=dt.weekday())
                wk[ws]=bsr
            for ws in sorted(wk):
                out.append((region,c,b,a,ws,wk[ws]))
        print(f"  {region}/{c}: {len(asins)} brand-ASINs, cat {cid} | tokensLeft~{tl}")
print(f"\nTOTAL competition_rank_history rows: {len(out)}")
if WRITE and out:
    cur.execute("delete from competition_rank_history where region=any(%s)",(REGIONS,))
    execute_values(cur,"insert into competition_rank_history (region,category,brand,asin,date,bsr) values %s on conflict (region,category,asin,date) do update set bsr=excluded.bsr, brand=excluded.brand",out,page_size=1000)
    con.commit(); print(f"  -> wrote {len(out)} rows")
cur.close(); con.close()
print("DONE."+("" if WRITE else "  (dry-run)"))
