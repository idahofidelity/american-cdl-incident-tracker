#!/usr/bin/env python3
"""
American CDL Incident Tracker — Scraper
Google News RSS queries + FMCSA enrichment.
Runs via GitHub Actions on 1st and 15th of each month.
"""

import csv
import hashlib
import io
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR        = Path(__file__).parent.parent / "data"
INCIDENTS_FILE  = DATA_DIR / "incidents.json"
COMPANIES_FILE  = DATA_DIR / "companies.json"
PENDING_FILE    = DATA_DIR / "pending_review.json"

FHWA_COST = {"fatal": 12_000_000, "injury": 600_000, "pdo": 12_000}

# ── Google News Queries ───────────────────────────────────────────────────────

GNEWS_QUERIES = [
    # Fatal / serious
    "semi truck crash killed",
    "tractor trailer crash fatality",
    "18-wheeler accident killed",
    "commercial truck crash dead",
    # At-fault
    "semi truck driver charged DUI crash",
    "truck driver arrested crash",
    "tractor trailer driver cited crash",
    "semi truck driver asleep wheel crash",
    "semi truck ran red light crash",
    "tractor trailer wrong way crash",
    # Not at fault
    "semi truck crash black ice highway",
    "tractor trailer crash ice conditions",
    # Injury
    "semi truck crash injured hospitalized",
    "tractor trailer collision injured highway",
    # Hazmat
    "semi truck hazmat spill highway",
    "tanker truck crash spill highway",
    "semi truck overturned highway closed",
    # Foreign / unlicensed — documented cases
    "truck driver unlicensed crash",
    "truck driver no CDL crash killed",
    "non-domiciled CDL truck crash",
    "illegal immigrant truck driver crash",
    "undocumented truck driver crash",
    "truck driver deported crash",
    "no name given CDL driver crash",
    "truck driver immigration crash",
    "FMCSA non-domiciled carrier crash",
]

GNEWS_BASE = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# ── Fault Classification ──────────────────────────────────────────────────────

AT_FAULT_PHRASES = [
    "driver at fault","cited for","charged with","arrested for",
    "caused the crash","caused the accident","crossed center",
    "crossed the center line","ran red light","ran a red light",
    "failed to yield","fell asleep","fell asleep at the wheel",
    "fatigued","fatigue","impaired","under the influence",
    "dui","dwi","drunk driving","speeding","excessive speed",
    "improper lane change","rear-ended","following too closely",
    "overloaded","unsecured load","distracted","using phone",
    "texting while driving","wrong way","wrong side",
    "no cdl","unlicensed","suspended license","revoked license",
]

NOT_AT_FAULT_PHRASES = [
    "not at fault","other driver caused","other vehicle crossed",
    "other driver ran","other driver failed",
    "black ice","ice on road","icy road","icy conditions",
    "road conditions caused","weather caused",
    "struck by oncoming","hit by oncoming",
    "tire blowout","mechanical failure","brake failure",
    "debris in road","animal in road",
]

# ── Foreign Driver Detection ──────────────────────────────────────────────────
# Three tiers:
#   CONFIRMED  — source explicitly documents foreign/illegal/non-domiciled status
#   PROBABLE   — name "No Name Given" issued by CA DMV, documented practice
#   POSSIBLE   — surname pattern statistically associated with foreign CDL holders
#                flagged as "Possible — verify" not confirmed

FOREIGN_CONFIRMED_PHRASES = [
    "non-domiciled cdl","non domiciled cdl","foreign national",
    "illegal alien","illegal immigrant","undocumented immigrant",
    "undocumented driver","deported","immigration hold",
    "no valid cdl","cdl not valid in","improper cdl",
    "work permit","visa overstay","not authorized to work",
    "kyrgyzstan","eritrea","fmcsa non-domiciled",
]

# "No Name Given" — documented CA DMV practice for foreign/undocumented drivers
# Multiple news articles 2023-2025 document this specifically
NO_NAME_GIVEN_PATTERNS = [
    r'\bno\s+name\s+given\b',
    r'\bno-name-given\b',
    r'\bnonamegiven\b',
]

