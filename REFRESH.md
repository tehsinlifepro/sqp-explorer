# Keeping SQP Explorer up to date — the refresh routines

Three data streams feed the app. They split by **how the source behaves** and **who can authenticate**,
so they use two different runners. The one rule that matters:

> **A rolling-window source needs an accumulator you only ever UPSERT — never truncate.**
> Ranks is such a source (last ~30 days only). Ads and SQP keep full history, so a plain rebuild is safe.

| Stream | Source | Window | Accumulator? | Cadence | Runner | Status |
|---|---|---|---|---|---|---|
| **Ranks** | Datarova Google Sheet | rolling **30 days** | ✅ `rank_daily` (upsert) | **daily** | Scheduled Claude task (gws) | ✅ **live** |
| **Ads** | Azure Postgres (Canada Vendor Central) | full history | ❌ rebuild ok | monthly | Mac `launchd` | ✅ **built + tested** |
| **SQP** | SellerLabs MySQL (3P) | ~12 mo | ❌ rebuild ok | monthly | Mac `launchd` | ✅ built (pull needs 1st Mac run) |

Why two runners: Ranks pulls a Google Sheet (auth via the `gws` CLI, no DB allowlist). Ads/SQP need
**DB creds + a static IP on the allowlist**, so they run on the Mac. Ads (Azure) + SQP builders/loader
were tested from here; the SellerLabs SQP *pull* can only run where the IP is allowlisted (the Mac).

---

## 1. Ranks — daily, automatic (LIVE)

