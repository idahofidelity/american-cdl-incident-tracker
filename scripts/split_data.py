#!/usr/bin/env python3
"""
split_data.py — Splits incidents.json into per-year files + an index.
Run once after seeding, then after each merge.

Output:
  data/by_year/YYYY.json   — incidents for that year
  data/index.json          — metadata: years available, counts, totals (no incident records)
"""

import json
from pathlib import Path
from collections import defaultdict

DATA_DIR   = Path(__file__).parent.parent / "data"
BY_YEAR    = DATA_DIR / "by_year"
BY_YEAR.mkdir(exist_ok=True)

print("Loading incidents.json...")
incidents = json.loads((DATA_DIR / "incidents.json").read_text())
print(f"  {len(incidents)} incidents")

# Split by year
by_year = defaultdict(list)
for inc in incidents:
    year = (inc.get("date") or "0000")[:4]
    by_year[year].append(inc)

# Write per-year files
for year, incs in sorted(by_year.items()):
    path = BY_YEAR / f"{year}.json"
    path.write_text(json.dumps(incs))
    print(f"  {year}: {len(incs)} incidents → {path.stat().st_size // 1024}KB")

# Build index
index = {
    "total_incidents": len(incidents),
    "years": {},
}
for year, incs in sorted(by_year.items()):
    fatalities = sum(i["severity"]["fatalities"] for i in incs)
    injuries   = sum(i["severity"]["injuries"]   for i in incs)
    at_fault   = sum(1 for i in incs if i["fault"] == "AT_FAULT")
    not_fault  = sum(1 for i in incs if i["fault"] == "NOT_AT_FAULT")
    foreign    = sum(1 for i in incs if i.get("foreign_driver_flag"))
    est_cost   = sum(i["cost"]["estimated_usd"] for i in incs if i["cost"].get("estimated_usd"))
    index["years"][year] = {
        "count":      len(incs),
        "fatalities": fatalities,
        "injuries":   injuries,
        "at_fault":   at_fault,
        "not_fault":  not_fault,
        "foreign":    foreign,
        "est_cost":   est_cost,
    }

(DATA_DIR / "index.json").write_text(json.dumps(index, indent=2))
print(f"\nIndex written: {len(index['years'])} years")
print(f"Total: {index['total_incidents']} incidents")
print("\nDone. Commit data/by_year/ and data/index.json to GitHub.")
