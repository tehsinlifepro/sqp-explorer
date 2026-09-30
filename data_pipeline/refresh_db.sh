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
echo "--- SQP ---" | tee -a "$LOG"
$PY data_pipeline/refresh_sqp.py 2>&1 | tee -a "$LOG"

# 2. Ads (Azure → ad_searchterm + campaign_map; preserves manual_family).
echo "--- Ads ---" | tee -a "$LOG"
$PY data_pipeline/refresh_ads.py 2>&1 | tee -a "$LOG"

# 3. Campaign auto-mapping (80% advertised-spend dominance; needs Azure). Run AFTER refresh_ads.
echo "--- Campaign map (dominance) ---" | tee -a "$LOG"
$PY data_pipeline/build_campaign_map.py 2>&1 | tee -a "$LOG"

# 4. Retail-analytics total sales (the TACOS denominator; Azure Manufacturing view). Accumulator: upserts, never truncates.
echo "--- Retail analytics (TACOS denominator) ---" | tee -a "$LOG"
$PY data_pipeline/refresh_ra.py 2>&1 | tee -a "$LOG"

echo "===== done $(date '+%H:%M:%S') =====" | tee -a "$LOG"