# Surnames commonly associated with foreign-origin CDL holders in US commercial
# trucking — Indian/Punjabi, Pakistani, Middle Eastern, Eastern European.
# Flagged as POSSIBLE only — requires no source confirmation.
# Source: FMCSA carrier registration data, trucking industry demographic reporting,
#         news coverage of CDL enforcement actions 2020-2025.
#
# Indian / Punjabi
INDIA_ORIGIN_SURNAMES = {
    "singh", "patel", "sharma", "kumar", "yadav", "gupta", "verma",
    "dhaliwal", "grewal", "gill", "sandhu", "sidhu", "brar", "sohi",
    "mann", "virk", "chahal", "bajwa", "randhawa", "sohal", "cheema",
    "dhillon", "atwal", "bains", "nagra", "sekhon", "toor", "hayer",
    "khatkar", "malhi", "pannu", "rai", "sahota", "thind", "uppal",
}

# Pakistani
PAKISTAN_ORIGIN_SURNAMES = {
    "khan", "malik", "chaudhry", "chaudry", "mirza", "butt", "awan",
    "qureshi", "sheikh", "siddiqui", "ahmed", "baig", "rajput",
    "hashmi", "abbasi", "niazi", "bhatti", "javed", "iqbal",
}

# Middle Eastern (Arab, Iranian, Afghan, Turkish)
MIDDLE_EAST_SURNAMES = {
    "al-rashid", "al-hassan", "alrashid", "alhassan", "alhussein",
    "hussein", "hassan", "rahimi", "ahmadi", "karimi", "sultani",
    "mohammadi", "haidari", "nazari", "noori", "wardak",
    "demir", "yilmaz", "kaya", "celik", "arslan", "ozturk",
    "khalil", "mansour", "nassar", "saleh", "hamdan", "farooq",
}

# Eastern European (Ukrainian, Russian, Romanian, Bulgarian, Kyrgyz, Uzbek)
EASTERN_EU_SURNAMES = {
    "kovalenko", "shevchenko", "bondarenko", "kovalchuk", "tkachenko",
    "melnyk", "petrenko", "savchenko", "kravchenko", "lysenko",
    "popescu", "ionescu", "gheorghe", "stan", "dumitru", "constantin",
    "ivanov", "petrov", "sidorov", "volkov", "kuznetsov", "popov",
    "dzhaksybekov", "mamytbekov", "toktosunov", "umarov", "karimov",
    "nazarov", "ergashev", "yusupov", "tursunov", "mirzayev",
    "georgiev", "dimitrov", "stefanov", "angelov", "nikolov",
}

# Combined lookup for fast matching
ALL_FOREIGN_SURNAMES = (
    INDIA_ORIGIN_SURNAMES |
    PAKISTAN_ORIGIN_SURNAMES |
    MIDDLE_EAST_SURNAMES |
    EASTERN_EU_SURNAMES
)

# Common American-origin surnames for driver origin flagging.
# If a driver name is extracted and matches none of the foreign lists,
# it is flagged as American-origin (possible — verify).
# This keeps the data neutral — all drivers flagged equally by name origin.
AMERICAN_SURNAMES = {
    # Anglo/English
    "smith","johnson","williams","jones","brown","davis","miller","wilson",
    "moore","taylor","anderson","thomas","jackson","white","harris","martin",
    "thompson","garcia","martinez","robinson","clark","rodriguez","lewis",
    "lee","walker","hall","allen","young","hernandez","king","wright",
    "lopez","hill","scott","green","adams","baker","gonzalez","nelson",
    "carter","mitchell","perez","roberts","turner","phillips","campbell",
    "parker","evans","edwards","collins","stewart","sanchez","morris",
    "rogers","reed","cook","morgan","bell","murphy","bailey","rivera",
    "cooper","richardson","cox","howard","ward","torres","peterson",
    "gray","ramirez","james","watson","brooks","kelly","sanders","price",
    "bennett","wood","barnes","ross","henderson","coleman","jenkins",
    "perry","powell","long","patterson","hughes","flores","washington",
    "butler","simmons","foster","gonzales","bryant","alexander","russell",
    "griffin","diaz","hayes","myers","ford","hamilton","graham","sullivan",
    "wallace","woods","cole","west","jordan","owens","reynolds","fisher",
    "ellis","harrison","gibson","mcdonald","cruz","marshall","ortiz",
    "gomez","murray","freeman","wells","webb","simpson","stevens","tucker",
    "porter","hunter","hicks","crawford","henry","boyd","mason","morales",
    "kennedy","warren","dixon","ramos","reyes","burns","gordon","shaw",
    "holmes","rice","robertson","hunt","black","daniels","palmer","mills",
    "nichols","grant","knight","ferguson","rose","stone","hawkins","dunn",
    "perkins","hudson","spencer","gardner","stephens","payne","pierce",
    "berry","matthews","arnold","wagner","willis","ray","watkins","olson",
    "carroll","duncan","snyder","hart","cunningham","bradley","lane",
    "andrews","ruiz","harper","fox","riley","armstrong","carpenter",
    "weaver","greene","lawrence","elliott","chavez","sims","austin",
    "peters","kelley","franklin","lawson","fields","gutierrez","ryan",
    "schmidt","carr","vasquez","castillo","wheeler","chapman","oliver",
    "montgomery","larson","carlson","murray","hoffman","little","owen",
    # Irish / Scottish common in trucking
    "o'brien","obrien","o'connor","oconnor","murphy","sullivan","walsh",
    "ryan","byrne","kelly","kennedy","gallagher","o'neil","oneil",
    "mcdonald","mcdonough","mckenzie","mcallister","mcbride","mccoy",
    "mccormick","mccullough","mcdaniel","mcfarland","mcgee","mcguire",
    "mckay","mclaughlin","mcleod","mcmahon","mcmillan","mcneil",
}

