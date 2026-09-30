# Weekly Granularity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-tab Monthly/Weekly toggle across every time-series tab of SQP Explorer, backed by parallel `_week` tables, without altering the working monthly path.

**Architecture:** Mirror each month-keyed table with a `_week` twin keyed by week-start date; add weekly pipeline steps (SellerLabs weekly SQP pull + `date_trunc('week')` aggregation of Reason daily data); the React app resolves table names from a per-tab `grain` state and formats period labels accordingly.

**Tech Stack:** React (single-file `web/src/App.jsx`, Recharts, Supabase JS), Python data_pipeline (`/usr/bin/python3`, pymysql, psycopg2), Supabase Postgres, GitHub Pages deploy.

## Global Constraints

- Week key = **week-start date**, `YYYY-MM-DD` text, computed as `date_trunc('week', <date>)::date` (ISO Monday-start) on every source, so cross-source weekly joins align. SellerLabs weekly `start_date` is already week-bucketed — normalize it the same way.
- Accumulator rule: weekly tables **upsert on PK, never truncate**.
- **Monthly output must stay byte-identical** — do not modify existing `*_month` tables, monthly builders, or monthly render paths; weekly is additive.
- CA-only paid scope unchanged; region selector behavior unchanged.
- Pipeline runs with `/usr/bin/python3` + Supabase **pooler** env override (`PGHOST=aws-0-us-east-1.pooler.supabase.com PGPORT=5432 PGUSER=postgres.vhrzfsceziyqbrwwwhxv`); `.secrets/supabase.env` sourced first.
- Deploy = commit, `gh auth switch --user tehsinlifepro`, push with the gh credential helper, then `gh auth switch --user umer2325`.
- Verification per task (no unit-test framework in repo): **(a)** `cd web && npm run build` green; **(b)** a data-layer SQL check reconciling weekly→monthly for additive metrics; **(c)** QA via the `代码审查员` subagent; then deploy + document in the "PPC Roadmap" Claude doc.
- Default grain per tab = `'month'`.

---

## Phase 1 — Foundation + Organic (Sprint W1)

### Task 1: Frontend grain plumbing (shared helpers)

**Files:**
- Modify: `web/src/App.jsx` (helpers region near `fmtMonth`, `useMonthRange`, `MonthRange`)

**Interfaces:**
- Produces: `fmtPeriod(grain, key)` → "Aug 2026" | "Wk of Sep 20"; `usePeriodRange(periods)` (same API as `useMonthRange`: `{from,to,setFrom,setTo,inRange,months:periods}`); `GrainToggle({grain,setGrain})` component; `PeriodRange({r})` (grain-agnostic label).

- [ ] **Step 1: Add `fmtPeriod`** next to `fmtMonth`:
```js
const fmtWeek = (d) => { if (!d) return ''; const [y,m,dd]=String(d).split('-'); return `Wk of ${MON_ABBR[(+m)-1]||m} ${+dd}` }
const fmtPeriod = (grain, key) => grain === 'week' ? fmtWeek(key) : fmtMonth(key)
```
- [ ] **Step 2: Add `GrainToggle`** (segmented control reusing `.tab` styles):
```js
const GrainToggle = ({ grain, setGrain }) => (
  <div className="field"><label>Granularity</label>
    <div className="tabs" role="tablist" aria-label="Granularity">
      {[['month','Monthly'],['week','Weekly']].map(([id,l]) => (
        <button key={id} type="button" className={'tab'+(grain===id?' active':'')} role="tab" aria-selected={grain===id} onClick={()=>setGrain(id)}>{l}</button>))}
    </div></div>)
```
- [ ] **Step 3: Generalize the range hook** — `usePeriodRange` is `useMonthRange` verbatim (it already treats keys as opaque sortable strings; works for `YYYY-MM-DD`). Add an alias so intent is clear: `const usePeriodRange = useMonthRange`. Keep `MonthRange` for monthly; components pass the resolved periods list regardless of grain.
- [ ] **Step 4: Build** — `cd web && npm run build`; expected: green (no render path uses these yet).
- [ ] **Step 5: Commit** — `git add web/src/App.jsx && git commit -m "feat(weekly): grain helpers (fmtPeriod, GrainToggle, usePeriodRange)"`

