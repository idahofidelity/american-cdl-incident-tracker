# American CDL Incident Tracker

**Published by [Idaho Fidelity](https://idahofidelity.com)**

National database of commercial vehicle (CDL-required) incidents across the United States, 2000–present. Built for accountability, pattern identification, and public awareness.

🔗 **Live site:** `https://idahofidelity.github.io/american-cdl-incident-tracker`

---

## What This Tracks

- All incidents involving CDL-required vehicles (GVWR 26,001 lbs+)
- National coverage, state-filterable
- 2000 to present
- Fault classification: At Fault / Not At Fault / Not Stated — **facts only, no inference**
- Foreign driver flag — **documented in source only, never inferred**
- Cost: stated (reported) + estimated (FHWA cost model, labeled separately)
- Company pattern analysis with per-capita rates (incidents per 100 CDL drivers)
- Interactive map with clustering and highway hotspot identification

## Data Sources

| Source | Use |
|---|---|
| NHTSA FARS API | Fatal incident baseline, 2000–present |
| FMCSA Motor Carrier Census (Socrata) | Company driver/CDL counts for per-capita |
| FMCSA SAFER API | Company profiles, safety ratings |
| FMCSA SMS Monthly Crash Download | Carrier crash history |
| NTSB Investigation Reports | Official fault determinations |
| News RSS (50+ feeds) | Driver names, costs, foreign driver documentation |

Full methodology: [`pages/about.html`](pages/about.html)

## Fault Classification

- **AT_FAULT** — Police report, citation, NTSB finding, or court record names the CDL driver
- **NOT_AT_FAULT** — Official record establishes other cause; no CDL driver contributing factor documented
- **NO_FAULT_STATED** — Insufficient documentation (default until resolved)

No fault classification is made from inference, article tone, or assumption.

## Foreign Driver Flag

Set **only** when a source explicitly documents: non-domiciled CDL, foreign national identification, or immigration status as a documented factor. Source text is quoted in the record note field.

## Cost Methodology

Two separate figures per incident:
- **Stated** — dollar amount reported in source material
- **Estimated** — FHWA Comprehensive Crash Cost model (2024 dollars):
  - Fatal: $12,000,000 per fatality
  - Injury crash: $600,000
  - Property damage only: $12,000

## Project Structure

```
american-cdl-incident-tracker/
├── index.html                  # Map view (main page)
├── pages/
│   ├── incidents.html          # Sortable/filterable incident table
│   ├── companies.html          # Company pattern analysis
│   └── about.html              # Data sources & methodology
├── css/style.css               # Stylesheet
├── js/map.js                   # Map logic, filters, panel
├── data/
│   ├── incidents.json          # Live incident database
│   ├── companies.json          # Carrier records with per-capita rates
│   └── pending_review.json     # Scraper output awaiting review
├── scripts/
│   ├── scraper.py              # Scraper (FARS + news RSS + FMCSA enrichment)
│   └── merge_pending.py        # Merges approved incidents to live DB
└── .github/workflows/
    ├── scrape.yml              # Runs 1st & 15th, opens PR for review
    ├── merge.yml               # Auto-merges to incidents.json on PR merge
    └── deploy.yml              # Deploys to GitHub Pages on push to main
```

## Automated Update Workflow

1. GitHub Actions runs scraper on 1st and 15th of each month
2. New incidents written to `data/pending_review.json`
3. A Pull Request is opened with a summary of each new incident (fault, severity, cost, source)
4. Editor reviews PR — merge to approve all, or edit `pending_review.json` to remove specific entries before merging
5. On PR merge, `merge.yml` runs `merge_pending.py` — moves approved incidents to `incidents.json`
6. `deploy.yml` redeploys GitHub Pages

**No incident is ever published without human review.**

## Setup (first time)

```bash
# Install Python deps
pip install requests beautifulsoup4 feedparser

# Run scraper manually
python scripts/scraper.py

# Preview results
cat data/pending_review.json | python -m json.tool | head -100

# Merge if satisfied
python scripts/merge_pending.py
```

## GitHub Actions Setup

Enable these settings in your repo:
- **Settings → Actions → General → Workflow permissions:** Read and write permissions
- **Settings → Pages → Source:** GitHub Actions
- Add label `incident-review` to your repo (Settings → Labels)

## Attribution

Every incident record includes source URLs. Aggregate data attributed to:
- Federal Motor Carrier Safety Administration (FMCSA)
- National Highway Traffic Safety Administration (NHTSA)
- National Transportation Safety Board (NTSB)
- National Safety Council (NSC)
- Federal Highway Administration (FHWA) cost model

## License

Data is compiled from public sources and original research. Published for public accountability purposes.