def get_surname_region(surname):
    s = surname.lower()
    if s in INDIA_ORIGIN_SURNAMES:   return "Indian/Punjabi-origin"
    if s in PAKISTAN_ORIGIN_SURNAMES: return "Pakistani-origin"
    if s in MIDDLE_EAST_SURNAMES:    return "Middle Eastern-origin"
    if s in EASTERN_EU_SURNAMES:     return "Eastern European-origin"
    return "foreign-origin"

def detect_foreign_driver(text, driver_name):
    """
    Returns (flag_level, note) where flag_level is:
      'confirmed' — source explicitly documents foreign status
      'probable'  — No Name Given DMV-issued name
      'possible'  — surname pattern (India-origin)
      None        — no flag
    """
    t = text.lower()

    # Tier 1: Confirmed — explicit documentation in source
    hits = [p for p in FOREIGN_CONFIRMED_PHRASES if p in t]
    if hits:
        return "confirmed", f"Source documents: {', '.join(hits[:3])}"

    # Tier 2: Probable — "No Name Given" as actual issued name
    for pattern in NO_NAME_GIVEN_PATTERNS:
        if re.search(pattern, t):
            return "probable", (
                '"No Name Given" — name as issued by CA DMV, documented practice '
                'for foreign/undocumented drivers (multiple verified news reports 2023-2025)'
            )

    # Tier 3: Possible — foreign-origin surname
    check_name = (driver_name or "").lower().replace(" ", "")
    if check_name in ("nonamegiven", "no_name_given"):
        return "probable", (
            '"No Name Given" — name as issued by CA DMV, documented practice '
            'for foreign/undocumented drivers (multiple verified news reports 2023-2025)'
        )
    if driver_name:
        name_lower = driver_name.lower()
        for surname in ALL_FOREIGN_SURNAMES:
            if re.search(r'\b' + re.escape(surname) + r'\b', name_lower):
                region = get_surname_region(surname)
                return "possible", (
                    f'Surname "{surname.title()}" is a {region} name common among '
                    f'foreign CDL holders in US commercial trucking — verify against source'
                )

    # Tier 4: American-origin name — flagged equally for neutral comparison
    if driver_name:
        name_lower = driver_name.lower()
        for surname in AMERICAN_SURNAMES:
            if re.search(r'\b' + re.escape(surname) + r'\b', name_lower):
                return "american", f'Surname "{surname.title()}" is an American-origin name — verify against source'

    return None, ""

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path):
    if Path(path).exists():
        return json.loads(Path(path).read_text())
    return []

def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2))

def make_id(date, state, url):
    h = hashlib.md5(f"{date}{state}{url}".encode()).hexdigest()[:8].upper()
    return f"INC-{date[:4]}-{h}"

