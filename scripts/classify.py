#!/usr/bin/env python3
"""
classify.py - stdlib-only helpers shared by scraper.py and merge_pending.py:
state extraction, conservative fault classification, and dedupe keys.

Google News RSS links resolve to a Google interstitial page, so the fetched
"article" text usually contains no crash details. Always classify on the
headline plus any real article text, never on the interstitial alone.
"""
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
BY_YEAR = DATA_DIR / "by_year"

STATE_NAMES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}
CODES = set(STATE_NAMES.values())

# AP-style abbreviations used in datelines ("SPRINGFIELD, Ill. (AP)")
AP_ABBR = {
    "Ala.": "AL", "Ariz.": "AZ", "Ark.": "AR", "Calif.": "CA", "Colo.": "CO", "Conn.": "CT",
    "Del.": "DE", "Fla.": "FL", "Ga.": "GA", "Ill.": "IL", "Ind.": "IN", "Kan.": "KS",
    "Ky.": "KY", "La.": "LA", "Md.": "MD", "Mass.": "MA", "Mich.": "MI", "Minn.": "MN",
    "Miss.": "MS", "Mo.": "MO", "Mont.": "MT", "Neb.": "NE", "Nev.": "NV", "N.H.": "NH",
    "N.J.": "NJ", "N.M.": "NM", "N.Y.": "NY", "N.C.": "NC", "N.D.": "ND", "Okla.": "OK",
    "Ore.": "OR", "Pa.": "PA", "R.I.": "RI", "S.C.": "SC", "S.D.": "SD", "Tenn.": "TN",
    "Vt.": "VT", "Va.": "VA", "Wash.": "WA", "W.Va.": "WV", "Wis.": "WI", "Wyo.": "WY",
}

# Unambiguous large cities / well-known places that headlines use without a state
CITIES = {
    "Los Angeles": "CA", "San Francisco": "CA", "San Diego": "CA", "Sacramento": "CA",
    "Fresno": "CA", "Bakersfield": "CA", "Oakland": "CA", "San Bernardino": "CA",
    "Houston": "TX", "Dallas": "TX", "San Antonio": "TX", "El Paso": "TX", "Fort Worth": "TX",
    "Chicago": "IL", "Phoenix": "AZ", "Tucson": "AZ", "Philadelphia": "PA", "Pittsburgh": "PA",
    "Jacksonville": "FL", "Miami": "FL", "Tampa": "FL", "Orlando": "FL", "Florida Turnpike": "FL",
    "Indianapolis": "IN", "Detroit": "MI", "Milwaukee": "WI", "Minneapolis": "MN",
    "Denver": "CO", "Las Vegas": "NV", "Albuquerque": "NM", "Oklahoma City": "OK",
    "Nashville": "TN", "Memphis": "TN", "Atlanta": "GA", "Charlotte": "NC", "Baltimore": "MD",
    "Boston": "MA", "Seattle": "WA", "Spokane": "WA", "Portland, Ore": "OR", "Salt Lake City": "UT",
    "Boise": "ID", "Omaha": "NE", "Des Moines": "IA", "Louisville": "KY", "New Orleans": "LA",
    "Cleveland, Ohio": "OH", "Columbus, Ohio": "OH", "Cincinnati": "OH", "Brooklyn": "NY",
    "Bronx": "NY", "Manhattan": "NY", "Long Island": "NY", "Queens": "NY",
}

