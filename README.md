# Trade Inventory Automation

Merch Strategy & Enablement — Inventory Health Dashboard + Weekly Trade Automation

Tracks **6 supply-chain nodes** (On-Order → Yard → DC → In-Transit → Store → FC) with live BigQuery data, auto-generates the weekly talk track PDF, and updates the Trade Slides PPTX — all from a single dashboard.

---

## What It Does

| Component | Description |
|---|---|
| **Dashboard** (`app.py`) | Dash app — node cards, trend charts, SBU/dept filters, AI insights, PPTX download |
| **Talk Track PDF** (`generate_talk_track_pdf.py`) | Auto-generates 2-page trade narrative with dept callouts, WoW/YoY, cross-node signals |
| **PPTX Updater** (`update_pptx.py`) | Patches Trade Slides deck with live BQ numbers (text replacement) |
| **Weekly Refresh** (`weekly_refresh.bat`) | One-click: regenerates PDF + PPTX + restarts dashboard |

---

## Quick Start (Local)

### 1. Clone

```bash
git clone https://gecgithub01.walmart.com/R0C0JUG/Trade_Inventory_Automation.git
cd Trade_Inventory_Automation
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up credentials

```bash
cp .env.example .env
# Edit .env — set BQ_PROJECT_ID if needed (default: wmt-execution-intel-prod)
```

BigQuery auth (pick one):
- **Local dev**: `gcloud auth application-default login`
- **Service account**: set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json` in `.env`

### 4. Run the dashboard

```bash
python app.py
# open http://127.0.0.1:8050
```

Or double-click **`weekly_refresh.bat`** to regenerate all outputs and open the dashboard.

---

## Weekly Workflow

```
weekly_refresh.bat
  └─ 1. python generate_talk_track_pdf.py  → talk_track_WK{N}.pdf
  └─ 2. python update_pptx.py              → Trade Slides - Inventory WK{N}.pptx
  └─ 3. python app.py                      → http://127.0.0.1:8050
```

**Download Trade Slides from dashboard**: open http://127.0.0.1:8050 in Chrome/Edge → click **⬇ Download Trade Slides (PPTX)**. Uses `pptx_template.pptx` in project root (save your master template there).

---

## Project Structure

```
├── app.py                      # Dash dashboard + Flask /download-pptx route
├── generate_talk_track_pdf.py  # Weekly talk track PDF generator
├── update_pptx.py              # Standalone PPTX number updater
├── business_rules.py           # Thresholds, SBU flags, OO watch logic
├── data/
│   ├── bq.py                   # BQ connector (ADC auth, sample fallback)
│   └── queries.py              # All SQL (OO snapshot, INV snapshot, trend, L13W)
├── ai/
│   └── insights.py             # AI narrative generator (Insights section)
├── weekly_refresh.bat          # One-click weekly refresh
├── restart_dashboard.bat       # Kill + restart dashboard only
├── PPTX_SLIDE1_SPEC.md         # Field definitions, shape names, gap analysis
├── requirements.txt
├── .env.example
└── README.md
```

---

## Data Sources

| Table | Format | LY Offset | Used For |
|---|---|---|---|
| `R0C0JUG_WMUS_HIST_COMBINED` | `WM_YR_WK_NBR` = YYYYWW | -100 | All inventory nodes (Yard, DC, IT, Store, FC) |
| `R0C0JUG_WMUS_HIST_ONORDER` | `wm_week` = YYWWW (MABD week) | -100 | On-Order (NON-DSD, grouped by MABD arrival week) |

**Project**: `wmt-execution-intel-prod.WM_AD_HOC`

### Key business rules
- **DC** = DC_OH + DC_LABELED + DC_UNLABELED + DC_RESERVED (4-component)
- **Salesfloor** = Store OH − Backroom (not ON_FLOOR_UNITS directly)
- **On-Order WoW** = MABD WK{N} vs MABD WK{N-1} (not pipeline-velocity comparison)
- **Backroom fallback**: if WK{N} backroom = 0 (pipeline pending), uses WK{N-1} as proxy — logged at startup
- **L13W avg**: 13-week rolling average of MABD-week ordered units, NON-DSD, excl. OTHER SBU

---

## Posit Connect Deployment

### First-time setup

```bash
pip install rsconnect-python

# Add your Posit Connect server (one-time)
rsconnect add \
  --server https://posit.walmart.com \
  --api-key <YOUR_API_KEY> \
  --name walmart-posit
```

### Deploy

```bash
rsconnect deploy dash \
  --server walmart-posit \
  --entrypoint app:server \
  --title "Inventory Health Dashboard" \
  .
```

### Environment variables on Posit

Set these in the Posit Connect app settings → Vars:
```
BQ_PROJECT_ID=wmt-execution-intel-prod
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

Upload the service account JSON as a bundled file or via the Posit Connect secret store.

---

## PPTX Slide 1 Shape Map

Full field definitions, BQ column names, and shape TextBox IDs are documented in [`PPTX_SLIDE1_SPEC.md`](PPTX_SLIDE1_SPEC.md).

Key shapes updated on download:
- **50+ shapes** — units, vs LY %, vs LW %, cube ft³ + vs LY for all 6 nodes
- **TextBox 25** — L13W avg (1,366M/wk +1.3% YoY)
- **Rounded Rectangle 10** — Insights bullets (auto-generated from live data)

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Dashboard won't start | Run `weekly_refresh.bat` — kills stale Python processes and restarts |
| Download button no response | Open dashboard in **Chrome/Edge** (not VS Code browser) |
| Backroom shows 0 M | Pipeline pending — fallback to PW auto-applied, check startup log |
| On Yard shows 0.0 M | Correct — On Yard < 500K units rounds to 0.0 M |
| OO WoW direction differs from WMS | Different methodology — ours is MABD-week vs MABD-week; WMS is order-velocity |
| `UnicodeEncodeError` on startup | Set `PYTHONUTF8=1` in environment or use `weekly_refresh.bat` |

---

## Maintainer

**r0c0jug** — Merch Strategy & Enablement, Inventory Insights  
Repo: https://gecgithub01.walmart.com/R0C0JUG/Trade_Inventory_Automation
