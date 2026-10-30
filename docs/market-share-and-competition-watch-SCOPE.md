# Market Share + Competition Watch — Scope

_Scoping only. Nothing is built yet. Three workstreams, sequenced._

## The ask (from Tehsin)
1. **Market-share area graph** in the SQP Explorer — our share of the category over time at each funnel stage: **impression share, click share, ATC (cart) share, purchase share** — for **USA and Canada** (demand is mostly US).
2. **USA full build** — stand up the whole SQP Explorer for the US, sourced from the new **USA "Reason" automation DB** (Azure Postgres; creds in `.secrets/usa-reason.env`).
3. **Competition Watch** — a market-share view that includes competitors, via **Keepa API** (subcategory share from BSR), combined with **SQP** and **Datarova rank** data → "a report that's unmatched."

## What we're building on (already exists)
- React single-file app (`web/src/App.jsx`) + **Recharts 2.12** + Supabase Postgres (`vhrzfsceziyqbrwwwhxv`).
- A **region switch** (`REGION` US/CA, line 7) already in the app; `region` columns already on `targets`, `catalog`, etc.
- A full pipeline (`data_pipeline/*.py`): `refresh_sqp`, `refresh_sqp_weekly`, `refresh_ads`, `refresh_advertised`, `refresh_placements`, `refresh_ranks`, etc.
- SQP tables already hold per-stage brand/market counts per period → the 4 share lines are computable from raw counts (CA today; US after WS2).

---

## Discovery findings (2026-10-30) — scope is now firm

Verified against the live DBs:

- **Keepa API: working** — 3,600 tokens, refill 60/min. (`.secrets/keepa.env`)
- **USA Reason DB: connected** (Azure Postgres 16, `.secrets/usa-reason.env`). It is the **US Vendor-Central data platform**: ads (sponsored products/brands/display — search-term, targeting, advertised-product, placements) + retail analytics (sales, traffic, inventory, forecasting, payments, coupons, S&S). Readable via `public` / `raw` schemas; `internal_ra` is permission-denied but `public` mirrors it. **It does NOT contain Brand-Analytics SQP** (no impression/click/cart/purchase *share*).
- **SQP is already handled by the existing pipeline for BOTH regions.** `refresh_sqp.py` pulls from the **SellerLabs** MySQL warehouse per venue (CA=4, US=6). SellerLabs has US: **58,415 rows / 169 ASINs / May–Sep 2026**. `catalog` already has **163 US ASINs**.
- **Supabase already has US data loaded** for the SQP + rank lanes:
  - `category_month` **US 60 / CA 50**, `category_week` **US 247 / CA 196** — and it already carries `our_impr_share / our_click_share / our_atc_share / our_purchase_share` + raw counts + price, by region+period. **The market-share area graph's data is ready.**
  - `asin_month` US 736, `query_month` US 38,619, `rank_family_day` **US 7,604** — US SQP + rank are live.
  - **Ads are CA-only** (`ad_asin_month`, `ad_searchterm`, `ad_placement_month` have no US rows). **This is the real US gap**, and the USA Reason DB is exactly its source.

**Revised plan (much smaller than first scoped):**
- **WS1** = front-end only (data exists for US+CA). Do now.
- **WS2 "USA full build"** = really just the **US ads lane**: map the USA Reason `public.ads_*` tables → the Supabase `ad_*` tables with `region='US'` (SQP + rank already loaded). Then every tab works on the US switch.
- **WS3** = Competition Watch (Keepa ready).

---

## Workstream 1 — Market-Share area graph (the cascade over time)
**What:** a new **Market Share** tab. Recharts stacked/overlaid **area chart**, four series (impression / click / cart-add / purchase share), x-axis = time. Region toggle (US/CA) + the existing Monthly/Weekly toggle. Optional drill: whole-brand (default) → per-family → per-ASIN.

