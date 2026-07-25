#!/usr/bin/env zsh
# DB lane (Ads + SQP) monthly refresh — invoked by launchd (com.lifepro.sqp-refresh-db.plist).
# Sources keep full history, so this is a full rebuild-and-reload, not an accumulator.
# Runs on THIS Mac so its public IP hits SellerLabs/Azure — allowlist the Mac IP once.
set -euo pipefail
cd "$(dirname "$0")/.."                      # -> sqp-explorer/
set -a; . .secrets/supabase.env; set +a      # PG* + AZURE_PG_* + SellerLabs creds
LOG="data_pipeline/refresh.log"
echo "===== DB refresh $(date '+%Y-%m-%d %H:%M:%S') =====" | tee -a "$LOG"

# --- SQP (SellerLabs) --------------------------------------------------------
# TODO: reconstruct data_pipeline/refresh_sqp.py (pull -> rebuild masters -> rebuild derived
#       tables -> reload Supabase). Until it exists this is a no-op with a warning.
if [[ -f data_pipeline/refresh_sqp.py ]]; then
  python3 data_pipeline/refresh_sqp.py 2>&1 | tee -a "$LOG"
else
  echo "WARN: data_pipeline/refresh_sqp.py not built yet — skipping SQP refresh." | tee -a "$LOG"
fi

# --- Ads (Azure Vendor Central) ---------------------------------------------
# TODO: reconstruct data_pipeline/refresh_ads.py — MUST preserve campaign_map.manual_family edits.
if [[ -f data_pipeline/refresh_ads.py ]]; then
  python3 data_pipeline/refresh_ads.py 2>&1 | tee -a "$LOG"
else
  echo "WARN: data_pipeline/refresh_ads.py not built yet — skipping Ads refresh." | tee -a "$LOG"
fi

echo "===== done $(date '+%H:%M:%S') =====" | tee -a "$LOG"
