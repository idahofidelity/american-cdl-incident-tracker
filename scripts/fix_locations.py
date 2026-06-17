#!/usr/bin/env python3
"""
fix_locations.py — Fixes UNKNOWN state on news records by:
1. Extracting state from headline text (city/county/state names)
2. Inferring state from news outlet domain name
3. Filling in missing highway/county fields

Run from project root:
  py scripts/fix_locations.py

Then run:
  py scripts/geocode_news.py
  py scripts/split_data.py
  git add -A && git commit -m "Fix locations" && git push
"""

import json
import re
import logging
from pathlib import Path
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
BY_YEAR  = DATA_DIR / "by_year"

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

OUTLET_STATE = {
    "ocregister":"CA","latimes":"CA","sfgate":"CA","mercurynews":"CA","sacbee":"CA",
    "fresnobee":"CA","dailynews":"CA","pressdemocrat":"CA","sandiegouniontribune":"CA",
    "gothamist":"NY","nypost":"NY","nytimes":"NY","nydailynews":"NY","newsday":"NY",
    "timesunion":"NY","syracuse":"NY","democratandchronicle":"NY",
    "theledger":"FL","miamiherald":"FL","orlandosentinel":"FL","tampabay":"FL",
    "sun-sentinel":"FL","tallahassee":"FL","naplesnews":"FL","palmbeachpost":"FL",
    "heraldtribune":"FL","gainesville":"FL","ocala":"FL",
    "dallasnews":"TX","houstonchronicle":"TX","statesman":"TX","expressnews":"TX",
    "lubbockonline":"TX","star-telegram":"TX","chron":"TX","mysanantonio":"TX",
    "khou":"TX","kxan":"TX","kvue":"TX","wfaa":"TX","ksat":"TX",
    "kboi":"ID","ktvb":"ID","kivitv":"ID","postregister":"ID","idahostatesman":"ID",
    "magicvalley":"ID","cdasentinel":"ID","lmtribune":"ID",
    "seattletimes":"WA","spokesman":"WA","nonstoplocal":"WA","king5":"WA",
    "komo":"WA","kiro":"WA","thenewstribune":"WA","peninsuladailynews":"WA",
    "oregonlive":"OR","kgw":"OR","oregonian":"OR","kptv":"OR","registerguard":"OR",
    "kval":"OR","kezi":"OR","mailtribune":"OR",
    "denverpost":"CO","coloradoan":"CO","gazette":"CO","thedenverchannel":"CO",
    "9news":"CO","kdvr":"CO","kusa":"CO",
    "azcentral":"AZ","tucson":"AZ","kpho":"AZ","abc15":"AZ","12news":"AZ",
    "reviewjournal":"NV","rgj":"NV","ktnv":"NV","8newsnow":"NV",
    "deseret":"UT","sltrib":"UT","kutv":"UT","ksl":"UT","fox13now":"UT",
    "missoulian":"MT","greatfallstribune":"MT","billingsgazette":"MT","kpax":"MT",
    "trib":"WY","casperstartribune":"WY",
    "abqjournal":"NM","kob":"NM","krqe":"NM","koat":"NM",
    "ctpost":"CT","courant":"CT","nhregister":"CT","wtnh":"CT","wfsb":"CT",
    "philly":"PA","post-gazette":"PA","pennlive":"PA","mcall":"PA","wgal":"PA",
    "cleveland":"OH","dispatch":"OH","daytondailynews":"OH","wkyc":"OH","fox8":"OH",
    "freep":"MI","mlive":"MI","detroitnews":"MI","woodtv":"MI","wzzm13":"MI",
    "chicagotribune":"IL","suntimes":"IL","wgntv":"IL","abc7chicago":"IL",
    "indystar":"IN","wsbt":"IN","wrtv":"IN","wthr":"IN",
    "stltoday":"MO","kansascity":"MO","ksdk":"MO","kmov":"MO",
    "tennessean":"TN","timesfreepress":"TN","wsmv":"TN","newschannel5":"TN",
    "ajc":"GA","wsbtv":"GA","fox5atlanta":"GA","11alive":"GA",
    "newsobserver":"NC","charlotteobserver":"NC","wral":"NC","wcnc":"NC",
    "roanoke":"VA","pilotonline":"VA","wtvr":"VA","wric":"VA",
    "courier-journal":"KY","heraldleader":"KY","wkyt":"KY","wdrb":"KY",
    "al":"AL","bhamnow":"AL","wsfa":"AL","whnt":"AL","wbrc":"AL",
    "clarionledger":"MS","wapt":"MS","wlbt":"MS",
    "nola":"LA","theadvocate":"LA","wdsu":"LA","wafb":"LA",
    "arkansasonline":"AR","thv11":"AR","katv":"AR",
    "startribune":"MN","postbulletin":"MN","kare11":"MN","wcco":"MN",
    "jsonline":"WI","greenbaypressgazette":"WI","wisn":"WI","wtmj4":"WI",
    "desmoinesregister":"IA","thegazette":"IA","kcci":"IA","whotv":"IA",
    "wichitaeagle":"KS","kwch":"KS","ksnw":"KS",
    "omaha":"NE","journalstar":"NE","ketv":"NE","wowt":"NE",
    "argusleader":"SD","rapidcityjournal":"SD","keloland":"SD",
    "bismarcktribune":"ND","inforum":"ND","kfyr":"ND",
    "nj":"NJ","app":"NJ","northjersey":"NJ",
    "baltimoresun":"MD","wbal":"MD","wmar":"MD",
    "bostonglobe":"MA","masslive":"MA","wcvb":"MA","wbz":"MA",
    "pressherald":"ME","bangordailynews":"ME","wmtw":"ME",
    "unionleader":"NH","concordmonitor":"NH","wmur":"NH",
    "burlingtonfreepress":"VT","vtdigger":"VT",
    "wvgazettemail":"WV","wowktv":"WV","wsaz":"WV",
    "thestate":"SC","postandcourier":"SC","wyff4":"SC","wistv":"SC",
    "oklahoman":"OK","tulsaworld":"OK","kfor":"OK","newson6":"OK",
    "adn":"AK","ktuu":"AK","ktvf":"AK",
    "staradvertiser":"HI","khon2":"HI","kitv":"HI",
}

