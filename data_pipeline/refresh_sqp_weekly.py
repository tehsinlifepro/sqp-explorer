#!/usr/bin/env python3
"""Weekly SQP refresh: SellerLabs weekly `search_query_performance` -> weekly masters -> weekly builders
(_week tables) -> Supabase. Parallel to refresh_sqp.py (which is monthly); does NOT touch monthly tables
or the user-managed catalog.

  1. pull search_query_performance (weekly) for the catalog's ASINs per region (CA=4, US=6)
  2. enrich with the current Supabase catalog (asin -> category/family/sku)
  3. write weekly master CSVs (LifePro_{CA,US}_SQP_weekly_master.csv)
  4. run the builders with GRAIN=week (emit *_week CSVs)
  5. ensure the _week tables exist (build_weekly_schema) then load (accumulate month-keyed twins, truncate the rest)

Needs SellerLabs (Mac IP allowlisted) + Supabase. Part of the monthly DB lane (refresh_db.sh).
Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/refresh_sqp_weekly.py
"""
import os, sys, subprocess, pandas as pd, pymysql
sys.path.insert(0, os.path.dirname(__file__))
from sb_load import connect as sb_connect, load_csv

CA_DIR = os.path.expanduser("~/Downloads/SQP Analysis Canada")
MASTERS = {"CA": (4, os.path.join(CA_DIR, "4_Data", "LifePro_CA_SQP_weekly_master.csv")),
           "US": (6, os.path.join(CA_DIR, "USA SQP", "4_Data", "LifePro_US_SQP_weekly_master.csv"))}
PIPE = os.path.dirname(__file__)
# columns the weekly builders consume (all verified present in search_query_performance)
WK_COLS = ["start_date", "end_date", "asin", "search_query", "search_query_volume",
    "total_query_impression_count", "total_click_count", "total_cart_add_count", "total_purchase_count",
    "asin_impression_count", "asin_click_count", "asin_cart_add_count", "asin_purchase_count",
    "total_median_purchase_price_amount", "asin_median_purchase_price_amount",
    "asin_impression_share", "asin_click_share", "asin_purchase_share"]
DERIVED = ["category_week", "asin_week", "query_summary_week", "query_week", "query_asin_week",
           "family_niche_week", "family_kw_composition_week", "family_top_keywords_week"]
ACCUMULATE = {  # month-keyed twins -> upsert on (…, week); the rest truncate+replace
    "category_week":   ["region", "category", "week"], "asin_week": ["region", "asin", "week"],
    "query_week":      ["region", "search_query", "week"], "query_asin_week": ["region", "search_query", "asin", "week"],
    "family_niche_week": ["region", "family", "week"],
}

def sl():
    return pymysql.connect(host=os.environ["SL_HOST"], port=int(os.environ.get("SL_PORT", 6603)),
        user=os.environ["SL_USER"], password=os.environ["SL_PASSWORD"], database=os.environ["SL_DB"],
        connect_timeout=45, read_timeout=600)

# ── catalog from Supabase (current, user-edited) ──────────────────────────────
sb = sb_connect(); sc = sb.cursor()
sc.execute("select region, asin, category, family, sku from catalog")
cat = pd.DataFrame(sc.fetchall(), columns=["region", "asin", "category", "family", "sku"])

# ── 1-3. pull + enrich + write weekly masters ─────────────────────────────────
conn = sl(); cur = conn.cursor()
for region, (venue, path) in MASTERS.items():
    asins = cat[cat.region == region].asin.tolist()
    if not asins:
        print(f"  {region}: no catalog ASINs — skipping"); continue
    ph = ",".join(["%s"] * len(asins))
    cur.execute(f"select {','.join(WK_COLS)} from search_query_performance where venue_id=%s and asin in ({ph})",
                [venue] + asins)
    df = pd.DataFrame(cur.fetchall(), columns=WK_COLS)
    df = df.merge(cat[cat.region == region][["asin", "category", "family", "sku"]], on="asin", how="left")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    print(f"  {region} weekly master: {len(df):,} rows, {df.asin.nunique()} ASINs → {os.path.basename(path)}")
conn.close()

# ── 4. run the builders in weekly mode ────────────────────────────────────────
env = {**os.environ, "GRAIN": "week"}
for script in ("build_supabase_tables.py", "build_keyword_tables.py", "build_family_tables.py"):
    print(f"  running {script} (GRAIN=week) …")
    r = subprocess.run([sys.executable, os.path.join(PIPE, script)], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        sys.exit(f"{script} FAILED:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")

# ── 5. ensure _week tables exist, then load ───────────────────────────────────
r = subprocess.run([sys.executable, os.path.join(PIPE, "build_weekly_schema.py")], capture_output=True, text=True, env=os.environ)
print(r.stdout[-600:] if r.returncode == 0 else sys.exit(f"build_weekly_schema FAILED:\n{r.stderr[-1500:]}"))
try: sb.close()
except Exception: pass
sb = sb_connect(); sc = sb.cursor()
DE = os.path.expanduser("~/Downloads/sqp-explorer/data_export")
for t in DERIVED:
    conflict = ACCUMULATE.get(t)
    n = load_csv(sc, t, os.path.join(DE, f"{t}.csv"), truncate=(conflict is None), conflict=conflict); sb.commit()
    print(f"  {'upserted' if conflict else 'loaded'} {t}: {n:,} rows")
sb.close()
print("✓ refresh_sqp_weekly complete (monthly + catalog untouched)")
