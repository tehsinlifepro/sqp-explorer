#!/usr/bin/env python3
"""Export the Datarova "Ranks" + "Keywords" tabs to CSV via the gws CLI (HEADLESS).

Replaces the claude.ai Google Drive connector (which only works interactively and only returns the
first tab) so the daily scheduled task can actually pull the sheet. gws is authenticated via keyring.

Writes Ranks.csv + Keywords.csv to ~/Downloads/Datarova - Ranks & Keywords/ — same format the
Drive-connector path produced, so refresh_ranks.py + build_enrich.py consume them unchanged.

Run: python3 data_pipeline/pull_datarova_gws.py
"""
import subprocess, json, csv, os, sys

GWS = "/usr/local/bin/gws"
SHEET = "1DmeMBsYNXcXmU2992lVb5SJsmCyp52gQgdCMM5FZ1qM"
OUT = os.path.expanduser("~/Downloads/Datarova - Ranks & Keywords")
TABS = {"Ranks": "A1:H200000", "Keywords": "A1:Q20000"}  # generous row bounds

def pull(tab, rng):
    p = subprocess.run(
        [GWS, "sheets", "spreadsheets", "values", "get",
         "--params", json.dumps({"spreadsheetId": SHEET, "range": f"{tab}!{rng}"}),
         "--format", "json"],
        capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        sys.exit(f"gws failed for {tab}: {p.stderr[:300] or p.stdout[:300]}")
    out = p.stdout
    i = out.find("{")                       # strip the "Using keyring backend" preamble line
    if i < 0: sys.exit(f"no JSON in gws output for {tab}: {out[:200]}")
    rows = json.loads(out[i:]).get("values", [])
    if len(rows) < 2: sys.exit(f"{tab}: got {len(rows)} rows — sheet empty or wrong range?")
    # pad short rows to the header width (trailing empty cells are omitted by the API)
    w = len(rows[0]); rows = [r + [""] * (w - len(r)) for r in rows]
    path = os.path.join(OUT, f"{tab}.csv")
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    print(f"  {tab}.csv  rows={len(rows) - 1:,}  cols={w}")
    return rows

os.makedirs(OUT, exist_ok=True)
print("pulling Datarova tabs via gws …")
r = pull("Ranks", TABS["Ranks"])
pull("Keywords", TABS["Keywords"])
# quick freshness signal: latest date in Ranks
di = r[0].index("Date")
print("  Ranks latest date:", max(row[di] for row in r[1:] if len(row) > di and row[di]))
print("✓ pulled")
