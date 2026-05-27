#!/usr/bin/env python3
"""
merge_pending.py — Merges reviewed/approved incidents from pending_review.json
into incidents.json. Called by GitHub Actions after PR is merged.

Usage:
  python scripts/merge_pending.py                  # merge all pending
  python scripts/merge_pending.py --id INC-2024-XX # merge single incident
"""

import json
import sys
import argparse
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
INCIDENTS_FILE = DATA_DIR / "incidents.json"
PENDING_FILE = DATA_DIR / "pending_review.json"


def load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return []


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="Merge only this incident ID")
    args = parser.parse_args()

    incidents = load_json(INCIDENTS_FILE)
    pending = load_json(PENDING_FILE)

    if not pending:
        print("No pending incidents to merge.")
        return

    existing_ids = {i["id"] for i in incidents}
    merged = 0
    remaining = []

    for inc in pending:
        if args.id and inc["id"] != args.id:
            remaining.append(inc)
            continue
        if inc["id"] in existing_ids:
            print(f"SKIP (duplicate): {inc['id']}")
            continue
        inc["reviewed"] = True
        incidents.append(inc)
        merged += 1
        print(f"MERGED: {inc['id']} — {inc.get('description', '')[:60]}")

    # Sort by date descending
    incidents.sort(key=lambda x: x.get("date", ""), reverse=True)

    save_json(INCIDENTS_FILE, incidents)

    if args.id:
        save_json(PENDING_FILE, remaining)
    else:
        save_json(PENDING_FILE, [])

    print(f"\nMerged {merged} incident(s). Total in database: {len(incidents)}")


if __name__ == "__main__":
    main()
