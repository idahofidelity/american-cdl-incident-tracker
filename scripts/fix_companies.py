#!/usr/bin/env python3
"""
fix_companies.py — One-time script that:
1. Deduplicates companies.json by USDOT# (merge counts, keep highest)
2. Resolves carrier names from FMCSA SAFER for all entries with USDOT but no name
3. Backfills driver origin flags on existing news incidents

Run from project root:
  py scripts/fix_companies.py
"""

import json
import time
import re
import logging
from pathlib import Path
from collections import defaultdict

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR       = Path(__file__).parent.parent / "data"
COMPANIES_FILE = DATA_DIR / "companies.json"
INCIDENTS_FILE = DATA_DIR / "incidents.json"

# ── FMCSA Name Lookup ─────────────────────────────────────────────────────────

def fmcsa_name_from_safer(usdot):
    """Scrape FMCSA SAFER for carrier legal name by USDOT#."""
    try:
        url = (f"https://safer.fmcsa.dot.gov/query.asp"
               f"?searchtype=ANY&query_type=queryCarrierSnapshot"
               f"&query_param=USDOT&query_string={usdot}")
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        # SAFER returns a table — find "Legal Name" row
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                value = cells[1].get_text(strip=True)
                if "legal name" in label and value:
                    return value
        # Fallback: look for the name in any th/td pair
        tables = soup.find_all("table")
        for table in tables:
            text = table.get_text()
            m = re.search(r'Legal Name[:\s]+([A-Z][^\n]{3,60})', text)
            if m:
                return m.group(1).strip()
    except Exception as e:
        log.warning(f"SAFER lookup failed for USDOT {usdot}: {e}")
    return None

def fmcsa_census_by_usdot(usdot):
    """FMCSA open data Socrata API."""
    try:
        url = f"https://data.transportation.gov/resource/d9yx-zzpk.json?dot_number={usdot}&$limit=1"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            results = r.json()
            if results:
                rec = results[0]
                name = rec.get("legal_name") or rec.get("dba_name") or ""
                return {
                    "carrier_name":  name.strip() if name else None,
                    "total_drivers": int(rec.get("total_drivers", 0) or 0),
                    "cdl_drivers":   int(rec.get("tot_emp", 0) or 0),
                    "power_units":   int(rec.get("total_trucks", 0) or 0),
                    "safety_rating": rec.get("safety_rating", "Not Rated"),
                }
    except Exception:
        pass
    return None

# ── Driver Origin Backfill ────────────────────────────────────────────────────

