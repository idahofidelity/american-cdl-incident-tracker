#!/usr/bin/env python3
"""
split_data.py — Rebuilds incidents.json from by_year/ files (if needed),
then splits into per-year files + index.json.

Run after any data change:
  py scripts/split_data.py
"""

import json
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"
BY_YEAR  = DATA_DIR / "by_year"
BY_YEAR.mkdir(exist_ok=True)

# Load from by_year/ if incidents.json is missing
incidents_file = DATA_DIR / "incidents.json"
if incidents_file.exists():
    print("Loading incidents.json...")
    incidents = json.loads(incidents_file.read_text())
else:
    print("incidents.json not found — rebuilding from by_year/ files...")
    incidents = []
    for yf in sorted(BY_YEAR.glob("*.json")):
        data = json.loads(yf.read_text())
        incidents.extend(data)
        print(f"  {yf.name}: {len(data)} records")

print(f"Total: {len(incidents)} incidents")

# Split by year
by_year = defaultdict(list)
for inc in incidents:
    year = (inc.get("date") or "0000")[:4]
    by_year[year].append(inc)

for year, incs in sorted(by_year.items()):
    path = BY_YEAR / f"{year}.json"
    path.write_text(json.dumps(incs))
    print(f"  {year}: {len(incs)} incidents → {path.stat().st_size // 1024}KB")

# Rebuild incidents.json from full set
incidents_file.write_text(json.dumps(incidents))
print(f"Rebuilt incidents.json ({incidents_file.stat().st_size // (1024*1024)}MB)")

# Build index
index = {"total_incidents": len(incidents), "years": {}}
for year, incs in sorted(by_year.items()):
    index["years"][year] = {
        "count":      len(incs),
        "fatalities": sum(i["severity"]["fatalities"] for i in incs),
        "injuries":   sum(i["severity"]["injuries"]   for i in incs),
        "at_fault":   sum(1 for i in incs if i["fault"] == "AT_FAULT"),
        "not_fault":  sum(1 for i in incs if i["fault"] == "NOT_AT_FAULT"),
        "foreign":    sum(1 for i in incs if i.get("foreign_driver_flag")),
        "american":   sum(1 for i in incs if i.get("american_driver_flag")),
        "est_cost":   sum(i["cost"]["estimated_usd"] for i in incs if i["cost"].get("estimated_usd")),
    }

(DATA_DIR / "index.json").write_text(json.dumps(index, indent=2))
print(f"index.json written: {len(index['years'])} years, {index['total_incidents']} total")
