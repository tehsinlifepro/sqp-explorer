# SQP Explorer

A small, public-with-a-code web app to explore LifePro's Amazon **Search Query Performance** (SQP)
share data for **US & Canada** — dashboards, a category browser, ASIN lookup, and CSV downloads.

- **App:** static (Vite + React), hosted free on **GitHub Pages**.
- **Data:** hosted on **Supabase** (Postgres + auto REST API).
- **Access:** the app is public, but all data reads require a shared login — the **access code**
  is one Supabase user's password, enforced server-side by Row Level Security (a *real* gate,
  not hidden-in-the-browser).

> All figures are **core-niche, search-attributed** SQP purchases — **not total units sold**
> (they exclude 1P/Vendor Central volume). This matches the QC'd Excel reports.

---

## ✅ CURRENT STATUS (already done)
The Supabase backend is **fully provisioned and verified**:
- Project `vhrzfsceziyqbrwwwhxv` — schema + **7 tables** loaded, RLS gate ON (verified: anon=0 rows, logged-in=data).
  - Dashboard tables (4): `catalog`, `category_month`, `family_summary`, `asin_month`
  - Keyword tables (3): `query_summary` (74k), `query_month` (145k), `query_asin_month` (226k) — powers the Keyword Explorer (search any query → volume, our share, trend, and which ASINs win it). Built by `data_pipeline/build_keyword_tables.py` + `keyword_schema.sql`.
  - Family tables (3): `family_niche_month`, `family_kw_composition`, `family_top_keywords` — powers the Family Explorer (per-family niche movement split by top keyword + our market-share line + top keywords). Built by `data_pipeline/build_family_tables.py` + `family_schema.sql`.
  - Ad tables (2) + 2 views: `campaign_map` (521, **editable** — RLS allows authenticated UPDATE of `manual_family`), `ad_searchterm` (180k, from the Canada Vendor Central ad Search Term Reports); views `v_ad_family_month` / `v_ad_family_searchterm` aggregate by `coalesce(manual_family, auto_family)` so map edits reflect live. Powers the **Ads** and **Campaign Map** tabs. Built by `ad_schema.sql` + the pull/mapping scripts in `~/Downloads/Search Term Reports - Canada/`. **Canada only** (Vendor Central). Campaign→family: SP via `advertised_product` (100% of spend), SB via ASIN/family-name in campaign name (98%); ~5 campaigns triaged manually in the Campaign Map tab.

App tabs (8): Dashboard · Keyword Explorer · Family Explorer · Ads · Campaign Map · Categories · ASIN Explorer · Downloads.
- Shared login created & login-tested end-to-end:
  - **email:** `viewer@lifepro.internal`   **access code:** `LifeProSQP!2026`  ← rotate in Supabase → Auth → Users
- Credentials saved locally in `.secrets/supabase.env` (gitignored) and `web/.env.local`.

**All that's left = deploy the app (Section 2).** Sections 1 & 5 below are already complete;
keep them for reference / rebuilding.

---

## 1. Supabase (data) — one-time  ✅ DONE

1. Create a free project at supabase.com → note the **Project URL** and **anon key**
   (Settings → API).
2. SQL editor → paste & run [`data_pipeline/supabase_schema.sql`](data_pipeline/supabase_schema.sql)
   (creates tables + indexes + the authenticated-only RLS policies).
3. Generate the CSVs locally:
   ```bash
   python3 data_pipeline/build_supabase_tables.py   # writes data_export/*.csv
   ```
4. Import each CSV (Table editor → the table → **Insert → Import from CSV**):
   `catalog`, `category_month`, `family_summary`, `asin_month`.
5. Create the **shared viewer account** (this password = the access code):
   Authentication → Users → **Add user** → email `viewer@lifepro.internal`, set a password,
   and tick **Auto-confirm**. Share that password with your team. Rotate it anytime here.

## 2. App on GitHub Pages

1. Push this folder to a GitHub repo.
2. Repo **Settings → Pages → Source: GitHub Actions**.
3. Repo **Settings → Secrets and variables → Actions → Variables** — add three **Variables**
   (not secrets; they're public by design and safe because of RLS):
   - `VITE_SUPABASE_URL` = your project URL
   - `VITE_SUPABASE_ANON_KEY` = your anon key
   - `VITE_VIEWER_EMAIL` = `viewer@lifepro.internal`
4. Push to `main` → the workflow builds and deploys. Your site: `https://<user>.github.io/<repo>/`.

## 3. Local dev
```bash
cd web
cp .env.example .env.local     # fill in the 3 values
npm install
npm run dev
```

## 4. Monthly refresh
1. Re-pull the new month into the local masters (see the SQP Analysis pipeline / `5_Pipeline`).
2. `python3 data_pipeline/build_supabase_tables.py`
3. Re-import the 4 CSVs in Supabase (or `TRUNCATE` + import; primary keys prevent dupes on upsert).
   No app redeploy needed — the site reads live from Supabase.

---

### What's inside
| Path | What |
|---|---|
| `data_pipeline/build_supabase_tables.py` | Local CSVs → 4 Supabase tables (reuses the QC'd core logic) |
| `data_pipeline/supabase_schema.sql` | Tables, indexes, RLS gate |
| `web/` | Vite + React app (Dashboard · Categories · ASIN Explorer · Downloads) |
| `.github/workflows/deploy.yml` | Build + deploy to GitHub Pages |

### Notes
- The `catalog`, `category_month`, `family_summary`, `asin_month` tables total ~3.3K rows — tiny.
- If you'd rather **not** put the numbers in a public repo, keep `data_export/*.csv` gitignored
  (already is) — they live only in Supabase.
- Verified against the Excel reports: US `B07P5GV3VX` 2026-06 = **2,779**; CA Vibration Plate
  2026-06 = **428**.
