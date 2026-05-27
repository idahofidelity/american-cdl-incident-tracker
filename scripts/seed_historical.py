#!/usr/bin/env python3
"""
seed_historical.py — One-time historical seed from NHTSA FARS bulk CSVs (2000–2024)

What it does:
  - Downloads FARS annual zips from NHTSA for each year 2000–2024
  - Filters to CDL-required vehicles (large trucks, BODY_TYP 60–79)
  - Joins accident + vehicle + driverrf tables for fault classification
  - Extracts USDOT# for carrier lookup
  - Writes all incidents to data/incidents.json
  - Writes carrier list to data/companies.json

Run ONCE from the project root:
  py -m pip install requests
  py scripts/seed_historical.py

Or with year range:
  py scripts/seed_historical.py --start 2018 --end 2024

Takes ~20-40 min for full 2000-2024 run depending on connection.
Downloads ~800MB total (deleted after each year to save disk).
"""

import csv
import io
import json
import zipfile
import argparse
import logging
import hashlib
import time
import os
from pathlib import Path
from collections import defaultdict

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("seed_historical.log"),
    ],
)
log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
INCIDENTS_FILE = DATA_DIR / "incidents.json"
COMPANIES_FILE = DATA_DIR / "companies.json"

# ── FARS Constants ────────────────────────────────────────────────────────────

FARS_BASE = "https://static.nhtsa.gov/nhtsa/downloads/FARS/{year}/National/FARS{year}NationalCSV.zip"

# BODY_TYP codes for CDL-required large trucks (GVWR > 26,000 lbs or truck-tractor)
# 60 = Single-unit truck 10,001-19,500 lbs (borderline — included)
# 61 = Single-unit truck 19,501-26,000 lbs
# 62 = Single-unit truck 26,001+ lbs (CDL required)
# 63 = Single-unit truck — unknown weight
# 64 = Truck-tractor (bobtail)
# 65 = Truck-tractor + semi-trailer (one unit)
# 66 = Truck-tractor — any configuration (CDL required)
# 67 = Medium/heavy truck (not elsewhere classified)
# 68 = Truck — not further described
# 78 = Tanker truck
# 79 = Garbage/refuse truck
CDL_BODY_TYPES = {63, 64, 66, 67, 78, 79}

# Driver Related Factor codes that indicate AT_FAULT
AT_FAULT_DRF = {
    4,   # Drugs/medication
    6,   # Careless/inattentive driving
    8,   # Aggressive driving / road rage
    19,  # Driving on suspended/revoked license
    21,  # Overloading / improper loading
    22,  # Towing improperly
    26,  # Following improperly
    27,  # Improper lane change
    28,  # Improper lane usage
    29,  # Intentional illegal off-road driving
    31,  # Starting/backing improperly
    33,  # Passing where prohibited
    34,  # Improper passing
    35,  # Passing insufficient distance
    36,  # Erratic/reckless/negligent
    38,  # Failure to yield
    39,  # Failure to obey signs/signals
    47,  # Wrong turn
    48,  # Improper turn
    50,  # Wrong way one-way
    51,  # Wrong side two-way
    52,  # Operator inexperience
    58,  # Overcorrecting
    60,  # Alcohol/drug test refused
}

# DRF codes that indicate NOT_AT_FAULT (environmental/other-caused)
NOT_AT_FAULT_DRF = {
    77,  # Severe crosswind
    79,  # Slippery/loose surface
    80,  # Tire blowout (not driver-caused)
    81,  # Debris in road
    82,  # Ruts/holes/bumps
    83,  # Live animals
    84,  # Vehicle in road
    87,  # Ice/snow/slush on road
}

# FHWA cost model (2024 dollars)
FHWA_COST = {
    "fatal": 12_000_000,
    "injury": 600_000,
    "pdo": 12_000,
}

STATE_FIPS = {
    "1": "AL", "2": "AK", "4": "AZ", "5": "AR", "6": "CA", "8": "CO",
    "9": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY",
}

