#!/usr/bin/env python3
"""Incremental Ranks refresh — Datarova (rolling 30d) → durable accumulator → app tables.

WHY THIS EXISTS
  The Datarova "Ranks" sheet only exposes the LAST ~30 DAYS. If we truncate+reload the app
  tables from each pull, everything older than 30 days is lost forever. So instead:
    1. UPSERT the pulled window into rank_daily  — the PERMANENT record (only ever grows).
    2. RE-DERIVE rank_family_day + rank_family_keyword from the FULL accumulator every run.
  Run it as often as you like (daily is ideal); as long as the gap between runs is < 30 days,
  no day is ever missed. Idempotent: re-running on the same CSV changes nothing.

USAGE
  # 1) refresh the CSV from the sheet first (Drive connector -> split_tabs.py), then:
  python3 refresh_ranks.py [path/to/Ranks.csv]
  Default CSV: ~/Downloads/Datarova - Ranks & Keywords/Ranks.csv

ENV (loaded from ../.secrets/supabase.env):
  PGHOST PGPORT PGUSER PGPASSWORD [PGDATABASE=postgres]
"""
import os, sys, pandas as pd, numpy as np, psycopg2
from psycopg2.extras import execute_values

CSV = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1
                         else "~/Downloads/Datarova - Ranks & Keywords/Ranks.csv")
MKT = {"US": "US", "CA": "CA"}          # marketplaces the app covers (accumulator keeps ALL)

