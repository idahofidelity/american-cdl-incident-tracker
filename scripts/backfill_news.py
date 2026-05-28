#!/usr/bin/env python3
"""
backfill_news.py — Re-processes existing news records:
  1. Re-fetches article text from source URLs where possible
  2. Runs fault classification + name extraction on headline + article text
  3. Applies driver origin flags
  4. Saves updated records back to by_year/ files

Run from project root:
  py scripts/backfill_news.py

Takes ~30-60 min depending on how many articles are fetchable.
Checkpoints every 100 records.
"""

import json
import re
import time
import logging
import glob
from pathlib import Path
from collections import defaultdict

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
BY_YEAR  = DATA_DIR / "by_year"

# ── Fault Classification ──────────────────────────────────────────────────────

AT_FAULT_PHRASES = [
    "fell asleep", "asleep at the wheel", "asleep at wheel",
    "charged with", "cited for", "arrested for", "faces charges",
    "dui", "dwi", "drunk driving", "driving drunk", "impaired driving",
    "under the influence", "unlicensed", "no cdl", "no valid cdl",
    "ran red light", "ran a red light", "running red light",
    "reckless driving", "reckless", "negligent",
    "crossed center", "crossed the center line", "wrong way",
    "failed to yield", "failure to yield",
    "speeding", "excessive speed", "too fast",
    "driver at fault", "caused the crash", "caused the accident",
    "distracted", "using phone", "texting",
    "fatigued", "fatigue", "drowsy",
    "overloaded", "unsecured load",
    "improper lane", "following too closely",
    "rear-ended", "rear ended",
    "suspended license", "revoked license",
]

NOT_AT_FAULT_PHRASES = [
    "not at fault", "seizure", "medical episode", "heart attack",
    "black ice", "icy road", "icy conditions", "ice on road",
    "weather caused", "road conditions",
    "tire blowout", "blowout", "mechanical failure", "brake failure",
    "struck by oncoming", "hit by oncoming", "other driver",
    "debris in road", "animal in road",
]

def classify_fault(text):
    t = text.lower()
    at  = sum(1 for p in AT_FAULT_PHRASES  if p in t)
    naf = sum(1 for p in NOT_AT_FAULT_PHRASES if p in t)
    if at >= 1 and at > naf:  return "AT_FAULT"
    if naf >= 1 and naf > at: return "NOT_AT_FAULT"
    return "NO_FAULT_STATED"

def extract_severity(text):
    t = text.lower()
    fatalities, injuries = 0, 0
    m = re.search(r'(\d+)\s+(?:people?|persons?)\s+(?:were\s+)?killed', t)
    if m: fatalities = int(m.group(1))
    elif re.search(r'\b(?:killed|died|dead|fatal|fatality)\b', t): fatalities = 1
    m = re.search(r'(\d+)\s+(?:people?|persons?)\s+(?:were\s+)?(?:injured|hurt|hospitalized)', t)
    if m: injuries = int(m.group(1))
    elif re.search(r'\b(?:injured|hurt|hospitalized)\b', t): injuries = 1
    return {"fatalities": fatalities, "injuries": injuries,
            "property_damage_only": fatalities == 0 and injuries == 0}

# ── Name Extraction ───────────────────────────────────────────────────────────

NO_NAME_RE = re.compile(r'\bno\s*name\s*given\b', re.I)

NAME_PATTERNS = [
    # "John Smith, 45, arrested/charged/cited"
    r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}),\s*\d+,?\s*(?:was\s+)?(?:arrested|charged|cited|identified)',
    # "John Smith charged/arrested/cited/faces"
    r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s+(?:was\s+)?(?:charged|arrested|cited|faces\s+charges)',
    # "arrested/charged/cited John Smith"  
    r'(?:arrested|charged|cited)[,:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})',
    # "driver/trucker John Smith"
    r'(?:driver|trucker|operator)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*(?:,|was|has)',
    # "identified as John Smith"
    r'identified\s+as\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})',
    # "John Smith, a truck driver"
    r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}),\s+a\s+(?:truck|semi|commercial|cdl)',
]

SKIP_WORDS = {
    "police", "officer", "troop", "highway", "according", "officials",
    "tuesday", "monday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december", "national", "federal",
    "state", "county", "district", "department", "sheriff", "trooper",
}

def extract_name(text, fault):
    if NO_NAME_RE.search(text):
        return "No Name Given"
    if fault == "NO_FAULT_STATED":
        return None
    for pattern in NAME_PATTERNS:
        m = re.search(pattern, text)
        if m:
            name = m.group(1).strip()
            if len(name) > 4 and name.split()[0].lower() not in SKIP_WORDS:
                return name
    return None

# ── Driver Origin Detection ───────────────────────────────────────────────────

