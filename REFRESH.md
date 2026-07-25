# Keeping SQP Explorer up to date — the refresh routines

Three data streams feed the app. They split by **how the source behaves** and **who can authenticate**,
so they use two different runners. The one rule that matters:

> **A rolling-window source needs an accumulator you only ever UPSERT — never truncate.**
> Ranks is such a source (last ~30 days only). Ads and SQP keep full history, so a plain rebuild is safe.

| Stream | Source | Window | Accumulator? | Cadence | Runner | Status |
|---|---|---|---|---|---|---|
| **Ranks** | Datarova Google Sheet | rolling **30 days** | ✅ `rank_daily` (upsert) | **daily** | Scheduled Claude task | ✅ **live** |
| **Ads** | Azure Postgres (Canada Vendor Central) | full history | ❌ rebuild ok | monthly | Mac `launchd` | ⚠️ scaffold — see §3 |
| **SQP** | SellerLabs MySQL (3P) | ~12 mo | ❌ rebuild ok | monthly | Mac `launchd` | ⚠️ scaffold — see §3 |

Why two runners: Ranks needs **Google auth** (only a logged-in Claude session has it) but **no** DB
allowlist. Ads/SQP need **DB creds + a static IP on the allowlist** but no Google auth. Opposite needs →
opposite hosts.

---

## 1. Ranks — daily, automatic (LIVE)

**What runs:** the scheduled Claude task `refresh-ranks-daily` (06:09 local, daily). Each run:
1. Pulls the **Ranks** tab from the private Datarova sheet via the Google Drive connector → `Ranks.csv`.
2. Runs `data_pipeline/refresh_ranks.py`, which:
   - **UPSERTs** the pulled 30-day window into `rank_daily` (the permanent record — never truncated),
   - **re-derives** `rank_family_day` + `rank_family_keyword` (what the app reads) from the *full* accumulator.

Idempotent: re-running on the same CSV changes nothing (`+0` rows). As long as the gap between runs is
< 30 days, no day is ever missed — daily gives a wide safety margin.

**Manage it:** the "Scheduled" section in the app sidebar. Edit the schedule/prompt there, or via
`update_scheduled_task`. **Pre-approve once:** click *Run now* so the Drive-connector permission is stored;
otherwise the first real run may pause on a prompt.

**Run it by hand any time** (e.g. after refreshing the CSV yourself):
```bash
cd "$HOME/Downloads/sqp-explorer" && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/refresh_ranks.py
```
To only re-pull the CSV, follow the recipe in the `datarova-projects-gsheet` memory note (Drive connector →
`split_tabs.py … Ranks`). The accumulator lives in Supabase, so history survives even if this Mac is wiped.

---

## 2. What history you have

`rank_daily` seeded **2026-07-26** with the window `2026-06-15 … 2026-07-14` (193,077 raw rows, all
marketplaces). Every daily run extends the top edge. Query the span any time:
```bash
cd "$HOME/Downloads/sqp-explorer" && set -a && . .secrets/supabase.env && set +a && python3 -c "import os,psycopg2;c=psycopg2.connect(host=os.environ['PGHOST'],port=os.environ.get('PGPORT','5432'),user=os.environ['PGUSER'],password=os.environ['PGPASSWORD'],dbname='postgres',sslmode='require');cur=c.cursor();cur.execute('select count(*),min(date),max(date) from rank_daily');print(cur.fetchone())"
```

---

## 3. Ads + SQP — monthly, on the Mac (scaffold; needs first verified run)

These sources retain history, so the routine is a **full monthly rebuild**, not an accumulator:
`pull → rebuild derived tables → reload Supabase`. They run natively on this Mac (via `launchd`) so the
Mac's **public IP** is what hits the DBs — allowlist it **once** in SellerLabs and Azure (from a rotating
Claude sandbox the IP churns, which is why these don't run as a Claude task).

**Not yet built:** the SellerLabs SQP pull and the Azure ad-search-term pull were done ad-hoc earlier and
never saved as scripts (`ad_searchterm` also has no primary key yet). To finish this lane:
1. Reconstruct `data_pipeline/refresh_sqp.py` (SellerLabs → rebuild masters → rebuild `catalog`,
   `category_month`, `family_summary`, `asin_month`, `query_*`, `family_*` → reload Supabase) and
   `data_pipeline/refresh_ads.py` (Azure → rebuild `ad_searchterm` + `campaign_map`, **preserving**
   `manual_family` edits → reload). The exact pull SQL is recoverable from the project transcript.
2. Verify them once by running on this Mac (with the Mac IP allowlisted).
3. Schedule with the launchd job below.

**launchd (monthly, 1st @ 07:00).** Save as `~/Library/LaunchAgents/com.lifepro.sqp-refresh-db.plist`,
then `launchctl load ~/Library/LaunchAgents/com.lifepro.sqp-refresh-db.plist`. Template lives at
`data_pipeline/com.lifepro.sqp-refresh-db.plist`; it runs `data_pipeline/refresh_db.sh` (which loads
`.secrets/supabase.env` and calls the two pull scripts, logging to `data_pipeline/refresh.log`).
⚠️ `manual_family` edits in the Campaign Map tab must be **preserved** across an Ads rebuild — reload
`campaign_map` with an UPSERT that never overwrites a non-empty `manual_family`.

---

## Golden rules (don't regress)
- **Never `TRUNCATE rank_daily`.** It's the only copy of rank history older than 30 days.
- Ranks app tables (`rank_family_day/keyword`) are *derivations* — always safe to rebuild from `rank_daily`.
- Keep Ranks cadence **< 30 days** (daily is set).
- On an Ads rebuild, **preserve `campaign_map.manual_family`** (the user's manual campaign→family mappings).
- Secrets live in `.secrets/supabase.env` (gitignored). Never commit them.
