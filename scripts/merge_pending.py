#!/usr/bin/env python3
"""
merge_pending.py - Publishes reviewed/approved incidents from pending_review.json.
Called by GitHub Actions (merge.yml) after a scrape/review PR is merged.

Writes what the site actually reads:
  data/by_year/<year>.json   (master source, pretty-printed as before)
  data/index.json            (rebuilt via split_data.py)
  data/incidents.json        (compact, only if present; it is ~100 MB and
                              GitHub rejects files over 100 MB, which is why the
                              old indent=2 rewrite (116 MB) made the push fail)

Usage:
  python scripts/merge_pending.py                   # merge all pending
  python scripts/merge_pending.py --id INC-2024-XX  # merge single incident
  python scripts/merge_pending.py --file X.json     # merge an approved list, leave pending untouched
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from classify import BY_YEAR, DATA_DIR, dedupe_keys  # noqa: E402

INCIDENTS_FILE = DATA_DIR / "incidents.json"
PENDING_FILE = DATA_DIR / "pending_review.json"


def load_json(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="Merge only this incident ID")
    ap.add_argument("--file", help="Merge incidents from this file instead of pending_review.json")
    args = ap.parse_args()

    source = Path(args.file) if args.file else PENDING_FILE
    pending = load_json(source)
    if not pending:
        print("No pending incidents to merge.")
        return

    years = {yf.stem: json.loads(yf.read_text()) for yf in sorted(BY_YEAR.glob("*.json"))}
    seen_ids, seen_keys = set(), set()
    for incs in years.values():
        for i in incs:
            seen_ids.add(i["id"])
            seen_keys |= dedupe_keys(i)

    added, touched, remaining = [], set(), []
    for inc in pending:
        if args.id and inc["id"] != args.id:
            remaining.append(inc)
            continue
        keys = dedupe_keys(inc)
        if inc["id"] in seen_ids or keys & seen_keys:
            print(f"SKIP (duplicate): {inc['id']}")
            continue
        inc["reviewed"] = True
        year = (inc.get("date") or "0000")[:4]
        years.setdefault(year, []).append(inc)
        touched.add(year)
        seen_ids.add(inc["id"])
        seen_keys |= keys
        added.append(inc)
        print(f"MERGED: {inc['id']} - {inc.get('description', '')[:60]}")

    for year in sorted(touched):
        years[year].sort(key=lambda x: x.get("date", ""), reverse=True)
        (BY_YEAR / f"{year}.json").write_text(json.dumps(years[year], indent=2))

    if INCIDENTS_FILE.exists() and added:
        incidents = load_json(INCIDENTS_FILE) + added
        incidents.sort(key=lambda x: x.get("date", ""), reverse=True)
        INCIDENTS_FILE.write_text(json.dumps(incidents))  # compact: keep under 100 MB

    if not args.file:
        PENDING_FILE.write_text(json.dumps(remaining if args.id else [], indent=2))

    subprocess.run([sys.executable, str(Path(__file__).parent / "split_data.py")], check=True)
    print(f"\nMerged {len(added)} incident(s) into {len(touched)} year file(s).")


if __name__ == "__main__":
    main()