ROUTE_NAMES = {
    "1": "Interstate", "2": "US Highway", "3": "State Highway",
    "4": "County Road", "5": "Township Road", "6": "Forest Service Road",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_id(year, state, st_case):
    h = hashlib.md5(f"FARS{year}{state}{st_case}".encode()).hexdigest()[:8].upper()
    return f"INC-{year}-{h}"


def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def format_highway(route_code, tway_id, tway_id2):
    route_name = ROUTE_NAMES.get(str(route_code), "")
    if tway_id and tway_id.strip() not in ("", "Not Reported", "Unknown"):
        return tway_id.strip()
    return route_name if route_name else None


def estimate_cost(fatalities, injuries):
    if fatalities > 0:
        return fatalities * FHWA_COST["fatal"] + injuries * FHWA_COST["injury"]
    if injuries > 0:
        return injuries * FHWA_COST["injury"]
    return FHWA_COST["pdo"]


def classify_fault(truck_drf_codes, other_drf_codes):
    """
    Classify fault based on Driver Related Factor codes.
    truck_drf_codes: set of DRF codes for the truck driver
    other_drf_codes: set of DRF codes for other drivers involved
    """
    truck_at_fault = bool(truck_drf_codes & AT_FAULT_DRF)
    truck_env = bool(truck_drf_codes & NOT_AT_FAULT_DRF)
    other_at_fault = bool(other_drf_codes & AT_FAULT_DRF)

    # Truck driver had at-fault contributing factors
    if truck_at_fault and not other_at_fault:
        return "AT_FAULT"

    # Only environmental factors for truck, other driver had at-fault factors
    if other_at_fault and not truck_at_fault:
        return "NOT_AT_FAULT"

    # Pure environmental (weather/road) on truck side, no other driver fault noted
    if truck_env and not truck_at_fault and not other_at_fault:
        return "NOT_AT_FAULT"

    # Both or neither — no clear determination
    return "NO_FAULT_STATED"


def extract_usdot(mcarr_i1, mcarr_i2):
    """Extract USDOT number from FARS MCARR fields."""
    if mcarr_i1 in ("57", "57") and mcarr_i2 not in ("", "0", "777777777", "888888888", "999999999"):
        return mcarr_i2.lstrip("0") or None
    return None


# ── Download & Parse ──────────────────────────────────────────────────────────

def download_year(year):
    url = FARS_BASE.format(year=year)
    log.info(f"Downloading FARS {year}...")
    r = requests.get(url, timeout=120, stream=True)
    if r.status_code != 200:
        log.warning(f"FARS {year} not available (HTTP {r.status_code})")
        return None
    content = b""
    total = 0
    for chunk in r.iter_content(chunk_size=1024 * 1024):
        content += chunk
        total += len(chunk)
        if total % (10 * 1024 * 1024) == 0:
            log.info(f"  Downloaded {total // (1024*1024)}MB...")
    log.info(f"  Complete: {total // (1024*1024)}MB")
    return content


def read_csv_from_zip(zf, filename_pattern):
    """Find and read a CSV. Handles upper/lowercase filenames across FARS years.
    Matches exact basename only (vehicle -> vehicle.csv, not pvehiclesf.csv).
    """
    pat = filename_pattern.lower()
    for name in zf.namelist():
        base = name.split("/")[-1].lower()
        if base in (pat + ".csv", pat + "s.csv", pat.upper() + ".CSV"):
            with zf.open(name) as f:
                text = f.read().decode("utf-8-sig", errors="replace")
                reader = csv.DictReader(io.StringIO(text))
                return list(reader)
    return []


def process_year(year, zip_content):
    """
    Parse one year's FARS zip. Returns list of incident dicts.
    """
    incidents = []
    zf = zipfile.ZipFile(io.BytesIO(zip_content))

    log.info(f"  Parsing accident.csv...")
    accidents = {row["ST_CASE"]: row for row in read_csv_from_zip(zf, "accident")}

    log.info(f"  Parsing vehicle.csv...")
    vehicles = read_csv_from_zip(zf, "vehicle")

    log.info(f"  Parsing driverrf.csv...")
    driverrf_rows = read_csv_from_zip(zf, "driverrf")

    # Build DRF lookup: ST_CASE -> VEH_NO -> set of DRF codes
    drf_by_case_veh = defaultdict(lambda: defaultdict(set))
    for row in driverrf_rows:
        code = safe_int(row.get("DRIVERRF", 0))
        if code > 0:
            drf_by_case_veh[row["ST_CASE"]][row["VEH_NO"]].add(code)

    # Find crashes involving large trucks
    # Group vehicles by ST_CASE
    trucks_by_case = defaultdict(list)
    others_by_case = defaultdict(list)

    for veh in vehicles:
        bt = safe_int(veh.get("BODY_TYP", 0))
        case = veh["ST_CASE"]
        if bt in CDL_BODY_TYPES:
            trucks_by_case[case].append(veh)
        else:
            others_by_case[case].append(veh)

    log.info(f"  {len(trucks_by_case)} crashes with CDL vehicles in {year}")

    for st_case, truck_vehs in trucks_by_case.items():
        acc = accidents.get(st_case)
        if not acc:
            continue

        state_code = acc.get("STATE", "")
        state = STATE_FIPS.get(state_code, acc.get("STATENAME", "UNKNOWN")[:2])
        fatals = safe_int(acc.get("FATALS", 0))

        # Use the first/primary truck vehicle
        truck = truck_vehs[0]
        veh_no = truck.get("VEH_NO", "1")

        # DRF codes
        truck_drf = drf_by_case_veh[st_case][veh_no]
        other_drf = set()
        for ov in others_by_case[st_case]:
            other_drf |= drf_by_case_veh[st_case][ov.get("VEH_NO", "")]

        fault = classify_fault(truck_drf, other_drf)

        # USDOT
        usdot = extract_usdot(
            truck.get("MCARR_I1", ""),
            truck.get("MCARR_I2", ""),
        )

        # Highway
        route = acc.get("ROUTE", "")
        tway = acc.get("TWAY_ID", "")
        tway2 = acc.get("TWAY_ID2", "")
        highway = format_highway(route, tway, tway2)

        # Date
        month = str(safe_int(acc.get("MONTH", 1))).zfill(2)
        day   = str(safe_int(acc.get("DAY", 1))).zfill(2)
        date  = f"{year}-{month}-{day}"

        # Coordinates — field names vary by year (upper/lower case, NAME suffix)
        try:
            lat = float(
                acc.get("LATITUDE") or acc.get("latitude") or
                acc.get("LATITUDENAME") or 0
            )
            lng = float(
                acc.get("LONGITUD") or acc.get("longitud") or
                acc.get("LONGITUDNAME") or 0
            )
            # FARS uses 77/88/99 as unknown sentinel codes
            if abs(lat) > 90  or lat == 0: lat = None
            if abs(lng) > 180 or lng == 0: lng = None
        except (ValueError, TypeError):
            lat = lng = None

        # Injuries (FARS only has fatals in accident.csv; injury count not direct)
        # VE_FORMS = number of vehicles; PERSONS = total persons in crash
        # We use FATALS from accident and assume injury if PERSONS > FATALS
        persons = safe_int(acc.get("PERSONS", 0))
        injuries_est = max(0, persons - fatals)

        # Body type description — early FARS years lack BODY_TYPNAME
        BODY_TYPE_NAMES = {
            "63": "Single-unit truck (GVWR >26,000 lbs)",
            "64": "Single-unit truck (GVWR unknown)",
            "66": "Truck-tractor",
            "67": "Medium/heavy truck",
            "78": "Unknown medium/heavy truck",
            "79": "Unknown truck type",
        }
        bt_code = str(safe_int(truck.get("BODY_TYP", 0)))
        body_type = truck.get("BODY_TYPNAME") or BODY_TYPE_NAMES.get(bt_code, "Large Truck")

        # County
        county_name = acc.get("COUNTYNAME", "")
        if county_name in ("NOT APPLICABLE", "Unknown", ""):
            county_name = None

        # DRF note for description
        truck_drf_names = []
        for row in driverrf_rows:
            if row["ST_CASE"] == st_case and row["VEH_NO"] == veh_no:
                name = row.get("DRIVERRFNAME", "")
                if name and name != "None Noted":
                    truck_drf_names.append(name)

        drf_note = "; ".join(truck_drf_names[:3]) if truck_drf_names else "No contributing factors noted"

        # Build description
        desc = f"FARS fatal crash {year}. {body_type}."
        if fatals > 0:
            desc += f" {fatals} fatali{'ty' if fatals == 1 else 'ties'}."
        if drf_note != "No contributing factors noted":
            desc += f" Truck driver factors: {drf_note}."
        if highway:
            desc += f" Location: {highway}{', ' + county_name if county_name else ''}."

        inc_id = make_id(year, state, st_case)
        est_cost = estimate_cost(fatals, injuries_est)

        incident = {
            "id": inc_id,
            "date": date,
            "state": state,
            "highway": highway,
            "county": county_name,
            "lat": lat,
            "lng": lng,
            "fault": fault,
            "at_fault_driver": None,  # FARS does not publish driver names
            "carrier_name": None,     # Populated later via FMCSA lookup if USDOT available
            "carrier_usdot": usdot,
            "vehicle_type": body_type,
            "severity": {
                "fatalities": fatals,
                "injuries": injuries_est,
                "property_damage_only": fatals == 0 and injuries_est == 0,
            },
            "victims": [],
            "foreign_driver_flag": False,
            "foreign_driver_note": "",
            "cost": {
                "stated_usd": None,
                "estimated_usd": est_cost,
                "estimated_basis": "FHWA comprehensive crash cost model (2024 dollars)",
            },
            "description": desc,
            "sources": [
                f"NHTSA FARS {year} — Case {st_case} — https://www.nhtsa.gov/research-data/fatality-analysis-reporting-system-fars"
            ],
            "added": f"{year}-12-31",
            "reviewed": True,
            "_source": "FARS_SEED",
        }
        incidents.append(incident)

    return incidents


# ── Company Builder ───────────────────────────────────────────────────────────

def build_companies(incidents):
    """Aggregate company stats from incidents. FMCSA lookup done separately."""
    company_map = {}

    for inc in incidents:
        usdot = inc.get("carrier_usdot")
        if not usdot:
            continue
        if usdot not in company_map:
            company_map[usdot] = {
                "carrier_usdot": usdot,
                "carrier_name": None,
                "total_drivers": 0,
                "cdl_drivers": 0,
                "power_units": 0,
                "safety_rating": "Not Rated",
                "incident_count": 0,
                "fatal_count": 0,
                "at_fault_count": 0,
                "incidents_per_100_drivers": 0,
                "at_fault_per_100_drivers": 0,
            }
        rec = company_map[usdot]
        rec["incident_count"] += 1
        rec["fatal_count"] += inc["severity"]["fatalities"]
        if inc["fault"] == "AT_FAULT":
            rec["at_fault_count"] += 1

    return list(company_map.values())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed FARS historical data into incidents.json")
    parser.add_argument("--start", type=int, default=2000, help="Start year (default: 2000)")
    parser.add_argument("--end",   type=int, default=2024, help="End year (default: 2024)")
    parser.add_argument("--append", action="store_true", help="Append to existing data instead of replacing")
    parser.add_argument("--state", type=str, default=None, help="Filter to single state abbreviation (e.g. ID)")
    args = parser.parse_args()

    log.info(f"=== FARS Historical Seed: {args.start}–{args.end} ===")

    if args.append and INCIDENTS_FILE.exists():
        existing = json.loads(INCIDENTS_FILE.read_text())
        existing_ids = {i["id"] for i in existing}
        all_incidents = existing
        log.info(f"Appending to {len(existing)} existing incidents")
    else:
        existing_ids = set()
        all_incidents = []

    total_new = 0

    for year in range(args.start, args.end + 1):
        log.info(f"\n── Year {year} ──────────────────────────")
        zip_content = download_year(year)
        if not zip_content:
            continue

        try:
            year_incidents = process_year(year, zip_content)
        except Exception as e:
            log.error(f"Failed to process {year}: {e}")
            import traceback
            traceback.print_exc()
            continue

        # Filter state if requested
        if args.state:
            year_incidents = [i for i in year_incidents if i["state"] == args.state.upper()]

        # Deduplicate
        new = [i for i in year_incidents if i["id"] not in existing_ids]
        existing_ids.update(i["id"] for i in new)
        all_incidents.extend(new)
        total_new += len(new)

        log.info(f"  {year}: {len(year_incidents)} CDL incidents found, {len(new)} new → running total {len(all_incidents)}")

        # Free memory
        del zip_content

        # Save checkpoint after each year
        all_incidents.sort(key=lambda x: x.get("date", ""), reverse=True)
        INCIDENTS_FILE.write_text(json.dumps(all_incidents, indent=2))
        log.info(f"  Checkpoint saved: {INCIDENTS_FILE}")

    # Build companies
    log.info("\nBuilding company records...")
    companies = build_companies(all_incidents)
    COMPANIES_FILE.write_text(json.dumps(companies, indent=2))

    log.info(f"\n{'='*50}")
    log.info(f"SEED COMPLETE")
    log.info(f"  Total incidents: {len(all_incidents)}")
    log.info(f"  New this run:    {total_new}")
    log.info(f"  Companies found: {len(companies)}")
    log.info(f"  Saved to: {INCIDENTS_FILE}")
    log.info(f"\nNext step: run the regular scraper to add news-sourced incidents")
    log.info(f"  py scripts/scraper.py")


if __name__ == "__main__":
    main()
