#!/usr/bin/env zsh
# DB lane (SQP + Ads) monthly refresh — invoked by launchd (com.lifepro.sqp-refresh-db.plist).
# Sources keep full history, so this is a full rebuild-and-reload, not an accumulator.
# Runs on THIS Mac so its public IP hits SellerLabs/Azure — allowlist the Mac IP once.
set -uo pipefail
cd "$(dirname "$0")/.."                       # -> sqp-explorer/
set -a; . .secrets/supabase.env; set +a       # PG*, AZURE_PG_*, SL_* creds

# Bare `python3` is Homebrew 3.14 with NO pandas/numpy/psycopg2 — pin the interpreter that has them.
PY=/usr/bin/python3                           # 3.9.6, pandas 2.3.3
# Supabase SESSION pooler. The direct host (db.<ref>.supabase.co:5432) is unreachable from proxied
# environments; the pooler works from both. Drop these 3 lines if you confirm direct works here.
export PGHOST=aws-0-us-east-1.pooler.supabase.com
export PGPORT=5432
export PGUSER=postgres.vhrzfsceziyqbrwwwhxv

LOG="data_pipeline/refresh.log"
echo "===== DB refresh $(date '+%Y-%m-%d %H:%M:%S') =====" | tee -a "$LOG"

# 1. SQP (SellerLabs → masters → derived tables → Supabase). Needs Mac IP on the SellerLabs allowlist.
echo "--- SQP (monthly) ---" | tee -a "$LOG"
$PY data_pipeline/refresh_sqp.py 2>&1 | tee -a "$LOG"

# 1b. SQP weekly (SellerLabs search_query_performance -> _week tables). Parallel to monthly; accumulator.
echo "--- SQP (weekly) ---" | tee -a "$LOG"
$PY data_pipeline/refresh_sqp_weekly.py 2>&1 | tee -a "$LOG"

# 2. Ads (Azure → ad_searchterm + campaign_map; preserves manual_family).
echo "--- Ads ---" | tee -a "$LOG"
$PY data_pipeline/refresh_ads.py 2>&1 | tee -a "$LOG"

# 3. Campaign auto-mapping (80% advertised-spend dominance; needs Azure). Run AFTER refresh_ads.
echo "--- Campaign map (dominance) ---" | tee -a "$LOG"
$PY data_pipeline/build_campaign_map.py 2>&1 | tee -a "$LOG"

# 3b. Ads + Retail WEEKLY (Sprint W2). Apply the weekly schema (tables + TACOS views), then load
# ad_searchterm_week + ra_sales_week. Needs campaign_map (step 3) and catalog (step 1). ra weekly pulls
# period='DAILY' bucketed to ISO Monday weeks (NOT Amazon's Sunday-start WEEKLY) so it aligns with ad weeks.
echo "--- Ads + Retail (weekly) ---" | tee -a "$LOG"
$PY data_pipeline/apply_sql.py data_pipeline/ad_week_schema.sql 2>&1 | tee -a "$LOG"
GRAIN=week $PY data_pipeline/refresh_ads.py 2>&1 | tee -a "$LOG"
GRAIN=week $PY data_pipeline/refresh_ra.py  2>&1 | tee -a "$LOG"

# 4. Retail-analytics total sales (the TACOS denominator; Azure Manufacturing view). Accumulator: upserts, never truncates.
echo "--- Retail analytics (TACOS denominator) ---" | tee -a "$LOG"
$PY data_pipeline/refresh_ra.py 2>&1 | tee -a "$LOG"

# 5. SP targeting (wasted-spend + harvest source). Accumulator.
echo "--- Targeting (wasted-spend + harvest) ---" | tee -a "$LOG"
$PY data_pipeline/refresh_targeting.py 2>&1 | tee -a "$LOG"

# 6. SP placements (Top-of-Search / placement mix). Accumulator.
echo "--- Placements (Top-of-Search) ---" | tee -a "$LOG"
$PY data_pipeline/refresh_placements.py 2>&1 | tee -a "$LOG"

# 7. SP advertised-product (ASIN-level / variation science). Accumulator.
echo "--- Advertised product (ASIN-level) ---" | tee -a "$LOG"
$PY data_pipeline/refresh_advertised.py 2>&1 | tee -a "$LOG"

# 8. Sponsored Display (upper funnel). Accumulator.
echo "--- Sponsored Display ---" | tee -a "$LOG"
$PY data_pipeline/refresh_sd.py 2>&1 | tee -a "$LOG"

echo "===== done $(date '+%H:%M:%S') =====" | tee -a "$LOG"