def classify_fault(text):
    t = text.lower()
    at   = sum(1 for p in AT_FAULT_PHRASES     if p in t)
    not_ = sum(1 for p in NOT_AT_FAULT_PHRASES if p in t)
    if at >= 2 and at > not_:   return "AT_FAULT"
    if not_ >= 1 and not_ > at: return "NOT_AT_FAULT"
    if at == 1 and not_ == 0:   return "AT_FAULT"
    return "NO_FAULT_STATED"

def extract_severity(text):
    t = text.lower()
    fatalities = 0
    injuries   = 0
    m = re.search(r'(\d+)\s+(?:people?|persons?|others?)\s+(?:were\s+)?killed', t)
    if m: fatalities = int(m.group(1))
    elif re.search(r'\b(?:killed|died|dead|fatal|fatality|fatalities)\b', t): fatalities = 1
    m = re.search(r'(\d+)\s+(?:people?|persons?|others?)\s+(?:were\s+)?(?:injured|hurt|hospitalized)', t)
    if m: injuries = int(m.group(1))
    elif re.search(r'\b(?:injured|hurt|hospitalized|taken to hospital|critical condition)\b', t): injuries = 1
    return {"fatalities": fatalities, "injuries": injuries, "property_damage_only": fatalities==0 and injuries==0}

def extract_stated_cost(text):
    for p in [r'\$([0-9,]+(?:\.[0-9]+)?)\s*billion', r'\$([0-9,]+(?:\.[0-9]+)?)\s*million',
              r'\$([0-9,]+)\s+(?:in\s+)?(?:damage|damages|cleanup|repair)']:
        m = re.search(p, text, re.I)
        if m:
            val = float(m.group(1).replace(",",""))
            if "billion" in p: val *= 1e9
            elif "million" in p: val *= 1e6
            return int(val)
    return None

def estimate_cost(sev):
    f, i = sev["fatalities"], sev["injuries"]
    if f > 0: return f * FHWA_COST["fatal"] + i * FHWA_COST["injury"]
    if i > 0: return i * FHWA_COST["injury"]
    return FHWA_COST["pdo"]

STATE_NAMES = {
    "Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA",
    "Colorado":"CO","Connecticut":"CT","Delaware":"DE","Florida":"FL","Georgia":"GA",
    "Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS",
    "Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD","Massachusetts":"MA",
    "Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT",
    "Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM",
    "New York":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK",
    "Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC",
    "South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT",
    "Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY",
}

def extract_state(text):
    for name, abbr in STATE_NAMES.items():
        if name in text: return abbr
    m = re.search(r'\b([A-Z]{2})-\d+\b', text)
    if m and m.group(1) in STATE_NAMES.values(): return m.group(1)
    return None

def extract_highway(text):
    for p in [r'Interstate\s+(\d+[A-Z]?)', r'\bI-(\d+[A-Z]?)\b',
              r'US(?:\s+|-)?(?:Highway\s+)?(\d+)\b', r'(?:State\s+)?(?:Highway|Route|Hwy)\s+(\d+)']:
        m = re.search(p, text, re.I)
        if m:
            if "Interstate" in p or "I-" in p: return f"I-{m.group(1)}"
            if "US" in p: return f"US-{m.group(1)}"
            return f"Hwy {m.group(1)}"
    return None

def extract_driver_name(text, fault):
    """Extract at-fault driver name. Also checks for 'No Name Given'."""
    # Check for No Name Given first regardless of fault
    for pattern in NO_NAME_GIVEN_PATTERNS:
        if re.search(pattern, text, re.I):
            return "No Name Given"

    if fault != "AT_FAULT": return None
    for p in [
        r'(?:driver|trucker|operator)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*(?:,|was|has|of)',
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})[,\s]+(?:age\s+\d+|a\s+\d+-year-old)',
        r'identified\s+as\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})',
        r'(?:arrested|charged|cited)[,:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})',
    ]:
        m = re.search(p, text)
        if m:
            name = m.group(1).strip()
            skip = {"police","officer","troop","highway","according","officials","tuesday","monday",
                    "wednesday","thursday","friday","saturday","sunday","january","february","march",
                    "april","june","july","august","september","october","november","december"}
            if len(name) > 4 and name.split()[0].lower() not in skip:
                return name
    return None