INDIA_SURNAMES = {"singh","patel","sharma","kumar","yadav","gupta","verma","dhaliwal","grewal","gill","sandhu","sidhu","brar","sohi","mann","virk","chahal","bajwa","randhawa","sohal","cheema","dhillon","atwal","bains","nagra","sekhon","toor","hayer","khatkar","malhi","pannu","rai","sahota","thind","uppal"}
PAKISTAN_SURNAMES = {"khan","malik","chaudhry","chaudry","mirza","butt","awan","qureshi","sheikh","siddiqui","ahmed","baig","rajput","hashmi","abbasi","niazi","bhatti","javed","iqbal"}
MIDDLE_EAST_SURNAMES = {"al-rashid","al-hassan","alrashid","alhassan","alhussein","hussein","hassan","rahimi","ahmadi","karimi","sultani","mohammadi","haidari","nazari","noori","wardak","demir","yilmaz","kaya","celik","arslan","ozturk","khalil","mansour","nassar","saleh","hamdan","farooq"}
EASTERN_EU_SURNAMES = {"kovalenko","shevchenko","bondarenko","kovalchuk","tkachenko","melnyk","petrenko","savchenko","kravchenko","lysenko","popescu","ionescu","gheorghe","stan","dumitru","constantin","ivanov","petrov","sidorov","volkov","kuznetsov","popov","dzhaksybekov","mamytbekov","toktosunov","umarov","karimov","nazarov","ergashev","yusupov","tursunov","mirzayev","georgiev","dimitrov","stefanov","angelov","nikolov"}
AMERICAN_SURNAMES = {"smith","johnson","williams","jones","brown","davis","miller","wilson","moore","taylor","anderson","thomas","jackson","white","harris","martin","thompson","garcia","martinez","robinson","clark","rodriguez","lewis","lee","walker","hall","allen","young","hernandez","king","wright","lopez","hill","scott","green","adams","baker","gonzalez","nelson","carter","mitchell","perez","roberts","turner","phillips","campbell","parker","evans","edwards","collins","stewart","sanchez","morris","rogers","reed","cook","morgan","bell","murphy","bailey","rivera","cooper","richardson","cox","howard","ward","torres","peterson","gray","ramirez","james","watson","brooks","kelly","sanders","price","bennett","wood","barnes","ross","henderson","coleman","jenkins","perry","powell","long","patterson","hughes","flores","washington","butler","simmons","foster","gonzales","bryant","alexander","russell","griffin","diaz","hayes","myers","ford","hamilton","graham","sullivan","wallace","woods","cole","west","jordan","owens","reynolds","fisher","ellis","harrison","gibson","mcdonald","cruz","marshall","ortiz","gomez","murray","freeman","wells","webb","simpson","stevens","tucker","porter","hunter","hicks","crawford","henry","boyd","mason","morales","kennedy","warren","dixon","ramos","reyes","burns","gordon","shaw","holmes","rice","robertson","hunt","black","daniels","palmer","mills","nichols","grant","knight","ferguson","rose","stone","hawkins","dunn","perkins","hudson","spencer","gardner","stephens","payne","pierce","berry","matthews","arnold","wagner","willis","ray","watkins","olson","carroll","duncan","snyder","hart","cunningham","bradley","lane","andrews","ruiz","harper","fox","riley","armstrong","carpenter","weaver","greene","lawrence","elliott","chavez","sims","austin","peters","kelley","franklin","lawson","fields","gutierrez","ryan","schmidt","carr","vasquez","castillo","wheeler","chapman","oliver","montgomery","larson","carlson","hoffman","little","owen","obrien","oconnor","walsh","byrne","gallagher","oneil","mcdonough","mckenzie","mcallister","mcbride","mccoy","mccormick","mccullough","mcdaniel","mcfarland","mcgee","mcguire","mckay","mclaughlin","mcleod","mcmahon","mcmillan","mcneil"}

ALL_FOREIGN = INDIA_SURNAMES | PAKISTAN_SURNAMES | MIDDLE_EAST_SURNAMES | EASTERN_EU_SURNAMES

FOREIGN_CONFIRMED = [
    "non-domiciled cdl","non domiciled","foreign national","illegal alien",
    "illegal immigrant","undocumented","deported","immigration hold",
    "no valid cdl","improper cdl","work permit","visa overstay",
    "kyrgyzstan","eritrea","fmcsa non-domiciled",
]

def get_region(s):
    if s in INDIA_SURNAMES:     return "Indian/Punjabi-origin"
    if s in PAKISTAN_SURNAMES:  return "Pakistani-origin"
    if s in MIDDLE_EAST_SURNAMES: return "Middle Eastern-origin"
    if s in EASTERN_EU_SURNAMES: return "Eastern European-origin"
    return "foreign-origin"

