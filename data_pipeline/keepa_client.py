#!/usr/bin/env python3
"""Minimal Keepa API client for the Competition Watch (WS3).

- Reads the key from .secrets/keepa.env (never hard-code / never print it).
- Handles Keepa's gzip responses via urllib (no `requests` dependency).
- Caches every raw response to data_pipeline/.keepa_cache/*.json so re-runs
  NEVER re-spend tokens (delete a cache file to force a refresh).
- domain: US=1, CA=3.

Token cost (Keepa): product = 1 token / ASIN ; bestsellers = 50 tokens / call.
Do bulk pulls deliberately — see .build-loop DECISIONS D-004.
"""
import os, json, gzip, time, hashlib, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data_pipeline", ".keepa_cache")
os.makedirs(CACHE, exist_ok=True)

def _key():
    for line in open(os.path.join(ROOT, ".secrets", "keepa.env")):
        line = line.strip()
        if line.startswith("KEEPA_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("KEEPA_API_KEY not set in .secrets/keepa.env")

def _get(path, params, cache_tag, use_cache=True):
    """GET https://api.keepa.com/<path>?<params>; cache by a tag that EXCLUDES the key."""
    cf = os.path.join(CACHE, cache_tag + ".json")
    if use_cache and os.path.exists(cf):
        return json.load(open(cf)), True  # (data, from_cache)
    qs = "&".join(f"{k}={v}" for k, v in params.items() if k != "key")
    url = f"https://api.keepa.com/{path}?key={_key()}&{qs}"
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    for attempt in range(15):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                data = json.loads(raw)
                json.dump(data, open(cf, "w"))
                return data, False
        except urllib.error.HTTPError as e:
            if e.code == 429:  # out of tokens — wait for refill (60/min) and retry patiently
                time.sleep(30); continue
            raise
        except Exception:
            if attempt >= 14: raise
            time.sleep(5)
    raise SystemExit("keepa request failed after retries")

def product(asins, domain, stats=1, history=0, rating=0, buybox=0, use_cache=True):
    """Pull up to 100 ASINs in one call. history=1 adds salesRanks; rating=1 (+<=1 tok) adds
    rating/review history; buybox=1 (+2 tok) adds buy-box winner + buyBoxIsAmazon. Returns product dicts."""
    asins = [a for a in asins if a]
    out, tokens_left = [], None
    for i in range(0, len(asins), 100):
        chunk = asins[i:i + 100]
        tag = f"product_d{domain}_h{history}_r{rating}_b{buybox}_" + hashlib.md5((",".join(chunk)).encode()).hexdigest()[:16]
        params = {"domain": domain, "asin": ",".join(chunk), "stats": stats, "history": history}
        if rating: params["rating"] = 1
        if buybox: params["buybox"] = 1
        d, cached = _get("product", params, tag, use_cache)
        out += (d.get("products") or [])
        tokens_left = d.get("tokensLeft", tokens_left)
        if not cached: time.sleep(1.1)  # be gentle on the refill rate
    return out, tokens_left

def price_of(p):
    """Current price in currency units from stats (NEW, else AMAZON, else NEW_FBA). Keepa prices are cents."""
    st = (p.get("stats") or {}).get("current") or []
    for i in (1, 0, 10):
        if i < len(st) and st[i] and st[i] > 0:
            return round(st[i] / 100.0, 2)
    return None

def enrich_fields(p):
    """Pull the FREE + tiny-surcharge competitor signals from a product (stats=90, rating=1, buybox=1)."""
    st = p.get("stats") or {}
    cur = st.get("current") or []
    def ci(i): return cur[i] if i < len(cur) and cur[i] is not None and cur[i] >= 0 else None
    oos = st.get("outOfStockPercentage90") or []
    def oi(i): return oos[i] if i < len(oos) and oos[i] is not None and oos[i] >= 0 else None
    rating = ci(16)       # value*10 (45 = 4.5 stars)
    return {
        "monthly_sold": p.get("monthlySold"),
        "rating": round(rating / 10.0, 1) if rating else None,
        "review_count": ci(17),
        "price": price_of(p),
        "oos_pct": oi(1) if oi(1) is not None else oi(0),      # NEW else AMAZON out-of-stock %
        "rank_drops": st.get("salesRankDrops90"),
        "amazon_on": (p.get("availabilityAmazon", -1) != -1),  # Amazon itself has an offer
        "bb_amazon": st.get("buyBoxIsAmazon"),                 # Amazon holds the Buy Box
    }

def rank_history(p, cat_id, since_date=None):
    """Extract subcategory BSR history for cat_id from a product (history=1). Returns [(date, bsr)]."""
    import datetime
    sr = (p.get("salesRanks") or {}).get(str(cat_id)) or []
    epoch = datetime.datetime(2011, 1, 1)
    out = []
    for i in range(0, len(sr) - 1, 2):
        t, r = sr[i], sr[i + 1]
        if r is None or r < 0:
            continue
        dt = (epoch + datetime.timedelta(minutes=t)).date()
        if since_date and dt < since_date:
            continue
        out.append((dt, r))
    return out

def bestsellers(category, domain, use_cache=True):
    """Ranked ASIN list for a category (50 tokens). Returns (asinList, tokensLeft)."""
    tag = f"bestsellers_d{domain}_{category}"
    d, _ = _get("bestsellers", {"domain": domain, "category": category}, tag, use_cache)
    bs = d.get("bestSellersList") or {}
    return (bs.get("asinList") or []), d.get("tokensLeft")

def leaf_category(p):
    """Leaf subcategory (catId, name) from a product's categoryTree, else rootCategory."""
    tree = p.get("categoryTree") or []
    if tree: return tree[-1].get("catId"), tree[-1].get("name")
    return p.get("rootCategory"), None

if __name__ == "__main__":
    # smoke test (uses cache — no new spend): show the recon ASIN
    ps, tl = product(["B07P5GV3VX"], domain=1)
    p = ps[0]
    print("brand:", p.get("brand"), "| monthlySold:", p.get("monthlySold"),
          "| leaf:", leaf_category(p), "| tokensLeft:", tl)