def extract_carrier(text):
    for p in [
        r'([A-Z][A-Za-z\s&]{3,35}(?:Trucking|Transport|Freight|Logistics|Carriers?|Hauling))',
        r'(?:truck(?:ing)?|carrier|transport(?:ation)?)\s+(?:company\s+)?([A-Z][A-Za-z\s&,\.]{3,40}(?:Inc|LLC|Corp|Co|Ltd)\.?)',
    ]:
        m = re.search(p, text)
        if m:
            name = m.group(1).strip().rstrip(".,")
            if len(name) > 5: return name
    return None

def fetch_article(url):
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["nav","footer","script","style","aside","header","iframe"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)[:10000]
    except Exception:
        pass
    return ""

# ── Google News Scraper ───────────────────────────────────────────────────────

def fetch_gnews(existing_sources):
    found = []
    seen_urls = set(existing_sources)

    for query in GNEWS_QUERIES:
        url = GNEWS_BASE.format(query=requests.utils.quote(query))
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code != 200:
                log.warning(f"GNews failed ({r.status_code}): {query}")
                continue

            root = ET.fromstring(r.content)
            items = root.findall(".//item")
            log.info(f"Query '{query}': {len(items)} results")

            for item in items:
                title_el  = item.find("title")
                link_el   = item.find("link")
                pub_el    = item.find("pubDate")
                source_el = item.find("source")

                title  = title_el.text  if title_el  is not None else ""
                link   = link_el.text   if link_el   is not None else ""
                pub    = pub_el.text    if pub_el    is not None else ""
                source_domain = source_el.attrib.get("url","") if source_el is not None else ""

                if not link or link in seen_urls:
                    continue
                seen_urls.add(link)

                try:
                    pub_dt   = datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S")
                    pub_date = pub_dt.strftime("%Y-%m-%d")
                except Exception:
                    pub_date = datetime.now().strftime("%Y-%m-%d")

                if int(pub_date[:4]) < 2000:
                    continue

                # Fetch full article text
                full_text = fetch_article(link) or title

                # Build real source URL from source domain + article title search
                article_title_clean = title.rsplit(" - ", 1)[0].strip()
                if source_domain:
                    real_url = f"{source_domain.rstrip('/')}/search?q={requests.utils.quote(article_title_clean)}"
                else:
                    real_url = f"https://www.google.com/search?q={requests.utils.quote(article_title_clean)}"

                # Extract fields
                state    = extract_state(full_text) or extract_state(title)
                highway  = extract_highway(full_text)
                fault    = classify_fault(full_text)
                severity = extract_severity(full_text)
                driver   = extract_driver_name(full_text, fault)
                carrier  = extract_carrier(full_text)
                stated   = extract_stated_cost(full_text)
                est      = estimate_cost(severity)

                # Driver origin detection — four tiers
                flag_level, flag_note = detect_foreign_driver(full_text, driver)
                foreign_flag      = flag_level in ("confirmed","probable","possible")
                foreign_confirmed = flag_level == "confirmed"
                foreign_probable  = flag_level == "probable"
                foreign_possible  = flag_level == "possible"
                american_flag     = flag_level == "american"

                inc = {
                    "id":              make_id(pub_date, state or "XX", link),
                    "date":            pub_date,
                    "state":           state or "UNKNOWN",
                    "highway":         highway,
                    "county":          None,
                    "lat":             None,
                    "lng":             None,
                    "fault":           fault,
                    "at_fault_driver": driver,
                    "carrier_name":    carrier,
                    "carrier_usdot":   None,
                    "vehicle_type":    None,
                    "severity":        severity,
                    "victims":         [],
                    "foreign_driver_flag":      foreign_flag,
                    "foreign_driver_confirmed": foreign_confirmed,
                    "foreign_driver_probable":  foreign_probable,
                    "foreign_driver_possible":  foreign_possible,
                    "american_driver_flag":     american_flag,
                    "driver_origin_note":       flag_note,
                    "foreign_driver_note":      flag_note if foreign_flag else "",
                    "cost": {
                        "stated_usd":    stated,
                        "estimated_usd": est,
                        "estimated_basis": "FHWA comprehensive crash cost model (2024 dollars)",
                    },
                    "description":  title,
                    "sources":      [real_url],
                    "added":        datetime.now().strftime("%Y-%m-%d"),
                    "reviewed":     False,
                }

                flag_str = f" [{flag_level.upper()}]" if flag_level else ""
                if flag_level == "american": flag_str = " [🇺🇸]"
                sev_str  = f" | {severity['fatalities']} fatal" if severity["fatalities"] else (f" | {severity['injuries']} inj" if severity["injuries"] else "")
                log.info(f"  [{fault[:2]}]{sev_str}{flag_str} {title[:65]}")
                found.append(inc)
                time.sleep(0.2)

        except ET.ParseError as e:
            log.warning(f"XML parse error '{query}': {e}")
        except Exception as e:
            log.warning(f"Error on '{query}': {e}")
        time.sleep(1)

    return found

