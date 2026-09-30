# SQP Explorer — Weekly Granularity Across Every Tab

*Design spec · 2026-10-01 · Owner: Tehsin*

## Goal

Add a **weekly** view alongside the existing **monthly** view across every time-series tab of the SQP Explorer app, so trends can be read week-over-week (not just month-over-month). Monthly stays the default and the untouched baseline; weekly is additive.

## Decisions (locked with Tehsin, 2026-10-01)

- **Scope:** every **time-series** tab. Config/editable tabs with no time axis are exceptions (see below).
- **Toggle:** **per-tab** Monthly/Weekly switch (not one global switch), in each tab's controls.
- **Uneven history:** show whatever weekly history each source has, and **label** how far back weekly goes per tab. No artificial capping.
- **Architecture:** **parallel `_week` tables** (Approach A), not a `grain`-column rewrite (Approach B) — zero risk to the just-shipped monthly path.

## Verified data availability (2026-10-01)

| Source | Weekly source | Weekly depth |
| --- | --- | --- |
| Organic SQP | SellerLabs `search_query_performance` (weekly; full funnel cols confirmed) | ~14 weeks (2026-05-24 → 2026-09-20) |
| Ads (SP/SB/SD, targeting, placement, advertised) | Reason (Azure) daily `date` → rolled weekly | ~16+ months (to 2025) |
| Retail sales / TACOS | Reason `retail_analytics_sales` `period='WEEKLY'` | 72 weeks (2025-05-11 → 2026-09-20) |
| Organic ranks | `rank_family_day` (daily) → rolled weekly | full daily history |

Weekly depth is **intentionally uneven** — organic SQP weekly is short (~14 wks) while ads/sales weekly runs ~16 months. The UI labels this per tab.

## Architecture — parallel `_week` tables

- Week key = **week-start date** as `YYYY-MM-DD` text (sortable; joins to daily; ISO week starting Monday, matching each source's `start_date`/`date` week bucketing).
- Each month-keyed table gets a `_week` twin with identical columns except the period key is `week` (date) instead of `month` (`YYYY-MM`).
- Accumulator rule unchanged: weekly tables **upsert** on their PK (never truncate).
- Frontend resolves the table per tab from a `grain` state: monthly → existing `*_month` table; weekly → new `*_week` table.

### New weekly tables / views

Organic (from SellerLabs weekly pull → weekly builders):
`category_week`, `asin_week`, `query_summary_week`, `query_week`, `query_asin_week`, `family_niche_week`, `family_kw_composition_week`, `family_top_keywords_week`.

Ads / TACOS / ranks (from Reason daily + `rank_family_day`):
`ad_searchterm_week`, `ad_targeting_week`, `ad_placement_week`, `ad_asin_week`, `sd_campaign_week`, `ra_sales_week`, `rank_family_week`; plus weekly views mirroring the monthly ones (`v_ad_family_week`, `v_ad_term_enriched_week`, `v_tacos_family_week`, `v_placement_family_week`, `v_ad_asin_week`, `v_sd_week`, `v_targeting_enriched_week`, `v_ad_harvest` stays lifetime, `v_rank_kw_enriched_week`).

## Pipeline

- **New:** `refresh_sqp_weekly.py` — pull SellerLabs `search_query_performance` (venue 4/6) → weekly masters → weekly builders (`build_supabase_tables`, `build_keyword_tables`, `build_family_tables` gain a `--grain week` path or `_week` twins).
- **Extend:** `refresh_ads/ra/targeting/placements/advertised/sd` gain a weekly aggregation (group by week-start instead of month) writing the `_week` tables. Simplest: parameterize the SQL's `to_char(date,'YYYY-MM')` → week-start `date_trunc('week', date)::date`.
- **Fold** all weekly steps into `refresh_db.sh` after their monthly counterparts.
- Weekly schema in `*_week_schema.sql` files, applied idempotently.

## Frontend

- Per-tab `grain` state (`'month' | 'week'`, default `'month'`); a small **Monthly / Weekly** segmented toggle in each eligible tab's controls.
- `usePeriodRange(grain)` generalizes `useMonthRange` — works for both `month` (`YYYY-MM`) and `week` (`YYYY-MM-DD`) keys.
- Table-name resolver: components take `grain` and read `category_${grain}` etc.; charts/labels format the period accordingly (`fmtPeriod(grain, key)` → "Aug 2026" or "Wk of Sep 20").
- Each weekly view shows a one-line note: "Weekly SQP from 2026-05-24" (or the relevant source floor).
- Reuse existing components with a `grain` prop rather than duplicating them.

## Exceptions to "every tab"

- **Catalog**, **Campaign Map** — no time axis (ASIN→family / campaign→family maps). No weekly toggle; nothing to toggle.
- **Targets** — targets are monthly inputs by design; weekly *actuals* already surface in TACOS. Targets input stays monthly.
- **Downloads** — gains weekly CSV exports (not a toggle; separate buttons).

## Phasing (4 weekly-sprints, each PM → Dev → QA → Document)

1. **Foundation + Organic** — weekly SellerLabs SQP pull + `category/asin/query_*_week`, `family_*_week`; grain plumbing (toggle, `usePeriodRange`, resolver, `fmtPeriod`); wire Dashboard, Keyword, Family, Categories, ASIN.
2. **Weekly Ads + TACOS** — `ad_searchterm_week` + views, `ra_sales_week` + `v_tacos_family_week`; wire Ads, TACOS.
3. **Weekly Optimize + Recommendations + Ranks** — `ad_targeting/placement/asin/sd_week`, `rank_family_week`, weekly enriched views; wire Optimize, Recommendations, Organic Ranks.
4. **Polish** — weekly Downloads CSVs, period labels, per-tab freshness/floor notes, full QA sweep.

## Risks / caveats

- **Uneven depth** — labeled per tab; no capping (per decision).
- **Storage / row counts** — weekly ~4× monthly rows; still well under the 50k client fetch cap for most views, but the Keyword weekly (`query_week`) could be large — monitor and, if needed, keep server-side filtering (already used for `query_summary`).
- **Week bucketing consistency** — all sources use their own `start_date`/`date`; normalize every weekly bucket to `date_trunc('week')` (Mon-start) so cross-source weekly joins (e.g., weekly TACOS = weekly ad spend ⋈ weekly sales) align.
- **CA-only paid** unchanged; weekly doesn't alter the region scope.

## Acceptance

- Every eligible tab has a working Monthly/Weekly toggle; monthly output is byte-identical to today.
- Weekly numbers reconcile to monthly when summed within a month (for additive metrics).
- Weekly refresh folded into `refresh_db.sh`; accumulator preserves weekly history.
- Each weekly tab labels its weekly floor. Deploys green; QA clean per sprint.