CITY_STATE = {
    "los angeles":"CA","san francisco":"CA","san diego":"CA","sacramento":"CA",
    "fresno":"CA","orange county":"CA","riverside":"CA","anaheim":"CA",
    "new york":"NY","manhattan":"NY","brooklyn":"NY","queens":"NY","bronx":"NY",
    "buffalo":"NY","rochester":"NY","albany":"NY","long island":"NY",
    "chicago":"IL","springfield":"IL","rockford":"IL",
    "houston":"TX","dallas":"TX","san antonio":"TX","austin":"TX","fort worth":"TX",
    "el paso":"TX","lubbock":"TX","amarillo":"TX","waco":"TX",
    "phoenix":"AZ","tucson":"AZ","mesa":"AZ","scottsdale":"AZ","tempe":"AZ",
    "philadelphia":"PA","pittsburgh":"PA","allentown":"PA","erie":"PA","harrisburg":"PA",
    "miami":"FL","orlando":"FL","tampa":"FL","jacksonville":"FL","fort lauderdale":"FL",
    "tallahassee":"FL","gainesville":"FL","pensacola":"FL","sarasota":"FL",
    "atlanta":"GA","savannah":"GA","macon":"GA","columbus":"GA",
    "seattle":"WA","spokane":"WA","tacoma":"WA","bellevue":"WA","pasco":"WA",
    "portland":"OR","eugene":"OR","salem":"OR","bend":"OR","medford":"OR",
    "denver":"CO","colorado springs":"CO","aurora":"CO","fort collins":"CO","pueblo":"CO",
    "wheat ridge":"CO",
    "las vegas":"NV","reno":"NV","henderson":"NV","carson city":"NV",
    "albuquerque":"NM","santa fe":"NM","las cruces":"NM",
    "boise":"ID","nampa":"ID","meridian":"ID","idaho falls":"ID","pocatello":"ID",
    "twin falls":"ID","coeur d'alene":"ID","lewiston":"ID","gowen road":"ID",
    "salt lake city":"UT","provo":"UT","ogden":"UT",
    "minneapolis":"MN","st. paul":"MN","duluth":"MN",
    "milwaukee":"WI","madison":"WI","green bay":"WI",
    "detroit":"MI","grand rapids":"MI","lansing":"MI","ann arbor":"MI","flint":"MI",
    "cleveland":"OH","columbus":"OH","cincinnati":"OH","toledo":"OH","akron":"OH",
    "indianapolis":"IN","fort wayne":"IN","evansville":"IN","south bend":"IN",
    "louisville":"KY","lexington":"KY","bowling green":"KY",
    "nashville":"TN","memphis":"TN","knoxville":"TN","chattanooga":"TN",
    "birmingham":"AL","montgomery":"AL","huntsville":"AL","mobile":"AL",
    "jackson":"MS","gulfport":"MS","biloxi":"MS",
    "new orleans":"LA","baton rouge":"LA","shreveport":"LA","lafayette":"LA",
    "little rock":"AR","fort smith":"AR","fayetteville":"AR",
    "oklahoma city":"OK","tulsa":"OK","norman":"OK",
    "kansas city":"MO","st. louis":"MO","springfield":"MO",
    "omaha":"NE","lincoln":"NE","grand island":"NE",
    "sioux falls":"SD","rapid city":"SD",
    "fargo":"ND","bismarck":"ND","grand forks":"ND",
    "des moines":"IA","cedar rapids":"IA","davenport":"IA",
    "wichita":"KS","topeka":"KS","overland park":"KS",
    "charlotte":"NC","raleigh":"NC","greensboro":"NC","durham":"NC","winston-salem":"NC",
    "columbia":"SC","charleston":"SC","greenville":"SC",
    "richmond":"VA","virginia beach":"VA","norfolk":"VA","chesapeake":"VA",
    "baltimore":"MD","annapolis":"MD",
    "boston":"MA","worcester":"MA","lowell":"MA",
    "charleston":"WV","huntington":"WV","morgantown":"WV",
    "bridgeport":"CT","new haven":"CT","hartford":"CT","stamford":"CT",
    "newark":"NJ","jersey city":"NJ","trenton":"NJ",
    "anchorage":"AK","fairbanks":"AK","juneau":"AK",
    "honolulu":"HI","hilo":"HI",
    "billings":"MT","missoula":"MT","great falls":"MT","bozeman":"MT","butte":"MT",
    "cheyenne":"WY","casper":"WY","laramie":"WY",
    "portland":"ME","bangor":"ME","lewiston":"ME",
    "manchester":"NH","concord":"NH","nashua":"NH",
    "burlington":"VT","montpelier":"VT",
    "providence":"RI","cranston":"RI","warwick":"RI",
    "dover":"DE","wilmington":"DE",
}