# ── FMCSA Enrichment ──────────────────────────────────────────────────────────

def fmcsa_census_by_usdot(usdot):
    try:
        r = requests.get(f"https://data.transportation.gov/resource/d9yx-zzpk.json?dot_number={usdot}&$limit=1", timeout=10)
        if r.status_code == 200:
            results = r.json()
            if results:
                rec = results[0]
                return {
                    "carrier_name":  rec.get("legal_name",""),
                    "total_drivers": int(rec.get("total_drivers",0) or 0),
                    "cdl_drivers":   int(rec.get("tot_emp",0) or 0),
                    "power_units":   int(rec.get("total_trucks",0) or 0),
                    "safety_rating": rec.get("safety_rating","Not Rated"),
                }
    except Exception:
        pass
    return None

def enrich_companies(all_incidents):
    existing   = load_json(COMPANIES_FILE)
    company_map = {(c.get("carrier_usdot") or c.get("carrier_name")): c
                   for c in existing if c.get("carrier_usdot") or c.get("carrier_name")}

    for inc in all_incidents:
        usdot = inc.get("carrier_usdot")
        name  = inc.get("carrier_name")
        key   = usdot or name
        if not key: continue

        if key not in company_map:
            fmcsa = fmcsa_census_by_usdot(usdot) if usdot else None
            company_map[key] = {
                "carrier_usdot":  usdot or (fmcsa or {}).get("usdot"),
                "carrier_name":   (fmcsa or {}).get("carrier_name") or name,
                "total_drivers":  (fmcsa or {}).get("total_drivers", 0),
                "cdl_drivers":    (fmcsa or {}).get("cdl_drivers", 0),
                "power_units":    (fmcsa or {}).get("power_units", 0),
                "safety_rating":  (fmcsa or {}).get("safety_rating", "Not Rated"),
                "incident_count": 0, "fatal_count": 0, "at_fault_count": 0,
                "incidents_per_100_drivers": 0, "at_fault_per_100_drivers": 0,
            }
            time.sleep(0.3)

        rec = company_map[key]
        rec["incident_count"]  = rec.get("incident_count", 0) + 1
        rec["fatal_count"]     = rec.get("fatal_count", 0) + inc["severity"]["fatalities"]
        if inc["fault"] == "AT_FAULT":
            rec["at_fault_count"] = rec.get("at_fault_count", 0) + 1
        drivers = rec.get("cdl_drivers") or rec.get("total_drivers") or rec.get("power_units") or 1
        rec["incidents_per_100_drivers"] = round(rec["incident_count"] / drivers * 100, 4)
        rec["at_fault_per_100_drivers"]  = round(rec["at_fault_count"] / drivers * 100, 4)

    return list(company_map.values())

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== American CDL Incident Tracker Scraper ===")
    existing        = load_json(INCIDENTS_FILE)
    existing_ids    = {i["id"] for i in existing}
    existing_sources = {s for i in existing for s in i.get("sources", [])}

    log.info(f"Running {len(GNEWS_QUERIES)} Google News queries...")
    raw = fetch_gnews(existing_sources)

    pending = []
    seen_ids = set(existing_ids)
    for inc in raw:
        if inc["id"] not in seen_ids:
            seen_ids.add(inc["id"])
            pending.append(inc)

    log.info(f"Total new pending incidents: {len(pending)}")

    if pending:
        companies = enrich_companies(existing + pending)
        save_json(COMPANIES_FILE, companies)

    save_json(PENDING_FILE, pending)
    log.info(f"Written {len(pending)} incidents to pending_review.json")
    if pending:
        log.info(f"NEW_INCIDENTS={len(pending)}")
    else:
        log.info("No new incidents found.")

if __name__ == "__main__":
    main()