**What runs:** the scheduled Claude task `refresh-ranks-daily` (06:09 local, daily) runs three commands:
1. `python3 data_pipeline/pull_datarova_gws.py` — pulls the **Ranks** + **Keywords** tabs headlessly via
   the **`gws` CLI** (keyring auth) → `Ranks.csv` + `Keywords.csv`. (NOT the Google Drive connector — that
   only works interactively, so the earlier connector-based task couldn't pull in scheduled runs.)
2. `python3 data_pipeline/refresh_ranks.py` — **UPSERTs** the 30-day window into `rank_daily` (the permanent
   record, never truncated) and **re-derives** `rank_family_day` + `rank_family_keyword` from the *full* accumulator.
3. `python3 data_pipeline/build_enrich.py` — refreshes `kw_market` (Keyword Clicks L4W) + the enrichment views.

Idempotent: re-running on an unchanged sheet changes nothing (`+0` rows). As long as the gap between runs
is < 30 days, no day is missed. **Note:** if `rank_daily` isn't advancing, first check whether the Datarova
sheet itself has newer dates — a stale source (not the task) is the usual cause.

**Manage it:** the "Scheduled" section in the app sidebar, or `update_scheduled_task`.

**Run it by hand any time:**
```bash
cd "$HOME/Downloads/sqp-explorer" && python3 data_pipeline/pull_datarova_gws.py && set -a && . .secrets/supabase.env && set +a && python3 data_pipeline/refresh_ranks.py && python3 data_pipeline/build_enrich.py
```
The accumulator lives in Supabase, so history survives even if this Mac is wiped.

---

## 2. What history you have

`rank_daily` seeded **2026-07-26** with the window `2026-06-15 … 2026-07-14` (193,077 raw rows, all
marketplaces). Every daily run extends the top edge. Query the span any time:
```bash
cd "$HOME/Downloads/sqp-explorer" && set -a && . .secrets/supabase.env && set +a && python3 -c "import os,psycopg2;c=psycopg2.connect(host=os.environ['PGHOST'],port=os.environ.get('PGPORT','5432'),user=os.environ['PGUSER'],password=os.environ['PGPASSWORD'],dbname='postgres',sslmode='require');cur=c.cursor();cur.execute('select count(*),min(date),max(date) from rank_daily');print(cur.fetchone())"
```

---

## 3. Ads + SQP — monthly, on the Mac (built)

These sources retain history, so the routine is a **full monthly rebuild**. They run natively on this Mac
(via `launchd`) so the Mac's **public IP** hits the DBs — allowlist it **once** in SellerLabs and Azure.
`data_pipeline/refresh_db.sh` runs the three scripts in order and logs to `data_pipeline/refresh.log`:

1. **`refresh_sqp.py`** — SellerLabs `search_query_performance_by_month` (CA=venue 4, US=venue 6) for the
   catalog's ASINs → enrich with the current Supabase `catalog` → write masters → run the 3 builders
   (`build_supabase_tables` / `build_keyword_tables` / `build_family_tables`) → load the 9 derived tables
   via `sb_load.py`. **Leaves `catalog` untouched** (it's user-managed in the Catalog tab). *Builders +
   loader are tested; the SellerLabs pull needs its first run on the allowlisted Mac.*
2. **`refresh_ads.py`** — Azure SP/SB search-term reports → rebuild `ad_searchterm` (SP sales/orders =
   7-day window, SB = 14-day) + `campaign_map`, **preserving `manual_family`**. *Tested end-to-end.*
3. **`build_campaign_map.py`** — sets SP `auto_family` by the **80% advertised-spend dominance** rule
   (single family ≥ 80% of a campaign's advertised-product spend → map; else leave unmapped). Must run
   **after** `refresh_ads.py`. Never touches `manual_family`. *Tested (415 mapped / 41 unmapped).*

**launchd (monthly, 1st @ 07:00):**
```bash
cp data_pipeline/com.lifepro.sqp-refresh-db.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.lifepro.sqp-refresh-db.plist
launchctl start com.lifepro.sqp-refresh-db     # test it immediately
```
Before the first run: allowlist the Mac's public IP in **SellerLabs** (and confirm Azure). Then verify
`refresh.log` shows the SQP master row counts.

---

## Golden rules (don't regress)
- **Never `TRUNCATE rank_daily`.** It's the only copy of rank history older than 30 days.
- Ranks app tables (`rank_family_day/keyword`) are *derivations* — always safe to rebuild from `rank_daily`.
- Keep Ranks cadence **< 30 days** (daily is set).
- On an Ads rebuild, **preserve `campaign_map.manual_family`** (the user's manual campaign→family mappings).
- Secrets live in `.secrets/supabase.env` (gitignored). Never commit them.

---

## GOTCHA (2026-08-22) — re-derive / big read-back dies over the pooler; use keepalives

The `BATCH=2000` commit-per-batch loop fixed the *upsert*, but the **step-3 read-back**
(`refresh_ranks.py:81`, `select … from rank_daily` — now ~410k rows) still gets its connection
cut over the session pooler:

```
psycopg2.OperationalError: SSL connection has been closed unexpectedly
psycopg2.OperationalError: server closed the connection unexpectedly
```

It fails *after* the accumulator upsert has already committed, so `rank_daily` is correct but the
derived tables the app reads (`rank_family_day`, `rank_family_keyword`) stay stale — a silent
half-refresh.

**Fix — TCP keepalives.** `data_pipeline/run_keepalive.py` monkeypatches `psycopg2.connect` to add
`keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5` (plus
`statement_timeout=0`) and then runs the target script unchanged. Run either DB step through it:

```
cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a \
  && export PGHOST=aws-0-us-east-1.pooler.supabase.com PGPORT=5432 PGUSER=postgres.vhrzfsceziyqbrwwwhxv \
  && /usr/bin/python3 data_pipeline/run_keepalive.py data_pipeline/refresh_ranks.py
```

With keepalives both `refresh_ranks.py` and `build_enrich.py` complete end-to-end. Long-term the
keepalive kwargs belong in each script's own `conn()`.

**Verify, don't trust the exit code.** Both scripts are piped in the scheduled task, so a Python
traceback can still surface as `exit code 0`. Always confirm the run printed
`✓ ranks refresh complete` / `✓ enrichment build complete`, and sanity-check that the latest
`rank_daily` day has a full row count (~5,963/day) rather than a partial one.
