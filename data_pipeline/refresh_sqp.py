#!/usr/bin/env python3
"""Monthly SQP refresh: SellerLabs (3P Seller Central SQP) → masters → derived tables → Supabase.

SellerLabs keeps ~12 months of history, so this is a full rebuild:
  1. pull search_query_performance_by_month for the catalog's ASINs, per region (CA=venue 4, US=venue 6)
  2. enrich with the CURRENT Supabase `catalog` (asin → category/family/sku) — catalog is user-managed
     in the app's Catalog tab, so this NEVER rewrites it
  3. write the region master CSVs
  4. run the existing builders (build_supabase_tables / build_keyword_tables / build_family_tables)
  5. load the derived CSVs into Supabase (skips `catalog`)

Needs SellerLabs (Mac IP allowlisted — NOT reachable from a Claude sandbox) + Supabase.
Part of the monthly DB lane (Mac launchd → refresh_db.sh).
Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/refresh_sqp.py
"""
import os, sys, subprocess, pandas as pd, pymysql
sys.path.insert(0, os.path.dirname(__file__))
from sb_load import connect as sb_connect, load_csv

CA_DIR = os.path.expanduser("~/Downloads/SQP Analysis Canada")
MASTERS = {"CA": (4, os.path.join(CA_DIR, "4_Data", "LifePro_CA_SQP_master.csv")),
           "US": (6, os.path.join(CA_DIR, "USA SQP", "4_Data", "LifePro_US_SQP_master.csv"))}
PIPE = os.path.dirname(__file__)
# 45 raw SellerLabs columns (the master = these + category/family/sku enrichment)
SL_COLS = ["id", "venue_id", "modified_ts", "start_date", "end_date", "asin", "search_query",
    "search_query_score", "search_query_volume", "total_query_impression_count", "asin_impression_count",
    "asin_impression_share", "total_click_count", "total_click_rate", "asin_click_count", "asin_click_share",
    "total_median_click_price_amount", "total_median_click_price_currency_code", "asin_median_click_price_amount",
    "asin_median_click_price_currency_code", "total_same_day_shipping_click_count", "total_one_day_shipping_click_count",
    "total_two_day_shipping_click_count", "total_cart_add_count", "total_cart_add_rate", "asin_cart_add_count",
    "asin_cart_add_share", "total_median_cart_add_price_amount", "total_median_cart_add_price_currency_code",
    "asin_median_cart_add_price_amount", "asin_median_cart_add_price_currency_code", "total_same_day_shipping_cart_add_count",
    "total_one_day_shipping_cart_add_count", "total_two_day_shipping_cart_add_count", "total_purchase_count",
    "total_purchase_rate", "asin_purchase_count", "asin_purchase_share", "total_median_purchase_price_amount",
    "total_median_purchase_price_currency_code", "asin_median_purchase_price_amount",
    "asin_median_purchase_price_currency_code", "total_same_day_shipping_purchase_count",
    "total_one_day_shipping_purchase_count", "total_two_day_shipping_purchase_count"]
# derived CSV → table (catalog intentionally excluded: it is user-managed in the app)
DERIVED = ["category_month", "family_summary", "asin_month", "query_summary", "query_month",
           "query_asin_month", "family_niche_month", "family_kw_composition", "family_top_keywords"]

def sl():
    return pymysql.connect(host=os.environ["SL_HOST"], port=int(os.environ.get("SL_PORT", 6603)),
        user=os.environ["SL_USER"], password=os.environ["SL_PASSWORD"], database=os.environ["SL_DB"],
        connect_timeout=30, read_timeout=600)

# ── catalog from Supabase (current, user-edited) ──────────────────────────────
sb = sb_connect(); sc = sb.cursor()
sc.execute("select region, asin, category, family, sku from catalog")
cat = pd.DataFrame(sc.fetchall(), columns=["region", "asin", "category", "family", "sku"])

# ── 1-3. pull + enrich + write masters ────────────────────────────────────────
conn = sl(); cur = conn.cursor()
for region, (venue, path) in MASTERS.items():
    asins = cat[cat.region == region].asin.tolist()
    if not asins:
        print(f"  {region}: no catalog ASINs — skipping"); continue
    ph = ",".join(["%s"] * len(asins))
    cur.execute(f"select {','.join(SL_COLS)} from search_query_performance_by_month "
                f"where venue_id=%s and asin in ({ph})", [venue] + asins)
    df = pd.DataFrame(cur.fetchall(), columns=SL_COLS)
    df = df.merge(cat[cat.region == region][["asin", "category", "family", "sku"]], on="asin", how="left")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    print(f"  {region} master: {len(df):,} rows, {df.asin.nunique()} ASINs → {os.path.basename(path)}")
conn.close()

# ── 4. run the existing builders ──────────────────────────────────────────────
for script in ("build_supabase_tables.py", "build_keyword_tables.py", "build_family_tables.py"):
    print(f"  running {script} …")
    r = subprocess.run([sys.executable, os.path.join(PIPE, script)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{script} FAILED:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")

# ── 5. load derived CSVs into Supabase (skip catalog) ─────────────────────────
DE = os.path.expanduser("~/Downloads/sqp-explorer/data_export")
for t in DERIVED:
    n = load_csv(sc, t, os.path.join(DE, f"{t}.csv")); sb.commit()
    print(f"  loaded {t}: {n:,} rows")
sb.close()
print("✓ refresh_sqp complete (catalog left untouched — it is user-managed in the Catalog tab)")