### Task 2: Weekly organic SQP pipeline

**Files:**
- Create: `data_pipeline/refresh_sqp_weekly.py`
- Modify: `data_pipeline/build_supabase_tables.py`, `data_pipeline/build_keyword_tables.py`, `data_pipeline/build_family_tables.py` (add a `GRAIN` env switch: `month` default, `week` reads the weekly master + writes `_week` tables keyed by `week`)
- Create: `data_pipeline/weekly_schema.sql` (the `_week` tables + RLS + grants, mirroring the monthly DDL with `week date` in place of `month text`)

**Interfaces:**
- Produces Supabase tables: `category_week, asin_week, query_summary_week, query_week, query_asin_week, family_niche_week, family_kw_composition_week, family_top_keywords_week` (same columns as `*_month`, period col renamed `week`).

- [ ] **Step 1: `refresh_sqp_weekly.py`** — clone `refresh_sqp.py`; change the SellerLabs pull table `search_query_performance_by_month` → `search_query_performance`; write weekly masters (`LifePro_{CA,US}_SQP_weekly_master.csv`); set `os.environ['GRAIN']='week'`; run the three builders; upsert the `_week` tables (PKs with `week`). Normalize the week key: `week = date_trunc('week', start_date)::date` (or in pandas `pd.to_datetime(start_date).dt.to_period('W-MON').dt.start_time.dt.date`).
- [ ] **Step 2: Builders `GRAIN` switch** — in each builder, read `G=os.environ.get('GRAIN','month')`; when `week`, read the weekly master, group by the week key column named `week`, and write to `*_week` tables/CSVs. Keep the monthly branch untouched.
- [ ] **Step 3: Apply `weekly_schema.sql`** to Supabase (idempotent DDL runner, pooler env).
- [ ] **Step 4: Run** `refresh_sqp_weekly.py`; capture row counts.
- [ ] **Step 5: Reconcile** — SQL check: for a sample family/category, `sum(weekly metric within a month) ≈ monthly metric` for additive fields (impressions/clicks/purchases); market/share fields are per-query constants (dedupe) — spot-check they're sane, not summed. Expected: additive metrics reconcile within rounding.
- [ ] **Step 6: Commit** — `git add data_pipeline/ && git commit -m "feat(weekly): SellerLabs weekly SQP pull + _week organic tables"`

### Task 3: Wire Dashboard + Categories to grain

**Files:** Modify `web/src/App.jsx` (`Dashboard`, `Categories`)

**Interfaces:** Consumes `category_${grain}`, `family_niche_${grain}`, `family_summary` (family_summary is a 12-mo snapshot — stays monthly; note it). Uses `GrainToggle`, `fmtPeriod`, `usePeriodRange`.

- [ ] **Step 1:** Add `const [grain,setGrain]=useState('month')`; fetch `useRows(\`category_${grain}\`,{region})`; period field = `grain==='week'?'week':'month'`; sort/label via that field + `fmtPeriod(grain,...)`.
- [ ] **Step 2:** Add `<GrainToggle grain={grain} setGrain={setGrain}/>` to the controls; XAxis/tooltips use `fmtPeriod`.
- [ ] **Step 3:** Categories: `family_niche_${grain}` for the purchases-in-range rollup; add the toggle. `family_summary` (12-mo) unchanged.
- [ ] **Step 4: Build** green.
- [ ] **Step 5:** Add a weekly-floor note in each tab footer when `grain==='week'` (e.g., "Weekly SQP from {min week}").
- [ ] **Step 6: Commit** — `feat(weekly): Dashboard + Categories grain toggle`

### Task 4: Wire Keyword Explorer to grain

**Files:** Modify `web/src/App.jsx` (`KeywordExplorer`, `KeywordDetail`, `searchQueries`)

- [ ] **Step 1:** Thread `grain`; `searchQueries` reads `query_summary_${grain}` (server-side filter/sort preserved).
- [ ] **Step 2:** `KeywordDetail` reads `query_${grain}` + `query_asin_${grain}`; trend chart x-axis via `fmtPeriod`.
- [ ] **Step 3:** Add `GrainToggle` to the controls; weekly-floor note.
- [ ] **Step 4: Build** green; spot-check a keyword's weekly trend renders.
- [ ] **Step 5: Commit** — `feat(weekly): Keyword Explorer grain toggle`