def conn():
    return psycopg2.connect(
        host=os.environ["PGHOST"], port=os.environ.get("PGPORT", "5432"),
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"), sslmode="require", connect_timeout=25)

# ── 1. load + normalise the rolling window ────────────────────────────────────
R = pd.read_csv(CSV)
R.columns = [c.strip() for c in R.columns]
R = R.rename(columns={"Marketplace": "marketplace", "Project": "project", "Keyword": "keyword",
                      "Date": "date", "Ranked ASIN": "ranked_asin", "Organic Rank": "organic_rank",
                      "Sponsored Rank": "sponsored_rank", "Amazon Choice Badge": "ac_badge"})
R["ranked_asin"] = R["ranked_asin"].fillna("").astype(str).str.strip()
R["ac_badge"] = R["ac_badge"].astype(str).str.strip().str.lower().eq("yes")
R["keyword"] = R["keyword"].astype(str).str.strip()
R["project"] = R["project"].astype(str).str.strip()
R["marketplace"] = R["marketplace"].astype(str).str.strip()
R["date"] = pd.to_datetime(R["date"]).dt.strftime("%Y-%m-%d")
for c in ("organic_rank", "sponsored_rank"):
    R[c] = pd.to_numeric(R[c], errors="coerce")
KEY = ["marketplace", "project", "keyword", "date", "ranked_asin"]
R = R.drop_duplicates(KEY)
print(f"loaded {len(R):,} rows from {CSV}  ({R.date.min()} … {R.date.max()})")

rows = [(t.marketplace, t.project, t.keyword, t.date, t.ranked_asin,
         None if pd.isna(t.organic_rank) else float(t.organic_rank),
         None if pd.isna(t.sponsored_rank) else float(t.sponsored_rank),
         bool(t.ac_badge)) for t in R.itertuples(index=False)]

c = conn(); cur = c.cursor()
cur.execute("""create table if not exists rank_daily(
  marketplace text, project text, keyword text, date date, ranked_asin text default '',
  organic_rank real, sponsored_rank real, ac_badge boolean,
  primary key(marketplace,project,keyword,date,ranked_asin));""")
c.commit()
cur.execute("select count(*) from rank_daily"); before = cur.fetchone()[0]

# ── 2. UPSERT into the durable accumulator (never truncate) ───────────────────
execute_values(cur, """insert into rank_daily
  (marketplace,project,keyword,date,ranked_asin,organic_rank,sponsored_rank,ac_badge) values %s
  on conflict (marketplace,project,keyword,date,ranked_asin) do update set
    organic_rank=excluded.organic_rank, sponsored_rank=excluded.sponsored_rank,
    ac_badge=excluded.ac_badge""", rows, page_size=5000)
c.commit()
cur.execute("select count(*), min(date), max(date) from rank_daily")
after, dmin, dmax = cur.fetchone()
print(f"rank_daily accumulator: {before:,} → {after:,} rows (+{after-before:,})   history {dmin} … {dmax}")

# ── 3. RE-DERIVE app tables from the FULL accumulator ─────────────────────────
cur.execute("""select marketplace,project,keyword,date::text,ranked_asin,organic_rank,ac_badge
               from rank_daily""")
D = pd.DataFrame(cur.fetchall(), columns=["marketplace", "project", "keyword", "date",
                                          "ranked_asin", "organic_rank", "ac_badge"])
cur.execute("select region,asin,family from catalog")
cat = pd.DataFrame(cur.fetchall(), columns=["region", "asin", "family"])

D["region"] = D["marketplace"].map(MKT)
D = D[D.region.notna()].copy()
# project → family: majority-vote family across the project's catalog-matched ASINs
mm = D.merge(cat, left_on=["region", "ranked_asin"], right_on=["region", "asin"], how="inner")
p2f = (mm.groupby(["region", "project"])["family"]
         .agg(lambda s: s.mode().iloc[0]).reset_index())
D = D.merge(p2f, on=["region", "project"], how="left")
D = D[D.family.notna()].copy()                       # keep only families we can name
D["ranked"] = D.organic_rank.notna()
print(f"derivation universe: {len(D):,} rows across "
      f"{D.groupby('region').family.nunique().to_dict()} families")

# 3a. rank_family_day ---------------------------------------------------------
def day_agg(g):
    r = g[g.ranked]
    return pd.Series({
        "kw_tracked": g.keyword.nunique(),
        "kw_ranked": r.keyword.nunique(),
        "kw_top10": r[r.organic_rank <= 10].keyword.nunique(),
        "kw_top50": r[r.organic_rank <= 50].keyword.nunique(),
        "median_rank": round(float(r.organic_rank.median()), 1) if len(r) else None})
rfd = D.groupby(["region", "family", "date"]).apply(day_agg).reset_index()

# 3b. rank_family_keyword (over full history) ---------------------------------
def kw_agg(g):
    r = g[g.ranked].sort_values("date")
    days_tracked = g.date.nunique()
    days_ranked = r.date.nunique()
    ac = bool(g.ac_badge.any())
    if days_ranked == 0:
        return pd.Series({"latest_rank": None, "best_rank": None, "avg_rank": None,
                          "days_tracked": days_tracked, "days_ranked": 0,
                          "ac_badge": ac, "trend": "Unranked"})
    latest = float(r.iloc[-1].organic_rank)
    best = float(r.organic_rank.min())
    avg = round(float(r.organic_rank.mean()), 1)
    # trend: compare avg rank of earlier vs later half of the days we ranked
    dts = sorted(r.date.unique()); half = len(dts) // 2
    early = r[r.date.isin(dts[:half])].organic_rank.mean() if half else np.nan
    late = r[r.date.isin(dts[half:])].organic_rank.mean()
    span_days = (pd.to_datetime(g.date).max() - pd.to_datetime(g.date).min()).days
    seen_early = pd.to_datetime(r.date).min() <= pd.to_datetime(g.date).min() + pd.Timedelta(days=max(1, span_days // 3))
    seen_late = pd.to_datetime(r.date).max() >= pd.to_datetime(g.date).max() - pd.Timedelta(days=max(1, span_days // 3))
    if not seen_early and seen_late:
        trend = "New"
    elif seen_early and not seen_late:
        trend = "Lost"
    elif pd.notna(early) and pd.notna(late) and abs(late - early) >= 2:
        trend = "Improving" if late < early else "Declining"   # lower rank = better
    else:
        trend = "Stable"
    return pd.Series({"latest_rank": latest, "best_rank": best, "avg_rank": avg,
                      "days_tracked": days_tracked, "days_ranked": days_ranked,
                      "ac_badge": ac, "trend": trend})
rfk = D.groupby(["region", "family", "keyword"]).apply(kw_agg).reset_index()
for col in ("kw_tracked", "kw_ranked", "kw_top10", "kw_top50"):
    rfd[col] = rfd[col].astype(int)
for col in ("days_tracked", "days_ranked"):
    rfk[col] = rfk[col].astype(int)

# ── 4. replace derived tables (safe: they are pure functions of rank_daily) ───
def reload(table, df, cols):
    cur.execute(f"truncate {table}")
    vals = [tuple(None if (isinstance(v, float) and pd.isna(v)) else v for v in row)
            for row in df[cols].itertuples(index=False, name=None)]
    execute_values(cur, f"insert into {table} ({','.join(cols)}) values %s", vals, page_size=5000)

reload("rank_family_day", rfd,
       ["region", "family", "date", "kw_tracked", "kw_ranked", "kw_top10", "kw_top50", "median_rank"])
reload("rank_family_keyword", rfk,
       ["region", "family", "keyword", "latest_rank", "best_rank", "avg_rank",
        "days_tracked", "days_ranked", "ac_badge", "trend"])
c.commit()
print(f"re-derived: rank_family_day={len(rfd):,} rows, rank_family_keyword={len(rfk):,} rows")

# ── 5. sanity ────────────────────────────────────────────────────────────────
s = rfd[(rfd.region == "CA") & (rfd.family == "AllevaRed")].sort_values("date").tail(1)
if len(s):
    print("sanity CA/AllevaRed latest day:", s[["date", "kw_tracked", "kw_ranked", "median_rank"]].to_dict("records"))
c.close()
print("✓ ranks refresh complete")