# Mirrors the detection logic from scraper.py
INDIA_SURNAMES = {"singh","patel","sharma","kumar","yadav","gupta","verma","dhaliwal","grewal","gill","sandhu","sidhu","brar","sohi","mann","virk","chahal","bajwa","randhawa","sohal","cheema","dhillon","atwal","bains","nagra","sekhon","toor","hayer","khatkar","malhi","pannu","rai","sahota","thind","uppal"}
PAKISTAN_SURNAMES = {"khan","malik","chaudhry","chaudry","mirza","butt","awan","qureshi","sheikh","siddiqui","ahmed","baig","rajput","hashmi","abbasi","niazi","bhatti","javed","iqbal"}
MIDDLE_EAST_SURNAMES = {"al-rashid","al-hassan","alrashid","alhassan","alhussein","hussein","hassan","rahimi","ahmadi","karimi","sultani","mohammadi","haidari","nazari","noori","wardak","demir","yilmaz","kaya","celik","arslan","ozturk","khalil","mansour","nassar","saleh","hamdan","farooq"}
EASTERN_EU_SURNAMES = {"kovalenko","shevchenko","bondarenko","kovalchuk","tkachenko","melnyk","petrenko","savchenko","kravchenko","lysenko","popescu","ionescu","gheorghe","stan","dumitru","constantin","ivanov","petrov","sidorov","volkov","kuznetsov","popov","dzhaksybekov","mamytbekov","toktosunov","umarov","karimov","nazarov","ergashev","yusupov","tursunov","mirzayev","georgiev","dimitrov","stefanov","angelov","nikolov"}
AMERICAN_SURNAMES = {"smith","johnson","williams","jones","brown","davis","miller","wilson","moore","taylor","anderson","thomas","jackson","white","harris","martin","thompson","garcia","martinez","robinson","clark","rodriguez","lewis","lee","walker","hall","allen","young","hernandez","king","wright","lopez","hill","scott","green","adams","baker","gonzalez","nelson","carter","mitchell","perez","roberts","turner","phillips","campbell","parker","evans","edwards","collins","stewart","sanchez","morris","rogers","reed","cook","morgan","bell","murphy","bailey","rivera","cooper","richardson","cox","howard","ward","torres","peterson","gray","ramirez","james","watson","brooks","kelly","sanders","price","bennett","wood","barnes","ross","henderson","coleman","jenkins","perry","powell","long","patterson","hughes","flores","washington","butler","simmons","foster","gonzales","bryant","alexander","russell","griffin","diaz","hayes","myers","ford","hamilton","graham","sullivan","wallace","woods","cole","west","jordan","owens","reynolds","fisher","ellis","harrison","gibson","mcdonald","cruz","marshall","ortiz","gomez","murray","freeman","wells","webb","simpson","stevens","tucker","porter","hunter","hicks","crawford","henry","boyd","mason","morales","kennedy","warren","dixon","ramos","reyes","burns","gordon","shaw","holmes","rice","robertson","hunt","black","daniels","palmer","mills","nichols","grant","knight","ferguson","rose","stone","hawkins","dunn","perkins","hudson","spencer","gardner","stephens","payne","pierce","berry","matthews","arnold","wagner","willis","ray","watkins","olson","carroll","duncan","snyder","hart","cunningham","bradley","lane","andrews","ruiz","harper","fox","riley","armstrong","carpenter","weaver","greene","lawrence","elliott","chavez","sims","austin","peters","kelley","franklin","lawson","fields","gutierrez","ryan","schmidt","carr","vasquez","castillo","wheeler","chapman","oliver","montgomery","larson","carlson","hoffman","little","owen","obrien","oconnor","walsh","byrne","gallagher","oneil","mcdonough","mckenzie","mcallister","mcbride","mccoy","mccormick","mccullough","mcdaniel","mcfarland","mcgee","mcguire","mckay","mclaughlin","mcleod","mcmahon","mcmillan","mcneil"}

ALL_FOREIGN = INDIA_SURNAMES | PAKISTAN_SURNAMES | MIDDLE_EAST_SURNAMES | EASTERN_EU_SURNAMES

NO_NAME_RE = re.compile(r'\bno\s*name\s*given\b|\bnonamegiven\b', re.I)

def get_surname_region(s):
    if s in INDIA_SURNAMES:    return "Indian/Punjabi-origin"
    if s in PAKISTAN_SURNAMES:  return "Pakistani-origin"
    if s in MIDDLE_EAST_SURNAMES: return "Middle Eastern-origin"
    if s in EASTERN_EU_SURNAMES: return "Eastern European-origin"
    return "foreign-origin"

def classify_driver_origin(driver_name):
    if not driver_name:
        return None, None, ""
    name_lower = driver_name.lower().replace(" ","")
    if name_lower in ("nonamegiven","no_name_given") or NO_NAME_RE.search(driver_name):
        return "probable", False, ('"No Name Given" — CA DMV documented practice for foreign/undocumented drivers')
    nl = driver_name.lower()
    for s in ALL_FOREIGN:
        if re.search(r'\b' + re.escape(s) + r'\b', nl):
            region = get_surname_region(s)
            return "possible", False, f'Surname "{s.title()}" is a {region} name — verify against source'
    for s in AMERICAN_SURNAMES:
        if re.search(r'\b' + re.escape(s) + r'\b', nl):
            return "american", True, f'Surname "{s.title()}" is an American-origin name — verify against source'
    return None, None, ""

# ── Main ──────────────────────────────────────────────────────────────────────

