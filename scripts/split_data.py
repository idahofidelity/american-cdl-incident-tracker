#!/usr/bin/env python3
"""
split_data.py — Rebuilds index.json from existing by_year/ files.
NEVER reads from incidents.json — by_year/ files are the master source.
incidents.json is a local-only working file and should stay in .gitignore.

Run after any data change:
  py scripts/split_data.py
"""

import json
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"
BY_YEAR  = DATA_DIR / "by_year"
BY_YEAR.mkdir(exist_ok=True)

print("Loading from by_year/ files (master source)...")
incidents = []
for yf in sorted(BY_YEAR.glob("*.json")):
    data = json.loads(yf.read_text())
    incidents.extend(data)
    print(f"  {yf.name}: {len(data)} records")

print(f"Total: {len(incidents)} incidents")

# Build index only — do NOT rewrite by_year files
index = {"total_incidents": len(incidents), "years": {}}
by_year = defaultdict(list)
for inc in incidents:
    year = (inc.get("date") or "0000")[:4]
    by_year[year].append(inc)

for year, incs in sorted(by_year.items()):
    index["years"][year] = {
        "count":      len(incs),
        "fatalities": sum(i["severity"]["fatalities"] for i in incs if i.get("severity")),
        "injuries":   sum(i["severity"]["injuries"]   for i in incs if i.get("severity")),
        "at_fault":   sum(1 for i in incs if i.get("fault") == "AT_FAULT"),
        "not_fault":  sum(1 for i in incs if i.get("fault") == "NOT_AT_FAULT"),
        "foreign":    sum(1 for i in incs if i.get("foreign_driver_flag")),
        "american":   sum(1 for i in incs if i.get("american_driver_flag")),
        "est_cost":   sum(i["cost"]["estimated_usd"] for i in incs
                         if i.get("cost") and i["cost"].get("estimated_usd")),
    }

(DATA_DIR / "index.json").write_text(json.dumps(index, indent=2))
print(f"index.json written: {len(index['years'])} years, {index['total_incidents']} total")
print("Done. by_year/ files unchanged.")