AGENCY_STATE = {
    "isp:": "ID", "chp:": "CA", "osp:": "OR", "wsp:": "WA",
    "msp:": "MT", "mshp:": "MO", "nhp:": "NV", "nsp:": "NE",
    "ndp:": "ND", "wyp:": "WY", "ksp:": "KS",
}


def extract_state_from_text(text):
    for name, abbr in STATE_NAMES.items():
        if re.search(r'\b' + name + r'\b', text, re.I):
            return abbr
    tl = text.lower()
    for city, state in CITY_STATE.items():
        if city in tl and state:
            return state
    m = re.search(r'\bin\s+([A-Z]{2})\b', text)
    if m and m.group(1) in STATE_NAMES.values():
        return m.group(1)
    return None


def state_from_outlet(source_url):
    if not source_url:
        return None
    try:
        domain = urlparse(source_url).netloc.lower().replace("www.", "")
        base = domain.split(".")[0]
        state = OUTLET_STATE.get(base)
        if state:
            return state
        for key, st in OUTLET_STATE.items():
            if key in base and st:
                return st
    except Exception:
        pass
    return None


def state_from_agency(title):
    tl = title.lower()
    for prefix, state in AGENCY_STATE.items():
        if tl.startswith(prefix) or f" {prefix}" in tl:
            return state if state else None
    return None


def extract_highway(text):
    for p in [r'Interstate\s+(\d+[A-Z]?)', r'\bI-(\d+[A-Z]?)\b',
              r'US(?:\s+|-)?(?:Highway\s+)?(\d+)\b',
              r'(?:State\s+)?(?:Highway|Route|Hwy)\s+(\d+)']:
        m = re.search(p, text, re.I)
        if m:
            if "Interstate" in p or "I-" in p: return f"I-{m.group(1)}"
            if "US" in p: return f"US-{m.group(1)}"
            return f"Hwy {m.group(1)}"
    return None


def extract_county(text):
    m = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+County', text)
    if m:
        return m.group(1) + " County"
    return None


def main():
    log.info("=== Fix Locations on News Records ===")
    year_files = sorted(BY_YEAR.glob("*.json"))
    if not year_files:
        log.error("No by_year/ files. Run split_data.py first.")
        return

    total = fixed = 0

    for yf in year_files:
        incidents = json.loads(yf.read_text())
        year_fixed = 0

        for inc in incidents:
            if inc.get("_source") == "FARS_SEED":
                continue
            if inc.get("state") and inc["state"] != "UNKNOWN":
                continue

            total += 1
            title = inc.get("description", "")
            src   = (inc.get("sources") or [""])[0]

            state = (
                extract_state_from_text(title) or
                state_from_agency(title) or
                state_from_outlet(src)
            )

            if state:
                inc["state"] = state
                year_fixed += 1
                fixed += 1

            if not inc.get("highway"):
                hw = extract_highway(title)
                if hw:
                    inc["highway"] = hw

            if not inc.get("county"):
                co = extract_county(title)
                if co:
                    inc["county"] = co

        yf.write_text(json.dumps(incidents, indent=2))
        if year_fixed:
            log.info(f"  {yf.name}: fixed {year_fixed} locations")

    log.info(f"\n=== DONE ===")
    log.info(f"Unknown state records processed: {total}")
    log.info(f"Fixed: {fixed} ({round(fixed/total*100) if total else 0}%)")
    log.info(f"Remaining unknown: {total - fixed}")
    log.info(f"\nNext: py scripts/geocode_news.py")

if __name__ == "__main__":
    main()