def fix_companies():
    log.info("Loading companies.json...")
    companies = json.loads(COMPANIES_FILE.read_text())
    log.info(f"  {len(companies)} entries (may include duplicates)")

    # Deduplicate by USDOT# — merge counts
    by_usdot  = defaultdict(list)
    no_usdot  = []

    for c in companies:
        usdot = str(c.get("carrier_usdot") or "").strip()
        if usdot and usdot not in ("0", "None", ""):
            by_usdot[usdot].append(c)
        else:
            no_usdot.append(c)

    merged = []
    for usdot, entries in by_usdot.items():
        # Merge: sum counts, keep best name/rating
        base = entries[0].copy()
        for e in entries[1:]:
            base["incident_count"]  = base.get("incident_count",0)  + e.get("incident_count",0)
            base["fatal_count"]     = base.get("fatal_count",0)     + e.get("fatal_count",0)
            base["at_fault_count"]  = base.get("at_fault_count",0)  + e.get("at_fault_count",0)
            # Keep non-null name
            if not base.get("carrier_name") and e.get("carrier_name"):
                base["carrier_name"] = e["carrier_name"]
        merged.append(base)

    merged.extend(no_usdot)
    log.info(f"  After dedup: {len(merged)} carriers")

    # Resolve missing names
    resolved = 0
    for i, c in enumerate(merged):
        if c.get("carrier_name"):
            continue
        usdot = str(c.get("carrier_usdot") or "").strip()
        if not usdot:
            continue

        log.info(f"  Resolving USDOT {usdot} ({i+1}/{len(merged)})...")

        # Try Socrata first (faster)
        fmcsa = fmcsa_census_by_usdot(usdot)
        if fmcsa and fmcsa.get("carrier_name"):
            c["carrier_name"]  = fmcsa["carrier_name"]
            c["total_drivers"] = fmcsa.get("total_drivers", 0) or c.get("total_drivers", 0)
            c["cdl_drivers"]   = fmcsa.get("cdl_drivers", 0) or c.get("cdl_drivers", 0)
            c["power_units"]   = fmcsa.get("power_units", 0) or c.get("power_units", 0)
            c["safety_rating"] = fmcsa.get("safety_rating", "Not Rated")
            resolved += 1
            time.sleep(0.3)
            continue

        # Fallback to SAFER scrape
        name = fmcsa_name_from_safer(usdot)
        if name:
            c["carrier_name"] = name
            resolved += 1
        time.sleep(0.5)

        # Recalculate per-capita
        drivers = c.get("cdl_drivers") or c.get("total_drivers") or c.get("power_units") or 1
        c["incidents_per_100_drivers"] = round(c.get("incident_count",0) / drivers * 100, 4)
        c["at_fault_per_100_drivers"]  = round(c.get("at_fault_count",0) / drivers * 100, 4)

    log.info(f"  Resolved {resolved} carrier names")

    # Sort by incident count
    merged.sort(key=lambda x: x.get("incident_count", 0), reverse=True)
    COMPANIES_FILE.write_text(json.dumps(merged, indent=2))
    log.info(f"Saved {len(merged)} companies")
    return merged

def backfill_driver_flags():
    log.info("Backfilling driver origin flags on incidents...")
    incidents = json.loads(INCIDENTS_FILE.read_text())
    updated = 0

    for inc in incidents:
        # Skip if already has flag data (from new scraper runs)
        if "foreign_driver_confirmed" in inc:
            continue

        driver = inc.get("at_fault_driver")
        flag_level, american, note = classify_driver_origin(driver)

        inc["foreign_driver_confirmed"] = False
        inc["foreign_driver_probable"]  = flag_level == "probable"
        inc["foreign_driver_possible"]  = flag_level == "possible"
        inc["american_driver_flag"]     = bool(american)
        inc["driver_origin_note"]       = note

        # Only set foreign_driver_flag if not already set by scraper
        if not inc.get("foreign_driver_flag"):
            inc["foreign_driver_flag"] = flag_level in ("probable", "possible")

        if flag_level:
            updated += 1

    log.info(f"  Flagged {updated} incidents with driver origin data")
    INCIDENTS_FILE.write_text(json.dumps(incidents, indent=2))
    log.info(f"  Saved {len(incidents)} incidents")

def main():
    log.info("=== Fix Companies & Backfill Driver Flags ===")
    fix_companies()
    backfill_driver_flags()
    log.info("\nDone. Run split_data.py next:")
    log.info("  py scripts/split_data.py")

if __name__ == "__main__":
    main()