**Definition:** share = our count ÷ market total count, computed **from pooled raw counts per period** (never average percentages — same rule as the book). Brand-level from Brand-View SQP; ASIN-level where ASIN-View is loaded.

**Scope of "category" (important):** this is our share **across the search demand our ASINs/brand appear on** — i.e. the SQP query set — **not** the full subcategory. True whole-subcategory share (including products we never show against) comes from Keepa BSR in WS3. State this on the tab so it isn't misread.

**Data:** CA already in Supabase → **buildable now**. US lands after WS2. New aggregation: one `market_share_month` / `_week` table (region, period, stage counts + shares) built by a small `build_market_share.py`, or computed live from existing summary tables.

**Effort:** Small–Medium. Mostly one tab + one aggregation. The quick visible win.

---

## Workstream 2 — USA full build (from USA Reason Azure Postgres)
**What:** replicate the CA data lane for the US and load it into the **same** Supabase tables with `region='US'`, so every existing tab works when the region switch is set to US.

**Steps:**
1. **Explore the USA Reason schema** (gated on the password) — what does it actually contain: SQP? ads/search-term? advertised-product? rank? price?
2. Map Reason-US columns → the Supabase schema (query/asin/ads/etc.).
3. Build US refresh scripts (mirror `refresh_sqp` / `_weekly` / `_ads` …), parameterized by region.
4. Load US rows; QC totals; wire the region switch across tabs.

**Biggest unknown:** the contents/shape of the USA Reason DB. First task once the password is in. Scope of parity (all tabs vs SQP-first) depends on what the DB has.

**Effort:** Medium–Large, driven by schema parity with the CA source.

---

## Workstream 3 — Competition Watch (Keepa BSR + SQP + Datarova) — the flagship
**Goal:** subcategory market share **including competitors**, plus a per-competitor watch — the "unmatched" report.

**Method:**
- **Keepa API** → pull **BSR history**, category, price, review count, buy-box for our ASINs **and a competitor set**; convert BSR → estimated units/sales (Keepa sales estimates or a BSR→sales curve per subcategory) → each player's **share of the subcategory**.
- **SQP** → our share of the *search demand* + where competitors out-/under-index us per query (from the ASIN/Brand views).
- **Datarova** → keyword **rank** movements for us vs tracked competitors (already in `rank_daily`).
- **Fuse** → a Competition Watch tab/report: competitor table (BSR-estimated subcategory share + trend), our share, head-to-head on shared SQP queries, rank deltas.

**Unknowns / dependencies:**
- **Keepa API key** (paid token plan) — hard dependency; nothing starts without it. Token budget sets how many ASINs/competitors we can watch and how often.
- **BSR→sales estimation** method per subcategory (accuracy caveats; we present ranges, not false precision).
- **Competitor watchlist** source: manual list, auto from SQP co-occurrence (ASINs/brands on our queries), Keepa category top-N, or a curated blend.

**Effort:** Large. Highest value, highest uncertainty.

---

## Proposed sequence
- **Phase 0 (now):** password in → explore USA Reason schema (unblocks WS2). _Parallel:_ confirm Keepa API key (unblocks WS3).
- **Phase 1:** WS1 Market-Share area graph on **CA** (data exists) — quick win; US series added when loaded.
- **Phase 2:** WS2 USA full load.
- **Phase 3:** WS3 Competition Watch.

## Open decisions (need Tehsin)
1. ~~Keepa API key~~ ✅ confirmed working (3,600 tokens). Remaining: how many competitor ASINs should the watch cover (sets token spend)?
2. **Competitor watchlist** — manual list per family, or auto-seed from SQP + Keepa category top-N (then curate)?
3. **USA parity** — full build (all tabs) up front, or SQP + market-share first, ads/rank after?
4. **Area-graph default view** — whole-brand share (default) with family/ASIN drill — confirm.
5. **Excel export?** — if any of this is also delivered as an Excel report, the red→white→green SQP formatting rule applies; if it's in-app only, N/A.