def detect_origin(text, driver_name):
    t = text.lower()

    # Confirmed — explicit in source
    hits = [p for p in FOREIGN_CONFIRMED if p in t]
    if hits:
        return "confirmed", True, False, f"Source documents: {', '.join(hits[:3])}"

    # Probable — No Name Given
    if driver_name and NO_NAME_RE.search(driver_name):
        return "probable", True, False, '"No Name Given" — CA DMV documented practice for foreign/undocumented drivers'

    # Possible — foreign-origin surname
    if driver_name:
        nl = driver_name.lower()
        for s in ALL_FOREIGN:
            if re.search(r'\b' + re.escape(s) + r'\b', nl):
                return "possible", True, False, f'Surname "{s.title()}" is a {get_region(s)} name — verify against source'

    # American-origin surname
    if driver_name:
        nl = driver_name.lower()
        for s in AMERICAN_SURNAMES:
            if re.search(r'\b' + re.escape(s) + r'\b', nl):
                return "american", False, True, f'Surname "{s.title()}" is an American-origin name — verify against source'

    return None, False, False, ""

# ── Article Fetcher ───────────────────────────────────────────────────────────

def fetch_article(url):
    """Fetch real article text. Skip search URLs and Google News redirects."""
    if not url:
        return ""
    if "search?" in url or "news.google.com/rss/articles" in url:
        return ""
    try:
        r = requests.get(url, timeout=12, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["nav","footer","script","style","aside","header","iframe"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)[:8000]
    except Exception:
        pass
    return ""

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Backfill News Records ===")

    # Load all by_year files
    year_files = sorted(BY_YEAR.glob("*.json"))
    if not year_files:
        log.error("No by_year/ files found. Run split_data.py first.")
        return

    all_by_year = {}
    total = 0
    for yf in year_files:
        data = json.loads(yf.read_text())
        all_by_year[yf] = data
        total += len(data)
    log.info(f"Loaded {total} incidents from {len(year_files)} year files")

    news_count = 0
    updated = 0
    fetch_ok = 0
    fault_fixed = 0
    named = 0
    flagged = 0

    for yf, incidents in all_by_year.items():
        year_updated = False

        for inc in incidents:
            if inc.get("_source") == "FARS_SEED":
                continue

            news_count += 1
            title = inc.get("description", "")

            # Try to fetch real article text
            src = (inc.get("sources") or [""])[0]
            article_text = fetch_article(src)
            if article_text:
                fetch_ok += 1

            # Use article text if available, fall back to title
            full_text = f"{title} {article_text}" if article_text else title

            # Re-classify fault
            new_fault = classify_fault(full_text)
            if new_fault != inc.get("fault"):
                inc["fault"] = new_fault
                fault_fixed += 1

            # Re-extract severity if missing
            if not inc.get("severity") or inc["severity"].get("fatalities") == 0:
                sev = extract_severity(full_text)
                if sev["fatalities"] > 0 or sev["injuries"] > 0:
                    inc["severity"] = sev

            # Extract driver name
            if not inc.get("at_fault_driver"):
                name = extract_name(full_text, new_fault)
                if name:
                    inc["at_fault_driver"] = name
                    named += 1

            driver = inc.get("at_fault_driver")

            # Driver origin flags
            level, foreign_flag, american_flag, note = detect_origin(full_text, driver)
            inc["foreign_driver_flag"]      = foreign_flag
            inc["foreign_driver_confirmed"] = level == "confirmed"
            inc["foreign_driver_probable"]  = level == "probable"
            inc["foreign_driver_possible"]  = level == "possible"
            inc["american_driver_flag"]     = american_flag
            inc["driver_origin_note"]       = note
            inc["foreign_driver_note"]      = note if foreign_flag else ""

            if foreign_flag or american_flag:
                flagged += 1

            year_updated = True
            updated += 1

            if updated % 100 == 0:
                log.info(f"  Processed {updated}/{news_count} news records | "
                         f"fetched:{fetch_ok} fault_fixed:{fault_fixed} named:{named} flagged:{flagged}")
                # Checkpoint — save current year file
                yf.write_text(json.dumps(incidents, indent=2))

            time.sleep(0.15)

        if year_updated:
            yf.write_text(json.dumps(incidents, indent=2))
            log.info(f"Saved {yf.name}")

    log.info(f"\n=== BACKFILL COMPLETE ===")
    log.info(f"News records processed: {news_count}")
    log.info(f"Articles fetched:       {fetch_ok}")
    log.info(f"Fault reclassified:     {fault_fixed}")
    log.info(f"Names extracted:        {named}")
    log.info(f"Origin flags set:       {flagged}")
    log.info(f"\nRun split_data.py to rebuild index.json")

if __name__ == "__main__":
    main()
