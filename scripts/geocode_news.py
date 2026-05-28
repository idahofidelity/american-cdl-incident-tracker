#!/usr/bin/env python3
"""
geocode_news.py — Geocodes news incident records that have no lat/lng.
Uses OSM Nominatim (free, no API key, 1 req/sec rate limit).

Builds location query from: highway + state, county + state, or state alone.
Updates by_year/ files in place.

Run from project root:
  py scripts/geocode_news.py

Takes ~10-30 min for 2000+ records.
Checkpoints every 50 records.
"""

import json
import time
import re
import logging
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
BY_YEAR  = DATA_DIR / "by_year"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "AmericanCDLIncidentTracker/1.0 (idahofidelity.com)"}

STATE_NAMES = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
    "CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia",
    "HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas",
    "KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts",
    "MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri","MT":"Montana",
    "NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico",
    "NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma",
    "OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina",
    "SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont",
    "VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming",
}


def build_queries(inc):
    """Build a ranked list of location queries to try, most specific first."""
    state  = inc.get("state", "")
    state_name = STATE_NAMES.get(state, state)
    highway = inc.get("highway", "")
    county  = inc.get("county", "")
    desc    = inc.get("description", "")

    queries = []

    # 1. Highway + state (most specific)
    if highway and state_name and state not in ("UNKNOWN", ""):
        queries.append(f"{highway} {state_name}")

    # 2. County + state
    if county and state_name and state not in ("UNKNOWN", ""):
        queries.append(f"{county} {state_name}")

    # 3. Extract city/town from description
    city_match = re.search(
        r'\bin\s+([A-Z][a-zA-Z\s]{3,20}),?\s+(?:' + '|'.join(STATE_NAMES.values()) + r')\b',
        desc
    )
    if city_match and state_name:
        queries.append(f"{city_match.group(1).strip()} {state_name}")

    # 4. State centroid fallback
    if state_name and state not in ("UNKNOWN", ""):
        queries.append(state_name + " USA")

    return queries


def nominatim_lookup(query):
    """Query Nominatim, return (lat, lng) or (None, None)."""
    try:
        r = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
            headers=HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        log.warning(f"Nominatim error for '{query}': {e}")
    return None, None


def main():
    log.info("=== Geocode News Records ===")

    year_files = sorted(BY_YEAR.glob("*.json"))
    if not year_files:
        log.error("No by_year/ files found. Run split_data.py first.")
        return

    total_processed = 0
    total_geocoded  = 0
    total_skipped   = 0

    for yf in year_files:
        incidents = json.loads(yf.read_text())
        year_updated = False
        year_geocoded = 0

        for inc in incidents:
            # Skip FARS (already has coords from seed) and records already geocoded
            if inc.get("_source") == "FARS_SEED":
                continue
            if inc.get("lat") and inc.get("lng"):
                continue
            if inc.get("state", "UNKNOWN") == "UNKNOWN" and not inc.get("highway"):
                total_skipped += 1
                continue

            queries = build_queries(inc)
            if not queries:
                total_skipped += 1
                continue

            lat = lng = None
            used_query = None
            for q in queries:
                lat, lng = nominatim_lookup(q)
                time.sleep(1.1)  # Nominatim rate limit: 1 req/sec
                if lat and lng:
                    used_query = q
                    break

            if lat and lng:
                inc["lat"] = round(lat, 6)
                inc["lng"] = round(lng, 6)
                inc["_geocoded"] = True
                inc["_geocode_query"] = used_query
                year_geocoded += 1
                total_geocoded += 1
                year_updated = True

            total_processed += 1

            if total_processed % 50 == 0:
                log.info(f"  Processed {total_processed} | geocoded {total_geocoded} | skipped {total_skipped}")
                if year_updated:
                    yf.write_text(json.dumps(incidents, indent=2))

        if year_updated:
            yf.write_text(json.dumps(incidents, indent=2))
            log.info(f"  {yf.name}: geocoded {year_geocoded} records")

    log.info(f"\n=== GEOCODING COMPLETE ===")
    log.info(f"Processed: {total_processed}")
    log.info(f"Geocoded:  {total_geocoded}")
    log.info(f"Skipped:   {total_skipped} (no location data)")
    log.info(f"\nRun split_data.py to rebuild index, then push:")
    log.info(f"  py scripts/split_data.py")
    log.info(f"  git add data/by_year/ data/index.json")
    log.info(f"  git commit -m 'Geocode news records'")
    log.info(f"  git push")


if __name__ == "__main__":
    main()