### Task 5: Wire Family Explorer + ASIN Explorer to grain

**Files:** Modify `web/src/App.jsx` (`FamilyExplorer`, `AsinExplorer`)

- [ ] **Step 1:** FamilyExplorer reads `family_niche_${grain}`, `family_kw_composition_${grain}`, `family_top_keywords_${grain}`; add toggle.
- [ ] **Step 2:** AsinExplorer reads `asin_${grain}`; add toggle.
- [ ] **Step 3: Build** green.
- [ ] **Step 4: Commit** — `feat(weekly): Family + ASIN Explorer grain toggle`

**Phase 1 close:** dispatch QA subagent over Tasks 1–5 (grain resolver correctness, monthly path unchanged, reconciliation, null/label handling); apply fixes; fold `refresh_sqp_weekly.py` into `refresh_db.sh`; deploy; log Sprint W1 in the PPC Roadmap doc.

---

## Phase 2 — Weekly Ads + TACOS (Sprint W2)

### Task 6: Weekly ad + retail tables

**Files:**
- Modify: `data_pipeline/refresh_ads.py`, `refresh_ra.py` (add `GRAIN` switch: period expr `to_char(date,'YYYY-MM')` → `date_trunc('week',date)::date` and target `_week` tables)
- Create: `data_pipeline/ad_week_schema.sql` (`ad_searchterm_week`, `ra_sales_week` + weekly views `v_ad_family_week`, `v_ad_family_searchterm_week`, `v_ad_term_enriched_week`, `v_ra_family_week`, `v_ad_fam_week_all`, `v_tacos_family_week`)

**Interfaces:** Produces the weekly ad/retail tables + views mirroring monthly, period col `week`.

- [ ] **Step 1:** Parameterize `refresh_ads.py` SP/SB SQL period expr + insert target by `GRAIN`; same for `refresh_ra.py`.
- [ ] **Step 2:** Author `ad_week_schema.sql` mirroring `ad_schema.sql` + `ra_schema.sql` views with `week`.
- [ ] **Step 3:** Apply schema; run weekly refreshes; row counts.
- [ ] **Step 4: Reconcile** weekly ad spend/sales summed within a month ≈ monthly; weekly TACOS = weekly ad spend ⋈ weekly ordered_rev (spot-check a family week).
- [ ] **Step 5: Commit** — `feat(weekly): weekly ad_searchterm + ra_sales + tacos views`

### Task 7: Wire Ads tab to grain

**Files:** Modify `web/src/App.jsx` (`AdsExplorer`)

- [ ] **Step 1:** Thread `grain`; family/term/placement/child reads use `v_ad_*_${grain}` (placement/advertised weekly land in Phase 3 — for W2 gate those cards on `grain==='month'` OR ship them in Phase 3; keep spend/ACOS/ROAS/halo family+term weekly now).
- [ ] **Step 2:** Add `GrainToggle`; `PeriodRange`; labels via `fmtPeriod`.
- [ ] **Step 3: Build** green; commit — `feat(weekly): Ads tab grain toggle`

### Task 8: Wire TACOS tab to grain

**Files:** Modify `web/src/App.jsx` (`TacosExplorer`)

- [ ] **Step 1:** Read `v_tacos_family_${grain}`; `CUR_YM`/closed-period logic generalized: monthly compares to current calendar month; weekly excludes the in-progress week (`week < date_trunc('week', now)`).
- [ ] **Step 2:** Reinvest headroom "/day" divisor: month → days-in-month; week → 7. Add a `periodDays(grain,key)` helper.
- [ ] **Step 3:** Targets stay monthly — in weekly mode, the "Actuals vs targets" card shows a note "targets are monthly" and hides or month-aggregates; keep monthly targets join only in monthly mode.
- [ ] **Step 4: Build** green; commit — `feat(weekly): TACOS tab grain toggle`

**Phase 2 close:** QA subagent (weekly TACOS math, closed-week logic, reconciliation); fix; fold weekly ad/ra steps into `refresh_db.sh`; deploy; log Sprint W2.