_name_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, STATE_NAMES), key=len, reverse=True)) + r")\b")
_ap_re = re.compile(r"(?<![A-Za-z.])(" + "|".join(sorted(map(re.escape, AP_ABBR), key=len, reverse=True)) + r")(?![A-Za-z])")
_city_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, CITIES), key=len, reverse=True)) + r")\b")
_postal_re = re.compile(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s([A-Z]{2})\b")
_route_re = re.compile(r"\b([A-Z]{2})-\d+\b")
# Things that look like a state but are not a location
_not_place = re.compile(r"Washington (?:Post|Examiner|Times|Commanders|D\.?C\.?)|West Virginia University|"
                        r"Georgia (?:Tech|Bulldogs)|Indiana Jones|New York Times|New York Post|Texas Roadhouse")


def extract_state(text):
    """Earliest location mention wins. Returns a 2-letter code or None."""
    if not text:
        return None
    t = _not_place.sub(" ", text)
    hits = []
    for m in _name_re.finditer(t):
        st = STATE_NAMES[m.group(1)]
        # "New York" alone is usually the city; still NY.
        hits.append((m.start(), st))
    for m in _ap_re.finditer(t):
        hits.append((m.start(), AP_ABBR[m.group(1)]))
    for m in _city_re.finditer(t):
        hits.append((m.start(), CITIES[m.group(1)]))
    for m in _postal_re.finditer(t):
        if m.group(1) in CODES:
            hits.append((m.start(1), m.group(1)))
    for m in _route_re.finditer(t):
        if m.group(1) in CODES and m.group(1) not in ("US", "SR"):
            hits.append((m.start(), m.group(1)))
    return min(hits)[1] if hits else None


AT_FAULT_PHRASES = [
    "driver at fault", "at fault", "at-fault", "cited for", "was cited", "charged with",
    "charged in", "charged after", "faces charges", "arrested for", "arrested after",
    "arrested in", "cited after", "accused of dui", "accused of", "indicted", "convicted",
    "sentenced", "pleaded guilty", "pleads guilty", "found guilty", "accused of causing",
    "blamed for", "caused the crash", "caused the accident", "causing the crash",
    "caused a crash", "causes fatal", "caused fatal", "vehicular homicide",
    "vehicular manslaughter", "manslaughter", "homicide by vehicle", "crossed center",
    "crossed the center line", "crossed the centerline", "crossed the median",
    "crossed into oncoming", "ran red light", "ran a red light", "ran a stop sign",
    "failed to yield", "failed to stop", "fell asleep", "fatigued", "impaired",
    "under the influence", "dui", "dwi", "owi", "drunk", "intoxicated", "speeding",
    "excessive speed", "improper lane change", "following too closely", "overloaded",
    "unsecured load", "distracted", "texting while driving", "wrong way", "wrong-way",
    "wrong side", "illegal u-turn", "u-turn", "no cdl", "unlicensed", "suspended license",
    "revoked license", "failed cdl test",
]

NOT_AT_FAULT_PHRASES = [
    "not at fault", "not charged", "no charges", "other driver caused", "other vehicle crossed",
    "other driver ran", "other driver failed", "car crossed", "pickup crossed",
    "black ice", "ice on road", "icy road", "icy conditions", "road conditions caused",
    "weather caused", "struck by oncoming", "hit by oncoming", "tire blowout",
    "mechanical failure", "brake failure", "debris in road", "animal in road",
    "acquitted", "cleared of",
]


def _count(phrases, t):
    return sum(1 for p in phrases if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", t))


TRUCK_DRIVER = re.compile(
    r"\b(?<!pickup )(?:truck ?driver|trucker|semi(?:-truck)? driver|tractor[- ]trailer driver|big[- ]rig driver|"
    r"18-wheeler driver|bus driver|cdl (?:holder|driver)|commercial driver|driver of the (?:semi|truck|"
    r"tractor[- ]trailer|big rig|18-wheeler|bus)|(?:semi|truck|tractor-trailer|big rig) (?:driver|operator))\b")


def classify_fault(text):
    """Conservative fault for the COMMERCIAL driver.
    AT_FAULT needs an at-fault cue AND an explicit truck/bus-driver subject and no
    exculpatory cue; otherwise NO_FAULT_STATED (e.g. 'car that ran red light hits semi'
    is not attributed to the trucker)."""
    t = (text or "").lower()
    at = _count(AT_FAULT_PHRASES, t)
    not_ = _count(NOT_AT_FAULT_PHRASES, t)
    if not_ >= 1 and not_ >= at:
        return "NOT_AT_FAULT"
    if at >= 1 and TRUCK_DRIVER.search(t):
        return "AT_FAULT"
    return "NO_FAULT_STATED"


def norm_desc(s):
    """Headline without the trailing ' - Outlet' and punctuation, for dedupe."""
    s = (s or "").rsplit(" - ", 1)[0].lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def norm_url(u):
    return (u or "").strip().rstrip("/").lower()


def dedupe_keys(inc):
    keys = set()
    d = norm_desc(inc.get("description"))
    if len(d) >= 20:
        keys.add("d:" + d)
    for u in inc.get("sources") or []:
        keys.add("u:" + norm_url(u))
    return keys


def save_by_year(incidents):
    """Write incidents back to by_year/<year>.json (same format as before)."""
    from collections import defaultdict
    years = defaultdict(list)
    for inc in incidents:
        years[(inc.get("date") or "0000")[:4]].append(inc)
    for year, incs in years.items():
        incs.sort(key=lambda x: x.get("date", ""), reverse=True)
        (BY_YEAR / f"{year}.json").write_text(json.dumps(incs, indent=2))


def build_incidents_json(path=None):
    """Optional local convenience: rebuild data/incidents.json (untracked) from by_year/."""
    path = path or DATA_DIR / "incidents.json"
    Path(path).write_text(json.dumps(load_by_year()))
    return path


def load_by_year():
    """All published incidents (by_year/ is the master source the site reads)."""
    out = []
    for yf in sorted(BY_YEAR.glob("*.json")):
        out.extend(json.loads(yf.read_text()))
    return out
