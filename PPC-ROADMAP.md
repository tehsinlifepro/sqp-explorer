# SQP Explorer → Course-Complete PPC Layer — Roadmap

*Owner: Tehsin · Drafted 2026-10-01 · Lens: Shark Amazon Mastery course (33-video RAG) · Paid data source: **Reason** (Azure PG, Canada Vendor Central)*

## Why

The app is a strong **market + organic** telescope (SQP share, niche movement, organic ranks). On **paid**, it runs on a sliver: the Ads tab pulls **5 columns** (`impressions, clicks, spend, sales, orders`) from **one** of Reason's ~15 ad tables, and the copy is **stale since Jul 25** while everything else refreshed Sep 30. Reason itself is **current to Sep 30**. This roadmap closes the gap to what the course actually teaches.

## The course's PPC brain (five principles)

1. **Think in TACOS, not ACOS.** Set a TACOS ceiling; convert every point saved into a daily reinvest budget. *("TACOS Maths in Scaling Accounts — Understanding Growth Budgets")*
2. **Wasted-spend + harvest** with full **campaign / ad-group / targeting / match-type** context. *("the wasted ad spend table I very actively use")*
3. **Budget optimization + placement / Top-of-Search impression share** for ranked terms (bid opt is slow and risks rank). *("Budget Optimisation & Day Parting")*
4. **Recover & reinvest** — PPC buys organic rank so sales stop depending on ads.
5. **Variation science** — advertise the highest-CVR child.

## Gap → fill (each tagged to a Reason table, all fresh to Sep 30)

| Course principle | In app today | Reason source to add |
|---|---|---|
| 1 · TACOS growth-budget | ❌ ACOS only, no total-sales denominator | `retail_analytics_sales` (ordered/shipped revenue + COGS by ASIN; `distributor_view='Manufacturing'`) |
| 2 · Wasted-spend / harvest | ❌ targeting/match/bid/CPC/CTR/ACOS/ROAS/windows/halo dropped | widen `ads_sponsored_products_search_term` + add `ads_sponsored_products_targeting` |
| 3 · Placement / Top-of-Search | ❌ none | `ads_sponsored_products_campaign_placements` (`placement_type`, bidding strategy) + SB `search_term_impression_share/rank` |
| 4 · Recover & reinvest | ⚠️ have ads + ranks, never joined | join existing `rank_family_*` ⋈ ad spend per keyword |
| 5 · Variation science | ❌ no ASIN/variation ad attribution | `ads_sponsored_products_advertised_product` (`advertised_asin`, halo = other-SKU sales) |
| Bonus · Upper funnel | ❌ SD untouched | `ads_sponsored_display_campaign` (new-to-brand, DPV, ATC, view-through) |

Already right (build on it): the SQP overlay on ad terms (`sqp_volume`, impr/click/purch share next to spend) — the course's "is the CVR drop you or the market" bridge.

## Build plan

### P0 — Reliability + TACOS (the #1 lever)
- **Fix the lane:** fold `refresh_ads.py` into the monthly refresh; widen the search-term pull to CPC, CTR, `7/14/30-day` orders/units/sales, advertised-SKU vs total (**halo**), `acos_clicks_7d`, `roas_clicks_7d`, `campaign_budget_type`, `budget`, `match_type`, `keyword_bid`.
- **Total sales:** new `ra_sales_month` (region · asin · month · ordered_rev · shipped_rev · shipped_cogs · units), Manufacturing view only.
- **TACOS view + tab:** TACOS = ad spend ÷ total sales at account / family / ASIN; user-set ceiling; **$/day reinvest headroom** = (ceiling − current TACOS) × total sales ÷ days. Gross-margin column from COGS.

### P1 — Wasted-spend, harvest, placement, rank-tie
- `ad_targeting` table → **wasted-spend** view (spend, 0 orders, over N days) and **harvest** view (converting in auto/broad, not yet exact).
- `ad_placement_month` → placement mix + **Top-of-Search impression share** + placement ACOS; SB impression share/rank on terms.
- **Recover/reinvest** view: ad spend per keyword ⋈ organic rank trajectory — "buying rank efficiently, or can we pull back?"

### P2 — Variation science + Sponsored Display
- `ad_advertised_product_month` (ASIN-level) → per-child ad CVR + halo; flag the highest-CVR child to advertise.
- `sd_campaign_month` → SD upper-funnel tab (new-to-brand %, DPV, ATC, view-through).

## Data model additions (Supabase)
`ra_sales_month`, `ad_targeting`, `ad_placement_month`, `ad_advertised_product_month`, `sd_campaign_month` — all region-keyed, month grain, upsert PKs (accumulator pattern, never truncate — same golden rule as SQP).

## Notes / guardrails
- **CA only** — Reason is Canada Vendor Central. US ads would need a separate Seller-Central/SP-API lane (out of scope).
- **Halo caution** — total vs advertised-SKU sales differ; never double-count; label clearly.
- **`distributor_view='Manufacturing'`** to avoid the Sourcing double-count.
- **Windows** — SP uses 7-day, SB exposes 14-day only; keep windows explicit in labels.
- Any **Excel export** of these must carry the standing red→white→green conditional formatting rule.