---

## Phase 3 — Weekly Optimize + Recommendations + Ranks (Sprint W3)

### Task 9: Weekly targeting / placement / advertised / SD

**Files:** Modify `refresh_targeting.py`, `refresh_placements.py`, `refresh_advertised.py`, `refresh_sd.py` (GRAIN switch); Create `data_pipeline/ad_detail_week_schema.sql` (`ad_targeting_week`, `ad_placement_week`, `ad_asin_week`, `sd_campaign_week` + weekly views `v_targeting_enriched_week`, `v_placement_family_week`, `v_ad_asin_week`, `v_sd_week`).

- [ ] **Step 1–3:** Parameterize each refresh's period expr + `_week` targets; author schema; apply; run; reconcile weekly→monthly. Commit — `feat(weekly): weekly targeting/placement/advertised/SD`

### Task 10: Weekly organic ranks

**Files:** Modify `data_pipeline/build_enrich.py` (add `rank_family_week` rollup from `rank_family_day` via `date_trunc('week')`, + `v_rank_kw_enriched_week`); Modify `web/src/App.jsx` later.

- [ ] **Step 1:** Add weekly rank rollup view/table from daily; ad-spend join stays lifetime. Commit — `feat(weekly): weekly rank rollup`

### Task 11: Wire Optimize + Recommendations + Organic Ranks

**Files:** Modify `web/src/App.jsx` (`OptimizeExplorer`, `RecommendationsExplorer`, `OrganicRanks`, and the Ads placement/child cards deferred from Task 7)

- [ ] **Step 1:** OptimizeExplorer reads `v_targeting_enriched_${grain}`; harvest stays lifetime (label). Add toggle.
- [ ] **Step 2:** RecommendationsExplorer: benchmark + all rec generators read `_${grain}` views; `accBench` over the selected weeks; default weekly range = last ~8 weeks. Add toggle.
- [ ] **Step 3:** OrganicRanks: add weekly rank view; toggle. Ads placement/child cards use `v_*_${grain}`.
- [ ] **Step 4: Build** green; commit — `feat(weekly): Optimize + Recommendations + Ranks grain toggle`

**Phase 3 close:** QA subagent; fix; fold weekly steps into `refresh_db.sh`; deploy; log Sprint W3.

---

## Phase 4 — Polish (Sprint W4)

### Task 12: Weekly Downloads

**Files:** Modify `web/src/App.jsx` (`Downloads`)

- [ ] **Step 1:** Add weekly CSV buttons for `asin_week`, `category_week` (+ ad/tacos weekly where useful). Commit — `feat(weekly): weekly CSV exports`

### Task 13: Labels + freshness floors

**Files:** Modify `web/src/App.jsx`

- [ ] **Step 1:** Every weekly tab shows its source's weekly floor (min week present) in the footer; period axis labels via `fmtPeriod` everywhere. Commit — `feat(weekly): period labels + weekly-floor notes`

### Task 14: Full QA sweep + docs/memory

- [ ] **Step 1:** QA subagent across all weekly tabs (monthly unchanged; weekly reconciles; no NaN; labels correct).
- [ ] **Step 2:** Update the PPC Roadmap doc (weekly sprints logged) + the `sqp-ppc-layer` memory (weekly tables + `refresh_db.sh` weekly steps + the `search_query_performance` weekly source).
- [ ] **Step 3:** Final deploy; confirm live build healthy.

---

## Self-Review

**Spec coverage:** every spec table/decision maps to a task — grain toggle (T1), weekly organic tables (T2), each tab wired (T3–5, 7–8, 11), weekly ads/tacos (T6), weekly detail/ranks (T9–10), Downloads (T12), labels/floors (T13), exceptions (Catalog/Campaign Map get no toggle — simply not touched; Targets stays monthly — T8 Step 3). Uneven-history labeling (T3 Step 5, T13). ✓
**Placeholder scan:** period exprs, key normalization, and helper code are given concretely; no TBDs. ✓
**Type consistency:** period column is `week` (date) across all `_week` tables; frontend resolves `table_${grain}` uniformly; `fmtPeriod(grain,key)` used everywhere. ✓
