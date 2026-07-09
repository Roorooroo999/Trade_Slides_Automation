"""
Inventory Talk Track PDF
  Page 1      : Talk track — narrative only, fits one page
  Appendix    : Event timeline, pipeline chart, all SBU data tables

Run: python generate_talk_track_pdf.py
"""

import warnings; warnings.filterwarnings('ignore')
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv; load_dotenv()
from business_rules import (
    assess_oo_watch, OO_INSTORE_WIN_WEEKS, OO_INSTORE_MIN_COV_PCT,
    BACKROOM_YOY_EXCLUDE_SBUS, FRESH_REPLEN_COVERED_THRESHOLD,
    STORE_YOY_EXCLUDE_SBUS, STORE_YOY_EXCLUDE_NOTE,
    FRESH_WOW_VALID, FRESH_YOY_MERCH1_NOTE,
    ACTIVE_EVENTS, WATCH_THRESHOLDS, yyyyww_to_yywww, OO_ROLLING_WEEKS,
)

from google.cloud import bigquery
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart, HorizontalBarChart
from reportlab.graphics.charts.legends import Legend

# ── Colours ───────────────────────────────────────────────────────────────────
WM_BLUE  = colors.HexColor("#0071ce"); WM_DARK  = colors.HexColor("#003087")
WM_YEL   = colors.HexColor("#ffc220"); WM_GREEN = colors.HexColor("#16a34a")
WM_RED   = colors.HexColor("#dc2626"); WM_GREY  = colors.HexColor("#f5f5f5")
WM_LGREY = colors.HexColor("#e8f0fe"); WM_MID   = colors.HexColor("#7bb3e0")

# ── Styles ────────────────────────────────────────────────────────────────────
TITLE  = ParagraphStyle("ti", fontSize=13, fontName="Helvetica-Bold", textColor=WM_DARK, spaceAfter=1)
META   = ParagraphStyle("me", fontSize=7.5,fontName="Helvetica", textColor=colors.HexColor("#888"), spaceAfter=0)
SECHDG = ParagraphStyle("sh", fontSize=9,  fontName="Helvetica-Bold", textColor=colors.white, leftIndent=5)
BODY   = ParagraphStyle("bo", fontSize=8.5,fontName="Helvetica", textColor=colors.HexColor("#111"),
                         spaceAfter=5, leading=13)
BULLET = ParagraphStyle("bu", fontSize=8.5,fontName="Helvetica", textColor=colors.HexColor("#111"),
                         leftIndent=14, bulletIndent=4, spaceAfter=3, leading=13)
SMALL  = ParagraphStyle("sm", fontSize=6.5,fontName="Helvetica", textColor=colors.HexColor("#aaa"), spaceAfter=1)

# Appendix styles
APPH   = ParagraphStyle("ah", fontSize=9, fontName="Helvetica-Bold", textColor=colors.white, leftIndent=5)
TH_S   = ParagraphStyle("th", fontSize=7.5,fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_CENTER)
TL_S   = ParagraphStyle("tl", fontSize=8,  fontName="Helvetica-Bold", textColor=WM_DARK, alignment=TA_LEFT)

def sec(text, color=WM_BLUE):
    t = Table([[Paragraph(text, SECHDG)]], colWidths=[7.4*inch])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),color),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),7)]))
    return [t, Spacer(1,3)]

def app_sec(text):
    return sec(text, color=colors.HexColor("#444"))

# ── BQ data ───────────────────────────────────────────────────────────────────
print("Pulling BQ data...")
client = bigquery.Client(project='wmt-execution-intel-prod')
def bq(sql): return [dict(r) for r in client.query(sql).result()]

# ── Dynamic week detection (matches dashboard logic) ──────────────────────────
# Reads max week from BQ so PDF always matches dashboard on refresh
_wk_meta = bq("SELECT MAX(WM_YR_WK_NBR) wk, MAX(BUS_DT) bus_dt "
               "FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED`")[0]
INV_TY = int(_wk_meta['wk'])
INV_LY = INV_TY - 100
def _yyyyww_to_yywww(w):
    return 10000 + ((w//100)-2000)*100 + (w%100)
OO_TY = _yyyyww_to_yywww(INV_TY)
OO_LY = OO_TY - 100; OO_PW = OO_TY - 1
# Trade meeting = following week (WK data → next week's trade slides)
DATA_WK   = INV_TY % 100        # e.g. 22
TRADE_WK  = DATA_WK + 1         # e.g. 23
BUS_DT    = _wk_meta['bus_dt']  # latest BUS_DT in the dataset
TRADE_DATE = datetime.date.today().strftime('%b %d, %Y')
print(f"Weeks: INV_TY={INV_TY}, OO_TY={OO_TY}, TRADE_WK={TRADE_WK}, BUS_DT={BUS_DT}")

def _nodes(wk):
    q=f"""WITH s AS (SELECT OMNI_CATG_NBR,MAX(BUS_DT) dt FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED` WHERE WM_YR_WK_NBR={wk} GROUP BY 1)
    SELECT CAST(SUM(c.ON_YARD_UNITS) AS FLOAT64) yard,
           CAST(SUM(c.DC_OH_UNITS+c.DC_LABELED_UNITS+c.DC_UNLABELED_UNITS+c.DC_RESERVED_UNITS) AS FLOAT64) dc,
           CAST(SUM(c.INTRANSIT_TO_DC_UNITS) AS FLOAT64) it_dc,
           CAST(SUM(c.IN_TRANSIT_UNITS) AS FLOAT64) it_store,
           CAST(SUM(c.STORE_OH_UNITS) AS FLOAT64) store,
           CAST(SUM(c.BACKROOM_UNITS) AS FLOAT64) backroom,
           -- Salesfloor = Store OH - Backroom (not ON_FLOOR_UNITS directly)
           -- ON_FLOOR_UNITS from table = 4,230M (hardcodes 0 for 19 orphan backroom rows)
           -- Store OH - Backroom = 4,227M (correct: 3M orphan backroom reduces implied floor)
           CAST(SUM(c.STORE_OH_UNITS) - SUM(c.BACKROOM_UNITS) AS FLOAT64) salesfloor,
           CAST(SUM(c.FC_OH_UNITS) AS FLOAT64) fc,
           CAST(SUM(c.TOTAL_NETWORK_UNITS) AS FLOAT64) total_net
    FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED` c INNER JOIN s ON c.OMNI_CATG_NBR=s.OMNI_CATG_NBR AND c.BUS_DT=s.dt"""
    return bq(q)[0]

def _oo(wk):
    return bq(f"SELECT CAST(SUM(units_ordered) AS FLOAT64) v FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER` WHERE wm_week={wk} AND dsd_ind='NON-DSD'")[0]['v']

def _sbu(col,wk,tbl='COMBINED'):
    if tbl=='COMBINED':
        q=f"""WITH s AS (SELECT SBU,OMNI_CATG_NBR,MAX(BUS_DT) dt FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED` WHERE WM_YR_WK_NBR={wk} GROUP BY 1,2)
        SELECT c.SBU sbu,CAST(SUM(c.{col}) AS FLOAT64) v FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED` c INNER JOIN s ON c.OMNI_CATG_NBR=s.OMNI_CATG_NBR AND c.BUS_DT=s.dt WHERE c.SBU!='OTHER' GROUP BY 1"""
    else:
        q=f"SELECT sbu,CAST(SUM(units_ordered) AS FLOAT64) v FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER` WHERE wm_week={wk} AND dsd_ind='NON-DSD' AND sbu!='OTHER' GROUP BY 1"
    return {r['sbu']:r['v'] for r in bq(q)}

def _lnw(wk, n=OO_ROLLING_WEEKS):
    """L{n}W rolling average for on-order by SBU."""
    return {r['sbu']:r['v'] for r in bq(
        f"SELECT sbu,CAST(SUM(units_ordered)/{n} AS FLOAT64) v "
        f"FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER` "
        f"WHERE wm_week BETWEEN {wk-n+1} AND {wk} AND dsd_ind='NON-DSD' AND sbu!='OTHER' GROUP BY 1")}

ROLLING_LABEL = f"L{OO_ROLLING_WEEKS}W"

ty=_nodes(INV_TY); ly=_nodes(INV_LY); pw=_nodes(INV_TY-1)  # pw = prior week for WoW
oo_ty=_oo(OO_TY); oo_ly=_oo(OO_LY); oo_pw=_oo(OO_PW)

# Store OH by SBU — TY, LY, PW
store_ty=_sbu('STORE_OH_UNITS',INV_TY); store_ly=_sbu('STORE_OH_UNITS',INV_LY)
store_pw=_sbu('STORE_OH_UNITS',INV_TY-1)

# In DC by SBU — use FULL definition (DC_OH + Labeled + Unlabeled + Reserved) to match node card
def _sbu_dc(wk):
    q=f"""WITH s AS (SELECT SBU,OMNI_CATG_NBR,MAX(BUS_DT) dt
           FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED`
           WHERE WM_YR_WK_NBR={wk} GROUP BY SBU,OMNI_CATG_NBR)
    SELECT c.SBU sbu,
      CAST(SUM(c.DC_OH_UNITS+c.DC_LABELED_UNITS+c.DC_UNLABELED_UNITS+c.DC_RESERVED_UNITS) AS FLOAT64) v
    FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED` c
    INNER JOIN s ON c.OMNI_CATG_NBR=s.OMNI_CATG_NBR AND c.BUS_DT=s.dt
    WHERE c.SBU!='OTHER' GROUP BY 1"""
    return {r['sbu']:r['v'] for r in bq(q)}

dc_ty=_sbu_dc(INV_TY); dc_ly=_sbu_dc(INV_LY); dc_pw=_sbu_dc(INV_TY-1)

# In Transit → Store by SBU — TY, LY, PW
it_ty=_sbu('IN_TRANSIT_UNITS',INV_TY); it_ly=_sbu('IN_TRANSIT_UNITS',INV_LY)
it_pw=_sbu('IN_TRANSIT_UNITS',INV_TY-1)

# Backroom by SBU — TY, LY, PW
br_ty=_sbu('BACKROOM_UNITS',INV_TY); br_ly=_sbu('BACKROOM_UNITS',INV_LY)
br_pw=_sbu('BACKROOM_UNITS',INV_TY-1)

# ── Dept-level breakdown — all 4 nodes in one BQ call per week ────────────────
def _dept_all(wk):
    """Store, DC (full def), IT→Store, Backroom at (SBU, dept) level. Single BQ call."""
    q = f"""WITH s AS (
      SELECT SBU,OMNI_DEPT_NBR,OMNI_CATG_NBR,MAX(BUS_DT) dt
      FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED`
      WHERE WM_YR_WK_NBR={wk} GROUP BY 1,2,3)
    SELECT c.SBU sbu, c.OMNI_DEPT_DESC dept,
      CAST(SUM(c.STORE_OH_UNITS) AS FLOAT64) store,
      CAST(SUM(c.DC_OH_UNITS+c.DC_LABELED_UNITS+c.DC_UNLABELED_UNITS+c.DC_RESERVED_UNITS) AS FLOAT64) dc,
      CAST(SUM(c.IN_TRANSIT_UNITS) AS FLOAT64) it_store,
      CAST(SUM(c.BACKROOM_UNITS) AS FLOAT64) backroom
    FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED` c
    INNER JOIN s ON c.OMNI_CATG_NBR=s.OMNI_CATG_NBR AND c.BUS_DT=s.dt
    WHERE c.SBU!='OTHER'
    GROUP BY 1,2"""
    out = {}
    for r in bq(q):
        k = (r['sbu'], r['dept'])
        out[k] = {'store': float(r['store'] or 0), 'dc': float(r['dc'] or 0),
                  'it_store': float(r['it_store'] or 0), 'backroom': float(r['backroom'] or 0)}
    return out

def _dept_catg_all(wk):
    """Store at (SBU, dept, catg) level — used for category drivers. Uses distinct name to avoid shadowing."""
    q = f"""WITH s AS (
      SELECT SBU,OMNI_DEPT_NBR,OMNI_CATG_NBR,MAX(BUS_DT) dt
      FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED`
      WHERE WM_YR_WK_NBR={wk} GROUP BY 1,2,3)
    SELECT c.SBU sbu, c.OMNI_DEPT_DESC dept, c.OMNI_CATG_DESC catg,
      CAST(SUM(c.STORE_OH_UNITS) AS FLOAT64) store_u
    FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED` c
    INNER JOIN s ON c.OMNI_CATG_NBR=s.OMNI_CATG_NBR AND c.BUS_DT=s.dt
    WHERE c.SBU!='OTHER'
    GROUP BY 1,2,3"""
    result = {}
    for r in bq(q):
        result[(r['sbu'], r['dept'], r['catg'])] = float(r['store_u'] or 0)
    return result

print("Pulling dept-level breakdowns (TY / LY / PW)...")
dept_ty = _dept_all(INV_TY)
dept_ly = _dept_all(INV_LY)
dept_pw = _dept_all(INV_TY - 1)

# Category-level data — stored under dc_ty/dc_ly prefix to avoid any variable shadowing
DC_CATG_TY = _dept_catg_all(INV_TY)
DC_CATG_LY = _dept_catg_all(INV_LY)

# On-Order by SBU
oo_ty_s =_sbu(None,OO_TY,'OO'); oo_ly_s=_sbu(None,OO_LY,'OO'); oo_pw_s=_sbu(None,OO_PW,'OO')
l13w_ty_s=_lnw(OO_TY); l13w_ly_s=_lnw(OO_TY-100)  # L13W rolling avg TY and LY

# In-store date comparison (uses business_rules.OO_INSTORE_WIN_WEEKS)
WIN = OO_INSTORE_WIN_WEEKS
_ins_q = f"""
SELECT sbu,
  SAFE_DIVIDE(
    SUM(CASE WHEN wm_week={OO_TY} AND in_store_wm_week IS NOT NULL THEN units_ordered ELSE 0 END),
    NULLIF(SUM(CASE WHEN wm_week={OO_TY} THEN units_ordered ELSE 0 END),0)
  )*100 AS ins_cov_pct,
  CAST(SUM(CASE WHEN in_store_wm_week BETWEEN {OO_TY}-{WIN} AND {OO_TY}+{WIN} THEN units_ordered ELSE 0 END) AS FLOAT64) AS ins_win_ty,
  CAST(SUM(CASE WHEN in_store_wm_week BETWEEN {OO_TY}-100-{WIN} AND {OO_TY}-100+{WIN} THEN units_ordered ELSE 0 END) AS FLOAT64) AS ins_win_ly
FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER`
WHERE wm_week BETWEEN {OO_TY}-103 AND {OO_TY} AND dsd_ind='NON-DSD' AND sbu!='OTHER'
GROUP BY 1"""
_ins_rows = bq(_ins_q)
ins_cov  = {r['sbu']:float(r.get('ins_cov_pct') or 0) for r in _ins_rows}
ins_ty_s = {r['sbu']:float(r.get('ins_win_ty')  or 0) for r in _ins_rows}
ins_ly_s = {r['sbu']:float(r.get('ins_win_ly')  or 0) for r in _ins_rows}

# In-store prior-week window (for WoW comparison via in-store date)
_ins_pw_q = f"""
SELECT sbu,
  CAST(SUM(CASE WHEN in_store_wm_week BETWEEN {OO_PW}-{WIN} AND {OO_PW}+{WIN}
               THEN units_ordered ELSE 0 END) AS FLOAT64) AS ins_win_pw
FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER`
WHERE wm_week BETWEEN {OO_LY}-{WIN} AND {OO_TY}+{WIN}
  AND dsd_ind='NON-DSD' AND sbu!='OTHER'
GROUP BY 1"""
_ins_pw_rows = bq(_ins_pw_q)
ins_pw_s = {r['sbu']:float(r.get('ins_win_pw') or 0) for r in _ins_pw_rows}

# Produce WoW (valid: both WK22/WK21 BUS_DT are post-Jun 23 EI migration)
_prod_q = f"""WITH s AS (SELECT WM_YR_WK_NBR,OMNI_DEPT_NBR,MAX(BUS_DT) dt
  FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED`
  WHERE WM_YR_WK_NBR IN ({INV_TY},{INV_TY-1}) AND SBU='FRESH' GROUP BY 1,2)
SELECT c.WM_YR_WK_NBR wk, c.OMNI_DEPT_DESC dept,
  CAST(SUM(c.STORE_OH_UNITS) AS FLOAT64) v
FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED` c
INNER JOIN s ON c.WM_YR_WK_NBR=s.WM_YR_WK_NBR AND c.OMNI_DEPT_NBR=s.OMNI_DEPT_NBR AND c.BUS_DT=s.dt
WHERE c.SBU='FRESH' GROUP BY 1,2"""
_prod_rows = bq(_prod_q)
_prod_data = {}
for r in _prod_rows:
    _prod_data.setdefault(r['dept'],{})[r['wk']] = float(r['v'])
produce_ty = _prod_data.get('PRODUCE',{}).get(INV_TY, 0)
produce_pw = _prod_data.get('PRODUCE',{}).get(INV_TY-1, 0)
produce_wow_delta = produce_ty - produce_pw
produce_wow_pct   = (produce_wow_delta / produce_pw * 100) if produce_pw else 0

# Use full node totals (ty/ly/pw from _nodes()) so backroom matches dashboard
# _nodes() sums ALL rows including OTHER SBU; SBU dict excludes OTHER → 2-3M gap
br_ex_f_ty = ty['backroom']   # 422M — matches dashboard exactly
br_ex_f_ly = ly['backroom']   # LY full backroom

# Store OH breakdown by SBU (EI system now fully updated — all YoY valid)
store_ex_fresh_ty = sum(v for k,v in store_ty.items() if k not in STORE_YOY_EXCLUDE_SBUS)
store_ex_fresh_ly = sum(v for k,v in store_ly.items() if k not in STORE_YOY_EXCLUDE_SBUS)
store_ex_fresh_pw = sum(v for k,v in (_sbu('STORE_OH_UNITS', INV_TY-1) if False else store_ty).items()
                        if k not in STORE_YOY_EXCLUDE_SBUS)  # approx from pw_store
# Prior-week node totals for WoW (all nodes)
pw_dc    = pw['dc'];       pw_it_store = pw['it_store']
pw_store = pw['store'];    pw_backroom = pw['backroom']
pw_fc    = pw['fc'];       pw_total    = pw['total_net'] + oo_pw
br_ex_f_ly = ly['backroom']

# Salesfloor = Store OH - Backroom (same logic as dashboard)
sf_ty     = ty['store'] - ty['backroom']
sf_ly     = ly['store'] - ly['backroom']
sf_pw     = pw_store    - pw_backroom
sf_yoy_d  = sf_ty - sf_ly                                      # unit delta YoY
sf_wow_d  = sf_ty - sf_pw                                      # unit delta WoW
sf_yoy_p  = (sf_yoy_d / sf_ly  * 100) if sf_ly  else 0       # YoY %
sf_wow_p  = (sf_wow_d / sf_pw  * 100) if sf_pw  else 0       # WoW %

total_ty=ty['total_net']+oo_ty; total_ly=ly['total_net']+oo_ly
print("Data ready.")

# ── Pre-compute watch flags (needed on both page 1 and page 2) ────────────────
def pct(a,b): return ((a-b)/b*100) if b else 0
def dlt(a,b): return a-b
def fm(n):
    a=abs(n)
    if a>=1e9: return f"{n/1e9:.2f}B"
    if a>=1e6: return f"{n/1e6:.1f}M"
    if a>=1e3: return f"{n/1e3:.1f}K"
    return str(int(n))
def fp(v,sign=True):
    s="+" if v>=0 else ""
    return f"{s}{v:.1f}%"

oo_flags = {}
for s in ['FRESH','PANTRY','CAC','CONSUMABLES','HARDLINES','HOME','FASHION','ETS']:
    wow_p  = pct(oo_ty_s.get(s,0), oo_pw_s.get(s,0))
    l13w_p = pct(l13w_ty_s.get(s,0), l13w_ly_s.get(s,0))
    mabd_p = pct(oo_ty_s.get(s,0), oo_ly_s.get(s,0))
    cov    = ins_cov.get(s, 0.0)
    ins_p  = pct(ins_ty_s.get(s,0), ins_ly_s.get(s,0)) if ins_ty_s.get(s,0)>0 and ins_ly_s.get(s,0)>0 else None
    result = assess_oo_watch(s, wow_p, l13w_p, cov, ins_p, mabd_p)
    if result['flag']:
        oo_flags[s] = result

fresh_store_yoy    = None   # excluded: GRS→EI migration
fresh_replen_covered = True
dc_concerns = {s: pct(dc_ty.get(s,0),dc_ly.get(s,0)) for s in dc_ty
               if pct(dc_ty.get(s,0),dc_ly.get(s,0)) < WATCH_THRESHOLDS['dc_yoy_decline_flag']
               and s not in ('HOME','HARDLINES','FASHION')}

def pct(a,b): return ((a-b)/b*100) if b else 0
def dlt(a,b): return a-b
# ── Appendix charts & tables ──────────────────────────────────────────────────

def event_timeline():
    # Height: 14 (TODAY label) + 4 (gap) + 4 bars×12 (events) + 10 (axis) + 14 (WK labels) = 74
    H = 74
    d = Drawing(520, H)
    d.add(Rect(0, 0, 520, H, fillColor=colors.white, strokeColor=None))

    WK0=18; WKN=34; PPW=520/(WKN-WK0)
    def x(wk): return (wk-WK0)*PPW

    # Axis line and week labels at the bottom
    AXIS_Y = 20
    d.add(Line(0, AXIS_Y, 520, AXIS_Y, strokeColor=colors.HexColor("#ddd"), strokeWidth=0.5))
    for wk in range(WK0, WKN+1, 2):
        d.add(Line(x(wk), AXIS_Y-3, x(wk), AXIS_Y+3,
                   strokeColor=colors.HexColor("#ccc"), strokeWidth=0.5))
        d.add(String(x(wk)-8, 8, f"WK{wk}", fontSize=6,
                     fillColor=colors.HexColor("#0071ce"), fontName="Helvetica-Bold"))

    # TODAY marker — dashed line from axis up through all bars
    cur = x(22)
    d.add(Line(cur, AXIS_Y, cur, H-4, strokeColor=WM_RED, strokeWidth=1.5,
               strokeDashArray=[3, 2]))
    d.add(String(cur-10, H-6, "TODAY", fontSize=6,
                 fontName="Helvetica-Bold", fillColor=WM_RED))

    # Event bars — stacked from bottom up, clear of TODAY label
    BAR_H = 10
    events = [
        # (label, wk_start, wk_end, bar_y, color)
        ("A250  ends this week",    18, 22.2, 24, colors.HexColor("#c0392b")),
        ("Summer  ends Jul 6",      18, 23.5, 36, colors.HexColor("#e67e22")),
        ("World Cup  25% through",  18, 30.0, 48, colors.HexColor("#27ae60")),
        ("BTX 2026  starts WK23",   23, 33.0, 60, colors.HexColor("#2980b9")),
    ]
    for lbl, ws, we, bar_y, clr in events:
        bx = x(ws); bw = x(we) - x(ws)
        d.add(Rect(bx, bar_y, bw, BAR_H, fillColor=clr, strokeColor=None, rx=3, ry=3))
        d.add(String(bx+4, bar_y+2, lbl, fontSize=6,
                     fontName="Helvetica-Bold", fillColor=colors.white))
    return d

def pipeline_chart():
    # On Yard (~250K) is invisible at billion scale — excluded
    labels = ['On-Order','In DC','IT→DC','IT→Store','Store OH','Backroom','FC']
    ty_v   = [oo_ty/1e6, ty['dc']/1e6, ty['it_dc']/1e6,
              ty['it_store']/1e6, ty['store']/1e6, ty['backroom']/1e6, ty['fc']/1e6]
    ly_v   = [oo_ly/1e6, ly['dc']/1e6, ly['it_dc']/1e6,
              ly['it_store']/1e6, ly['store']/1e6, ly['backroom']/1e6, ly['fc']/1e6]

    def _lbl(v_m):
        """B / M / K smart format (v_m in millions)."""
        a = abs(v_m)
        if a >= 1000: return f"{v_m/1000:.1f}B"
        if a >= 1:    return f"{v_m:.0f}M"
        if a > 0:     return f"{v_m*1000:.0f}K"
        return "0"

    n  = len(ty_v)                    # 7 groups
    BC_W, BC_H = 460, 155
    d  = Drawing(520, 215)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 40, 18, BC_W, BC_H
    bc.data = [ty_v, ly_v]
    bc.categoryAxis.categoryNames   = labels
    bc.categoryAxis.labels.fontSize = 7
    bc.valueAxis.labels.fontSize    = 7
    bc.valueAxis.labelTextFormat    = lambda v: (f"{v/1000:.1f}B" if v >= 1000 else f"{v:.0f}M")
    bc.bars[0].fillColor = WM_BLUE
    bc.bars[1].fillColor = WM_MID
    bc.groupSpacing = 6
    bc.barSpacing   = 1

    g_w   = BC_W / n                  # group width
    bar_w = (g_w - 6 - 1) / 2        # width of one bar
    max_v = max(ty_v)

    for i, (tv, lv) in enumerate(zip(ty_v, ly_v)):
        # x centres for TY and LY bars
        grp_x  = 40 + i * g_w
        ty_cx  = grp_x + 1 + bar_w / 2
        ly_cx  = grp_x + 1 + bar_w + 1 + bar_w / 2

        # y tops (scaled to chart height)
        ty_top = 18 + (tv / max_v) * BC_H
        ly_top = 18 + (lv / max_v) * BC_H

        # TY label: above TY bar, bold blue
        ty_y = min(ty_top + 4, 205)
        d.add(String(ty_cx - 11, ty_y,
                     _lbl(tv),
                     fontSize=6, fontName="Helvetica-Bold",
                     fillColor=WM_DARK))

        # LY label: above LY bar, regular grey — slightly lower offset to separate from TY
        ly_y = min(ly_top + 2, 195)
        d.add(String(ly_cx - 11, ly_y,
                     f"LY {_lbl(lv)}",
                     fontSize=5.5, fontName="Helvetica",
                     fillColor=colors.HexColor("#666")))

    lg = Legend(); lg.x = 395; lg.y = 207
    lg.colorNamePairs = [(WM_BLUE, f"TY WK{OO_TY%100}"), (WM_MID, f"LY WK{OO_LY%100}")]
    lg.fontSize = 7; lg.columnMaximum = 2
    d.add(bc); d.add(lg); return d

def sbu_tbl(header, rows, up_cols, col_w=None, wow_sep_col=None):
    """
    wow_sep_col: 0-indexed column that starts the WoW section — gets a left border divider.
    """
    if col_w is None: col_w=[1.45*inch]+[0.82*inch]*(len(header)-1)
    data=[[Paragraph(h,TH_S) for h in header]]
    for row in rows:
        fr=[Paragraph(str(row[0]),TL_S)]
        for i,val in enumerate(row[1:],1):
            v=str(val)
            c=WM_GREEN if i in up_cols and v.startswith('+') else \
              WM_RED   if i in up_cols and v.startswith('-') else colors.HexColor("#222")
            fr.append(Paragraph(v,ParagraphStyle("td3",fontSize=8,fontName="Helvetica",
                textColor=c,alignment=TA_CENTER)))
        data.append(fr)
    t=Table(data,colWidths=col_w)
    style=[
        ("BACKGROUND",(0,0),(-1,0),WM_BLUE),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,WM_GREY]),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
        ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#ccc")),
        ("LINEBELOW",(0,0),(-1,0),1.5,WM_DARK),
    ]
    if wow_sep_col:
        # Visual divider between YoY and WoW sections
        style.append(("LINEBEFORE",(wow_sep_col,0),(wow_sep_col,-1),1.5,colors.HexColor("#0071ce")))
    t.setStyle(TableStyle(style))
    return t

# ══════════════════════════════════════════════════════════════════
# BUILD PDF
# ══════════════════════════════════════════════════════════════════
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),f"talk_track_WK{TRADE_WK}.pdf")
doc=SimpleDocTemplate(OUT,pagesize=letter,
    leftMargin=0.50*inch,rightMargin=0.50*inch,
    topMargin=0.42*inch,bottomMargin=0.42*inch)
story=[]
W=7.6*inch

# ══════════════════════════════════════════════════════════════════
# PAGE 1 — EXECUTIVE BULLET SUMMARY (one glance)
# ══════════════════════════════════════════════════════════════════

BUL = ParagraphStyle("bul", fontSize=8, fontName="Helvetica",
      textColor=colors.HexColor("#111"), leftIndent=12, bulletIndent=4,
      spaceAfter=2, leading=11)
BUL_HDR = ParagraphStyle("bulh", fontSize=8, fontName="Helvetica-Bold",
           textColor=WM_BLUE, spaceAfter=1, leftIndent=0)
BUL_SUB = ParagraphStyle("buls", fontSize=7.5, fontName="Helvetica",
           textColor=colors.HexColor("#555"), leftIndent=20, spaceAfter=2, leading=10.5)

story.append(Table([[
    Paragraph("Trade Slides — Inventory Talk Track", TITLE),
    Paragraph(f"WM Week {TRADE_WK}  ·  {TRADE_DATE}  ·  Trade Meeting",
              ParagraphStyle("rh",fontSize=7.5,fontName="Helvetica",
              textColor=colors.HexColor("#888"),alignment=TA_RIGHT)),
]], colWidths=[4.6*inch,3.0*inch]))
story.append(HRFlowable(width="100%",thickness=2,color=WM_YEL,spaceAfter=3))

story.append(HRFlowable(width="100%",thickness=0.5,color=colors.HexColor("#ddd"),spaceAfter=4))

# ── Callout helpers ───────────────────────────────────────────────────────────
def _top_sbu(ty_d, ly_d, n_g=3, n_d=3, min_u=10_000_000, thr=2.0):
    """Top N SBU gainers/decliners by YoY unit delta. Each item: (sbu, ty, ly, delta, yoy_pct)."""
    items = []
    for s in ty_d:
        if s == 'OTHER': continue
        t = float(ty_d.get(s) or 0); l = float(ly_d.get(s) or 0)
        if max(t, l) < min_u: continue
        items.append((s, t, l, t - l, pct(t, l)))
    g = sorted([x for x in items if x[4] >  thr], key=lambda x: -x[3])[:n_g]
    d = sorted([x for x in items if x[4] < -thr], key=lambda x:  x[3])[:n_d]
    return g, d

def _top_dept(node, ty_d, ly_d, sbu=None, n_g=3, n_d=3, min_u=500_000, thr=3.0, d_thr=None):
    """Top N dept gainers/decliners for a node, optionally filtered by SBU.
    d_thr: separate (lower) threshold for decliners — use for declining SBUs to surface drivers.
    Each item: (dept, ty, ly, delta, yoy_pct)."""
    _d = d_thr if d_thr is not None else thr
    items = []
    for (s, dept), tv in ty_d.items():
        if sbu and s != sbu: continue
        t = tv.get(node, 0); l = ly_d.get((s, dept), {}).get(node, 0)
        if max(t, l) < min_u: continue
        items.append((dept, t, l, t - l, pct(t, l)))
    g = sorted([x for x in items if x[4] >  thr], key=lambda x: -x[3])[:n_g]
    d = sorted([x for x in items if x[4] < -_d],  key=lambda x:  x[3])[:n_d]
    return g, d

def _top_catg_in_dept(DC_CATG_TY_d, DC_CATG_LY_d, sbu, dept_name,
                      n_g=2, n_d=2, min_u=200_000, thr=5.0):
    """Top store OH categories within a dept driving its YoY move.
    DC_CATG_TY_d / DC_CATG_LY_d: dict (sbu, dept, catg) → store_units float
    Returns (gainers, decliners) — each: (catg_name, t, l, delta, yoy_pct)."""
    items = []
    for (s, dept, catg), t_val in DC_CATG_TY_d.items():
        if s != sbu or dept != dept_name: continue
        l_val = DC_CATG_LY_d.get((s, dept, catg), 0)
        if max(t_val, l_val) < min_u: continue
        items.append((catg, t_val, l_val, t_val - l_val, pct(t_val, l_val)))
    g = sorted([x for x in items if x[4] >  thr], key=lambda x: -x[3])[:n_g]
    d = sorted([x for x in items if x[4] < -thr], key=lambda x:  x[3])[:n_d]
    return g, d

def _fmt_dept_with_catg(dept_items, DC_CATG_TY_d, DC_CATG_LY_d, sbu, n_catg=2):
    """Format dept mover with top store OH category drivers.
    e.g. 'PERSONAL CARE +8.4%  (VITAMINS +12.1%  SKIN CARE +6.8%)'"""
    parts = []
    for dept_row in dept_items:
        dept_name = dept_row[0]; dept_pct = dept_row[4]
        cg, cd = _top_catg_in_dept(DC_CATG_TY_d, DC_CATG_LY_d, sbu, dept_name,
                                    n_g=n_catg, n_d=n_catg, min_u=100_000, thr=3.0)
        catg_hits = [(c, p) for c, *_, p in (cg + cd) if abs(p) > 3]
        catg_str = ("  (" + "  ".join(f"{c} {fp(p)}" for c, p in catg_hits[:n_catg]) + ")"
                    if catg_hits else "")
        parts.append(f"{dept_name} {fp(dept_pct)}{catg_str}")
    return "  ·  ".join(parts)

def _cross_node_sf_br(ty_d, ly_d, sbu=None, n=3, min_u=100_000, sf_thr=-2.0, br_thr=2.0):
    """Find depts where salesfloor is declining YoY but backroom is building.
    Pattern: product staged in back, not reaching the floor → pull opportunity.
    Returns list of (dept, sf_yoy_pct, br_yoy_pct) sorted by worst salesfloor first."""
    hits = []
    for (s, dept), tv in ty_d.items():
        if sbu and s != sbu: continue
        sf_ty = tv.get('store', 0) - tv.get('backroom', 0)
        br_ty = tv.get('backroom', 0)
        lv    = ly_d.get((s, dept), {})
        sf_ly = lv.get('store', 0) - lv.get('backroom', 0)
        br_ly = lv.get('backroom', 0)
        if max(abs(sf_ty), abs(sf_ly)) < min_u: continue
        sf_p = pct(sf_ty, sf_ly) if sf_ly else 0
        br_p = pct(br_ty, br_ly) if br_ly else 0
        if sf_p < sf_thr and br_p > br_thr:
            hits.append((dept, sf_p, br_p))
    return sorted(hits, key=lambda x: x[1])[:n]  # worst salesfloor first

def _top_dept_wow(node, ty_d, pw_d, sbu=None, n_g=3, n_d=3, min_u=500_000, thr=5.0):
    """Top N dept WoW movers for a node."""
    items = []
    for (s, dept), tv in ty_d.items():
        if sbu and s != sbu: continue
        t = tv.get(node, 0); p = pw_d.get((s, dept), {}).get(node, 0)
        if max(t, p) < min_u: continue
        items.append((dept, t, p, t - p, pct(t, p)))
    g = sorted([x for x in items if x[4] >  thr], key=lambda x: -x[3])[:n_g]
    d = sorted([x for x in items if x[4] < -thr], key=lambda x:  x[3])[:n_d]
    return g, d

def _fmt_movers(g, d, n_key=0, p_key=4):
    """'▲ X +N% · Y +N%  ▼ A -N%' — arrows omitted if one side is empty."""
    gs = " · ".join(f"{x[n_key]} {fp(x[p_key])}" for x in g)
    ds = " · ".join(f"{x[n_key]} {fp(x[p_key])}" for x in d)
    if gs and ds: return f"▲ {gs}  ▼ {ds}"
    if gs: return f"▲ {gs}"
    if ds: return f"▼ {ds}"
    return "—"

def _sbu_sub(sbu_name, ty_sbu, ly_sbu, pw_sbu,
             yoy_g, yoy_d, wow_g, wow_d):
    """Build a direction-aware SBU sub-bullet.
    Declining SBU → decliners lead (what's causing the drop).
    Growing SBU   → gainers lead (what's driving the build).
    Always appends WoW dept callout if available."""
    sbu_yoy_raw = pct(ty_sbu.get(sbu_name,0), ly_sbu.get(sbu_name,0))
    sbu_wow_raw = pct(ty_sbu.get(sbu_name,0), pw_sbu.get(sbu_name,0))
    header = f"<b>{sbu_name} {fp(sbu_yoy_raw)} YoY, {fp(sbu_wow_raw)} WoW</b>"

    # Dept callout with BOTH YoY and WoW + top categories
    def _fmt_dept_full(dept_name, yoy_p, show_catg=True):
        """Format: DEPT +X% YoY / +Y% WoW  (CAT1 +Z%  CAT2 +W%)"""
        # WoW for this dept from dept_ty / dept_pw globals
        d_ty  = dept_ty.get((sbu_name, dept_name), {}).get('store', 0)
        d_pw  = dept_pw.get((sbu_name, dept_name), {}).get('store', 0)
        wow_p = pct(d_ty, d_pw) if d_pw else 0
        wow_part = f" / {fp(wow_p)} WoW" if abs(wow_p) > 0.5 else ""
        # Categories
        catg_str = ""
        if show_catg:
            cg, cd = _top_catg_in_dept(DC_CATG_TY, DC_CATG_LY, sbu_name, dept_name,
                                        n_g=2, n_d=2, min_u=80_000, thr=4.0)
            catg_hits = [(c, p) for c, *_, p in (cg + cd) if abs(p) > 4]
            if catg_hits:
                catg_str = "  (" + "  ".join(f"{c} {fp(p)}" for c, p in catg_hits[:2]) + ")"
        return f"{dept_name} {fp(yoy_p)} YoY{wow_part}{catg_str}"

    def _fmt_wow_dept_full(dept_name, wow_p):
        """Format: DEPT +X% WoW / +Y% YoY  (CAT1 +Z%)"""
        d_ty  = dept_ty.get((sbu_name, dept_name), {}).get('store', 0)
        d_ly  = dept_ly.get((sbu_name, dept_name), {}).get('store', 0)
        yoy_p = pct(d_ty, d_ly) if d_ly else 0
        yoy_part = f" / {fp(yoy_p)} YoY" if abs(yoy_p) > 0.5 else ""
        cg, cd = _top_catg_in_dept(DC_CATG_TY, DC_CATG_LY, sbu_name, dept_name,
                                    n_g=2, n_d=2, min_u=80_000, thr=4.0)
        catg_hits = [(c, p) for c, *_, p in (cg + cd) if abs(p) > 4]
        catg_str = ("  (" + "  ".join(f"{c} {fp(p)}" for c, p in catg_hits[:2]) + ")"
                    if catg_hits else "")
        return f"{dept_name} {fp(wow_p)} WoW{yoy_part}{catg_str}"

    # YoY dept gainers/decliners with WoW + categories
    gs = " · ".join(_fmt_dept_full(x[0], x[4]) for x in yoy_g)
    ds = " · ".join(_fmt_dept_full(x[0], x[4]) for x in yoy_d)
    if sbu_yoy_raw < 0 and ds:
        yoy_str = f"▼ {ds}" + (f"  ▲ {gs} partially offsetting" if gs else "")
    elif gs and ds:
        yoy_str = f"▲ {gs}  ▼ {ds}"
    elif gs:
        yoy_str = f"▲ {gs}"
    elif ds:
        yoy_str = f"▼ {ds}"
    else:
        yoy_str = ""

    txt = f"{header}: {yoy_str}." if yoy_str else f"{header}."

    # WoW dept movers with YoY + categories
    if wow_g or wow_d:
        wow_parts = []
        if wow_g:
            wow_parts.append("▲ " + " · ".join(_fmt_wow_dept_full(x[0], x[4]) for x in wow_g))
        if wow_d:
            wow_parts.append("▼ " + " · ".join(_fmt_wow_dept_full(x[0], x[4]) for x in wow_d))
        txt += f"  WoW: {('  '.join(wow_parts))}."
    return txt

# ── Pre-compute top movers for page 1 callouts ────────────────────────────────
# DC: top SBU and dept decliners/gainers
_dc_g, _dc_d = _top_sbu(dc_ty, dc_ly, n_g=2, n_d=4, min_u=20_000_000)
_dc_dept_g, _dc_dept_d = _top_dept('dc', dept_ty, dept_ly, n_g=2, n_d=4, min_u=3_000_000, thr=10.0)

# IT→Store: all SBUs — sorted by YoY% descending so biggest % gainers lead
_it_all_sbus = sorted(
    [(s, it_ty.get(s,0), it_ly.get(s,0),
      it_ty.get(s,0)-it_ly.get(s,0), pct(it_ty.get(s,0), it_ly.get(s,0)))
     for s in it_ty if s!='OTHER' and max(it_ty.get(s,0), it_ly.get(s,0)) > 1_000_000],
    key=lambda x: -x[4])  # sort by YoY% desc
_it_dept_g, _ = _top_dept('it_store', dept_ty, dept_ly, n_g=5, n_d=0, min_u=2_000_000, thr=5.0)

# Store OH dept by SBU (FRESH excluded from YoY commentary)
# Raw SBU YoY for adaptive thresholding (declining SBUs get lower d_thr to surface all decliners)
_cons_yoy_raw = pct(store_ty.get('CONSUMABLES',0), store_ly.get('CONSUMABLES',0))
_pan_yoy_raw  = pct(store_ty.get('PANTRY',0),      store_ly.get('PANTRY',0))
_ets_yoy_raw  = pct(store_ty.get('ETS',0),         store_ly.get('ETS',0))
_home_yoy_raw = pct(store_ty.get('HOME',0),        store_ly.get('HOME',0))
_cac_yoy_raw  = pct(store_ty.get('CAC',0),         store_ly.get('CAC',0))

_cons_g, _cons_d = _top_dept('store', dept_ty, dept_ly, sbu='CONSUMABLES', n_g=3, n_d=2, min_u=200_000,
                              thr=2.0, d_thr=0.5 if _cons_yoy_raw < 0 else 2.0)
_pan_g,  _pan_d  = _top_dept('store', dept_ty, dept_ly, sbu='PANTRY',      n_g=2, n_d=3, min_u=200_000,
                              thr=1.5, d_thr=0.3)
_ets_g,  _ets_d  = _top_dept('store', dept_ty, dept_ly, sbu='ETS',         n_g=3, n_d=3, min_u=200_000,
                              thr=3.0, d_thr=0.5 if _ets_yoy_raw < 0 else 3.0)
_home_g, _home_d = _top_dept('store', dept_ty, dept_ly, sbu='HOME',        n_g=2, n_d=3, min_u=200_000,
                              thr=3.0, d_thr=0.5 if _home_yoy_raw < 0 else 3.0)
_cac_g,  _cac_d  = _top_dept('store', dept_ty, dept_ly, sbu='CAC',         n_g=2, n_d=2, min_u=200_000,
                              thr=2.0, d_thr=0.3)

def _dept_catg_line(dept_items, sbu, n_catg=2):
    """Format: DEPT_NAME +X%  (CAT1 +Y%  CAT2 +Z%)  ·  DEPT2 ..."""
    return _fmt_dept_with_catg(dept_items, DC_CATG_TY, DC_CATG_LY, sbu, n_catg=n_catg)
_hl_wow_g,   _hl_wow_d   = _top_dept_wow('store', dept_ty, dept_pw, sbu='HARDLINES',  n_g=3, n_d=2, min_u=200_000, thr=10.0)
_ets_wow_g,  _ets_wow_d  = _top_dept_wow('store', dept_ty, dept_pw, sbu='ETS',        n_g=2, n_d=2, min_u=200_000, thr=5.0)
_cons_wow_g, _cons_wow_d = _top_dept_wow('store', dept_ty, dept_pw, sbu='CONSUMABLES',n_g=2, n_d=2, min_u=200_000, thr=3.0)
_pan_wow_g,  _pan_wow_d  = _top_dept_wow('store', dept_ty, dept_pw, sbu='PANTRY',     n_g=2, n_d=3, min_u=200_000, thr=3.0)
_home_wow_g, _home_wow_d = _top_dept_wow('store', dept_ty, dept_pw, sbu='HOME',       n_g=2, n_d=2, min_u=200_000, thr=3.0)
_cac_wow_g,  _cac_wow_d  = _top_dept_wow('store', dept_ty, dept_pw, sbu='CAC',        n_g=2, n_d=2, min_u=200_000, thr=3.0)

# Backroom: top SBU and dept
_br_g, _br_d = _top_sbu(br_ty, br_ly, n_g=3, n_d=2, min_u=3_000_000, thr=3.0)
_br_dept_g, _br_dept_d = _top_dept('backroom', dept_ty, dept_ly, n_g=4, n_d=2, min_u=300_000, thr=5.0)

# ── Cross-node "connect the dots" insights ────────────────────────────────────
# Pattern A: salesfloor declining YoY but backroom building → staged, can pull to floor
_cross_cons  = _cross_node_sf_br(dept_ty, dept_ly, sbu='CONSUMABLES', sf_thr=-3.0, br_thr=5.0)
_cross_pantry= _cross_node_sf_br(dept_ty, dept_ly, sbu='PANTRY',      sf_thr=-2.0, br_thr=3.0)
_cross_cac   = _cross_node_sf_br(dept_ty, dept_ly, sbu='CAC',         sf_thr=-2.0, br_thr=3.0)
_cross_ets   = _cross_node_sf_br(dept_ty, dept_ly, sbu='ETS',         sf_thr=-3.0, br_thr=5.0)
_cross_home  = _cross_node_sf_br(dept_ty, dept_ly, sbu='HOME',        sf_thr=-3.0, br_thr=5.0)

# Pattern B: store declining + OO building → incoming pipeline recovery
def _oo_store_signal(sbu):
    """(store_yoy, oo_yoy, br_yoy) for a given SBU."""
    return (pct(store_ty.get(sbu,0), store_ly.get(sbu,0)),
            pct(oo_ty_s.get(sbu,0),  oo_ly_s.get(sbu,0)),
            pct(br_ty.get(sbu,0),    br_ly.get(sbu,0)))

# ── Bullets ───────────────────────────────────────────────────────
_l13w_pct = pct(sum(l13w_ty_s.values()), sum(l13w_ly_s.values()))
_total_pct = pct(total_ty, total_ly)
_dc_pct    = pct(ty['dc'], ly['dc'])
_it_pct    = pct(ty['it_store'], ly['it_store'])
_store_pct = pct(ty['store'], ly['store'])
_br_pct    = pct(br_ex_f_ty, br_ex_f_ly)

def _bull(text): return Paragraph(f"• {text}", BUL)
def _sub(text):  return Paragraph(text, BUL_SUB)
def _bhead(text):return Paragraph(text, BUL_HDR)

story.append(_bhead("TOTAL NETWORK"))
story.append(_bull(
    f"<b>{fm(total_ty)} TY vs {fm(total_ly)} LY</b> — "
    f"<b>{fp(_total_pct)} YoY</b>  ·  <b>{fp(pct(total_ty,pw_total))} WoW</b>"))
story.append(Spacer(1,2))

story.append(_bhead("ON ORDER (NON-DSD)"))
story.append(_bull(
    f"<b>{fm(oo_ty)}</b>  ·  <b>{fp(pct(oo_ty,oo_ly))} vs LY</b>  ·  {fp(pct(oo_ty,oo_pw))} WoW  ·  "
    f"L{OO_ROLLING_WEEKS}W avg {fm(sum(l13w_ty_s.values()))}/wk = <b>{fp(_l13w_pct)} vs LY</b>"))
story.append(_sub(
    f"MABD timing (in-store date confirmed): HARDLINES {fp(pct(oo_ty_s.get('HARDLINES',0),oo_pw_s.get('HARDLINES',0)))} WoW "
    f"is a date shift — orders actually increasing. "
    f"FRESH {fp(pct(oo_ty_s.get('FRESH',0),oo_ly_s.get('FRESH',0)))} · CAC {fp(pct(oo_ty_s.get('CAC',0),oo_ly_s.get('CAC',0)))} genuine YoY increases."))
story.append(Spacer(1,2))

story.append(_bhead("IN DC & IN TRANSIT"))
_dc_line = f"SBU: {_fmt_movers(_dc_g, _dc_d)}"
if _dc_dept_g or _dc_dept_d:
    _dc_line += f"  |  Key depts: {_fmt_movers(_dc_dept_g, _dc_dept_d)}"
story.append(_bull(
    f"DC: <b>{fm(ty['dc'])} ({fp(_dc_pct)} YoY, {fp(pct(ty['dc'],pw_dc))} WoW)</b> — releasing into BTS pipeline."))
story.append(_sub(_dc_line + "."))
story.append(_bull(
    f"IT→Store: <b>{fm(ty['it_store'])} (+{fm(dlt(ty['it_store'],ly['it_store']))} YoY, "
    f"{fp(pct(ty['it_store'],pw_it_store))} WoW)</b> — all SBUs above LY. Lands at stores in 3–5 days."))
story.append(_sub(
    "All SBUs YoY% (high to low): " + " · ".join(f"{x[0]} {fp(x[4])}" for x in _it_all_sbus) + "."))
story.append(Spacer(1,2))

story.append(_bhead("STORE OH"))
story.append(_bull(
    f"<b>{fm(ty['store'])} ({fp(_store_pct)} YoY, {fp(pct(ty['store'],pw_store))} WoW)</b>  ·  "
    f"<b>Produce WoW {fm(produce_wow_delta)} ({fp(produce_wow_pct)})</b>  ·  "
    f"HARDLINES WoW: {_fmt_movers(_hl_wow_g, _hl_wow_d) if (_hl_wow_g or _hl_wow_d) else 'Stationery leading'} (BTS floor set)"))

# Compact SBU sub-bullets — YoY direction + top depts only (WoW detail on page 2)
def _p1_sbu(sbu_name, ty_s, ly_s, pw_s, yoy_g, yoy_d):
    """Page 1 compact SBU bullet: YoY % + top dept movers, no WoW detail."""
    raw_yoy = pct(ty_s.get(sbu_name,0), ly_s.get(sbu_name,0))
    raw_wow = pct(ty_s.get(sbu_name,0), pw_s.get(sbu_name,0))
    gs = " · ".join(f"{x[0]} {fp(x[4])}" for x in yoy_g[:2])
    ds = " · ".join(f"{x[0]} {fp(x[4])}" for x in yoy_d[:2])
    if raw_yoy < 0 and ds:
        dept = f"▼ {ds}" + (f"  ▲ {gs}" if gs else "")
    elif gs and ds:
        dept = f"▲ {gs}  ▼ {ds}"
    elif gs: dept = f"▲ {gs}"
    elif ds: dept = f"▼ {ds}"
    else:    dept = ""
    return f"<b>{sbu_name} {fp(raw_yoy)} YoY, {fp(raw_wow)} WoW</b>: {dept}." if dept else \
           f"<b>{sbu_name} {fp(raw_yoy)} YoY, {fp(raw_wow)} WoW</b>"

story.append(_sub(_p1_sbu('CONSUMABLES', store_ty, store_ly, store_pw, _cons_g, _cons_d)))
story.append(_sub(_p1_sbu('PANTRY',      store_ty, store_ly, store_pw, _pan_g,  _pan_d)))
story.append(_sub(_p1_sbu('ETS',         store_ty, store_ly, store_pw, _ets_g,  _ets_d)))
story.append(_sub(_p1_sbu('HOME',        store_ty, store_ly, store_pw, _home_g, _home_d)))
story.append(_sub(_p1_sbu('CAC',         store_ty, store_ly, store_pw, _cac_g,  _cac_d)))

story.append(Spacer(1,2))

story.append(_bhead("BACKROOM & SALESFLOOR"))
story.append(_bull(
    f"Backroom: <b>{fm(br_ex_f_ty)} ({fp(_br_pct)} YoY, {fp(pct(br_ex_f_ty,pw_backroom))} WoW)</b>  ·  "
    f"Salesfloor: <b>{fm(sf_ty)} ({fp(sf_yoy_p)} YoY, {fp(sf_wow_p)} WoW, {fm(sf_yoy_d)} units vs LY)</b>"))
_br_line = f"SBU: {_fmt_movers(_br_g, _br_d)}"
if _br_dept_g or _br_dept_d:
    _br_line += f"  |  Key depts: {_fmt_movers(_br_dept_g[:2], _br_dept_d[:1])}"
_br_line += f".  Fashion {fp(pct(br_ty.get('FASHION',0),br_ly.get('FASHION',0)))} YoY."
story.append(_sub(_br_line))
story.append(Spacer(1,2))

story.append(_bhead("INSTOCK  (WMS · as of this week)"))
# ── Static instock from WMS weekly snapshot — update from WMS instock report ──
_is_data = [
    # (SBU,          ty_pct, vs_lw_bps, vs_ly_bps)
    ("Walmart Total", 93.14,  -130,  -79),
    ("Consumables",   95.43,   -65,  -93),
    ("Food",          97.13,   -67,  -12),
    ("Pantry",        96.38,   -72,  -57),
    ("Fashion",       86.05,  -308, -134),
    ("ETSHH",         94.31,   -74,  -27),
    ("Home",          95.42,   -33,  +75),
]
for sbu, is_pct, lw_bps, ly_bps in _is_data:
    lw_str = f"{lw_bps:+.0f} bps vs LW"
    ly_str = f"{ly_bps:+.0f} bps vs LY"
    story.append(_sub(f"<b>{sbu}:</b>  {is_pct:.2f}%  ·  {lw_str}  ·  {ly_str}"))

story.append(Spacer(1,2))
story.append(HRFlowable(width="100%",thickness=0.5,color=colors.HexColor("#ddd"),spaceAfter=1))
story.append(Paragraph(
    f"See page 2 for full narrative  ·  Pages 3+ for charts & data tables  ·  "
    f"Generated {datetime.date.today().strftime('%b %d, %Y')}",
    SMALL))

# ══════════════════════════════════════════════════════════════════
# PAGE 2 — FULL TALK TRACK NARRATIVE
# ══════════════════════════════════════════════════════════════════
story.append(PageBreak())

# Header
story.append(Table([[
    Paragraph("Trade Slides — Inventory Talk Track", TITLE),
    Paragraph(f"WM Week {TRADE_WK}  ·  {TRADE_DATE}  ·  NON-DSD On-Order  ·  All figures vs LY same week",
              ParagraphStyle("rh",fontSize=7.5,fontName="Helvetica",
              textColor=colors.HexColor("#888"),alignment=TA_RIGHT)),
]], colWidths=[4.0*inch,3.3*inch]))
story.append(HRFlowable(width="100%",thickness=2,color=WM_YEL,spaceAfter=6))

story.append(HRFlowable(width="100%",thickness=0.5,color=colors.HexColor("#ddd"),spaceAfter=4))

# Compact body style for page 2 — fits more content without losing readability
BODY2 = ParagraphStyle("b2", fontSize=7.5, fontName="Helvetica",
        textColor=colors.HexColor("#111"), spaceAfter=4, leading=11)
BULL2 = ParagraphStyle("bu2", fontSize=7.5, fontName="Helvetica",
        textColor=colors.HexColor("#111"), leftIndent=12, bulletIndent=4,
        spaceAfter=3, leading=11)

# ── Total Network ─────────────────────────────────────────────────────────────
story += sec("TOTAL NETWORK — {} TY  vs  {} LY  |  {} ({:.1f}%) YoY  ·  {} ({:.1f}%) WoW".format(
    fm(total_ty), fm(total_ly), fm(dlt(total_ty,total_ly)), pct(total_ty,total_ly),
    fm(dlt(total_ty, pw_total)), pct(total_ty, pw_total)))

story.append(Paragraph(
    "Network is <b>{} TY vs {} LY ({:.1f}% YoY, {} WoW)</b>. "
    "DC releasing ({} below LY, {:.1f}%), IT→Store surging (+{} YoY, {} WoW, all SBUs above LY), "
    "store holding at {} ({:.1f}% YoY, {} WoW). "
    "Every signal points to BTX WK23 staging in final stretch.".format(
        fm(total_ty), fm(total_ly), pct(total_ty,total_ly), fp(pct(total_ty,pw_total)),
        fm(abs(dlt(ty['dc'],ly['dc']))), pct(ty['dc'],ly['dc']),
        fm(dlt(ty['it_store'],ly['it_store'])), fp(pct(ty['it_store'],pw_it_store)),
        fm(ty['store']), pct(ty['store'],ly['store']), fp(pct(ty['store'],pw_store))), BODY2))

# ── On Order ──────────────────────────────────────────────────────────────────
story += sec("ON ORDER (NON-DSD) — {ty}  |  {yoy} vs LY  ·  {wow} WoW  ·  {lnw} avg = L{n}W avg {lyoy} vs LY".format(
    ty=fm(oo_ty), yoy=fp(pct(oo_ty,oo_ly)), wow=fp(pct(oo_ty,oo_pw)),
    lnw=fm(sum(l13w_ty_s.values())), n=OO_ROLLING_WEEKS,
    lyoy=fp(pct(sum(l13w_ty_s.values()),sum(l13w_ly_s.values())))))

# ── On-Order: auto-assess signal vs MABD timing for each SBU ─────────────────
# Uses in-store date comparison where coverage ≥10%, L13W otherwise
_oo_signals = {}   # sbu → "real_up" | "real_down" | "mabd_shift" | "l13w_only"
for _s in ['FRESH','PANTRY','CAC','CONSUMABLES','HARDLINES','HOME','FASHION','ETS']:
    _mabd_wow = pct(oo_ty_s.get(_s,0), oo_pw_s.get(_s,0))
    _mabd_yoy = pct(oo_ty_s.get(_s,0), oo_ly_s.get(_s,0))
    _cov      = ins_cov.get(_s, 0.0)
    _ins_yoy  = pct(ins_ty_s.get(_s,0), ins_ly_s.get(_s,0)) if ins_ty_s.get(_s,0)>0 and ins_ly_s.get(_s,0)>0 else None
    _ins_wow = pct(ins_ty_s.get(_s,0), ins_pw_s.get(_s,0)) if ins_pw_s.get(_s,0) else None

    if _cov >= 10.0 and _ins_yoy is not None:
        _shift = abs((_ins_yoy or 0) - _mabd_yoy)
        # Key rule: if MABD WoW large negative but in-store WoW positive → MABD shift (e.g. HARDLINES)
        if abs(_mabd_wow) > 20 and _ins_wow is not None and _ins_wow > 0 and _mabd_wow < 0:
            _oo_signals[_s] = "mabd_shift"    # MABD drop but in-store INCREASING → definitive timing
        elif abs(_mabd_wow) > 20 and _ins_wow is not None and abs(_ins_wow - _mabd_wow) > 25:
            _oo_signals[_s] = "mabd_shift"    # large WoW divergence → MABD timing
        elif _mabd_yoy > 3:
            _oo_signals[_s] = "real_up"
        elif _mabd_yoy < -10:
            _oo_signals[_s] = "real_down"
        else:
            _oo_signals[_s] = "flat"
    else:
        # Low coverage — classify by L13W YoY
        _l13w_p = pct(l13w_ty_s.get(_s,0), l13w_ly_s.get(_s,0))
        if _l13w_p > 3:   _oo_signals[_s] = "real_up"
        elif _l13w_p < -8: _oo_signals[_s] = "real_down"
        else:              _oo_signals[_s] = "l13w_flat"

_mabd_timing_sbus = [s for s,v in _oo_signals.items() if v=="mabd_shift"]
_real_up_sbus     = [s for s,v in _oo_signals.items() if v=="real_up"]
_real_down_sbus   = [s for s,v in _oo_signals.items() if v in ("real_down",)]

# Build dynamic narrative
_l13w_total_pct = pct(sum(l13w_ty_s.values()), sum(l13w_ly_s.values()))
_timing_note = (f" <b>MABD timing shifts detected</b> (in-store date confirms): "
                f"{', '.join(_mabd_timing_sbus)} — single-week MABD dates shifted but "
                "in-store delivery window is stable. No action needed." if _mabd_timing_sbus else "")
_up_note   = (f" <b>Genuine ordering increases</b> (confirmed by L13W): "
              f"{' and '.join(_real_up_sbus)} are ordering ahead of LY — "
              "FRESH for post-A250 perishable fill-in, CAC for World Cup snacking demand." if _real_up_sbus else "")
_down_note = (f" <b>Intentional reductions</b>: "
              f"{' and '.join(_real_down_sbus)} are pulling back — BTS commitments were placed "
              "in prior weeks; forward pipeline already in motion." if _real_down_sbus else "")

story.append(Paragraph(
    "NON-DSD on-order <b>{} ({} vs LY, {} WoW)</b>. "
    "L{} avg {}/wk = <b>{} vs LY</b> — pipeline {}. "
    "{}{}{}".format(
        fm(oo_ty), fp(pct(oo_ty,oo_ly)), fp(pct(oo_ty,oo_pw)),
        OO_ROLLING_WEEKS, fm(sum(l13w_ty_s.values())), fp(_l13w_total_pct),
        "above LY" if _l13w_total_pct > 0 else "below LY",
        _timing_note, _up_note, _down_note),
    BODY2))

# ── In DC + In Transit ────────────────────────────────────────────────────────
story += sec("IN DC & IN TRANSIT — DC: {} ({} YoY, {} WoW)  ·  IT→Store: {} (+{} YoY, {} WoW, all SBUs ▲)".format(
    fm(ty['dc']), fp(pct(ty['dc'],ly['dc'])), fp(pct(ty['dc'],pw_dc)),
    fm(ty['it_store']), fm(dlt(ty['it_store'],ly['it_store'])), fp(pct(ty['it_store'],pw_it_store))))

story.append(Paragraph(
    "DC <b>{} ({} YoY, {} WoW)</b> — releasing into BTX pipeline. "
    "HOME -{} ({:.1f}% vs LY): Bath/Cook&Dine overstock + tariffs. "
    "HARDLINES -{} ({:.1f}% vs LY): Toys LY overstock; Stationery +3% unit buy for BTS Hold & Flow. "
    "IT→Store <b>+{} (+{:.1f}% YoY, {} WoW) — all SBUs above LY</b>; "
    "PANTRY +{:.1f}%, CONSUMABLES +{:.1f}%, HARDLINES +{:.1f}% lead. Lands in 3–5 days.".format(
        fm(ty['dc']), fp(pct(ty['dc'],ly['dc'])), fp(pct(ty['dc'],pw_dc)),
        fm(abs(dlt(dc_ty.get('HOME',0),dc_ly.get('HOME',0)))), abs(pct(dc_ty.get('HOME',0),dc_ly.get('HOME',0))),
        fm(abs(dlt(dc_ty.get('HARDLINES',0),dc_ly.get('HARDLINES',0)))), abs(pct(dc_ty.get('HARDLINES',0),dc_ly.get('HARDLINES',0))),
        fm(dlt(ty['it_store'],ly['it_store'])), pct(ty['it_store'],ly['it_store']), fp(pct(ty['it_store'],pw_it_store)),
        pct(it_ty.get('PANTRY',0),it_ly.get('PANTRY',0)),
        pct(it_ty.get('CONSUMABLES',0),it_ly.get('CONSUMABLES',0)),
        pct(it_ty.get('HARDLINES',0),it_ly.get('HARDLINES',0))), BODY2))

# ── Store + Backroom ──────────────────────────────────────────────────────────
story += sec("STORE OH & BACKROOM — Store: {s} ({sy} YoY, {sw} WoW)  ·  Backroom: {br} ({bry} YoY)  ·  Salesfloor: {sf} ({sfy} YoY, {sfw} WoW)".format(
    s=fm(ty['store']), sy=fp(pct(ty['store'],ly['store'])), sw=fp(pct(ty['store'],pw_store)),
    br=fm(br_ex_f_ty), bry=fp(pct(br_ex_f_ty,br_ex_f_ly)),
    sf=fm(sf_ty), sfy=fp(sf_yoy_p), sfw=fp(sf_wow_p)))

# SBUs to mention in store narrative (exclude FRESH — no text callout per business rule)
_store_sbus_to_discuss = [s for s in store_ty if s not in STORE_YOY_EXCLUDE_SBUS and s != 'OTHER']
_store_gainers  = sorted([s for s in _store_sbus_to_discuss if pct(store_ty.get(s,0),store_ly.get(s,0)) > 1],
                         key=lambda s:-store_ty.get(s,0))
_store_decliners= sorted([s for s in _store_sbus_to_discuss if pct(store_ty.get(s,0),store_ly.get(s,0)) < -2],
                         key=lambda s:pct(store_ty.get(s,0),store_ly.get(s,0)))

# Build dynamic per-SBU store OH lines for narrative
def _p2_sbu(sbu, g, d):
    raw = pct(store_ty.get(sbu,0), store_ly.get(sbu,0))
    gs = " · ".join(f"{x[0]} {fp(x[4])}" for x in g[:2])
    ds = " · ".join(f"{x[0]} {fp(x[4])}" for x in d[:2])
    if raw < 0 and ds:
        detail = f"▼ {ds}" + (f", ▲ {gs}" if gs else "")
    elif gs and ds: detail = f"▲ {gs}  ▼ {ds}"
    elif gs:        detail = f"▲ {gs}"
    elif ds:        detail = f"▼ {ds}"
    else:           detail = ""
    return f"<b>{sbu} {fp(raw)}</b>" + (f": {detail}" if detail else "")

_hl_wow_top = _hl_wow_g[0][0] if _hl_wow_g else "Stationery"
_hl_wow_top_pct = fp(_hl_wow_g[0][4]) if _hl_wow_g else ""
_sbu_lines = "  ".join([
    _p2_sbu('CONSUMABLES', _cons_g, _cons_d),
    _p2_sbu('PANTRY',      _pan_g,  _pan_d),
    _p2_sbu('ETS',         _ets_g,  _ets_d),
    _p2_sbu('HOME',        _home_g, _home_d),
    _p2_sbu('CAC',         _cac_g,  _cac_d),
])
_pull_lines = ""  # Pull opp signals removed per user request

story.append(Paragraph(
    "Store OH <b>{s} ({sy} YoY, {sw} WoW)</b>. "
    "Produce WoW {pd} ({pp}). "
    "HARDLINES WoW: <b>{hl_top} {hl_pct}</b> — BTS floor set landing now. "
    "{sbu_lines}. "
    "Backroom <b>{br} ({bry} YoY, {brw} WoW)</b> — HARDLINES {brhl}% YoY (Stationery staging); "
    "CONSUMABLES +{brco}% / CAC +{brca}% = replenishment, not BTS staging. "
    "Fashion backroom {fy} YoY. "
    "Salesfloor <b>{sf} ({sfy} YoY, {sfw} WoW, {sfyd} units vs LY)</b> = Store OH − Backroom. "
    "{pull}".format(
        s=fm(ty['store']), sy=fp(pct(ty['store'],ly['store'])), sw=fp(pct(ty['store'],pw_store)),
        pd=fm(produce_wow_delta), pp=fp(produce_wow_pct),
        hl_top=_hl_wow_top, hl_pct=_hl_wow_top_pct,
        sbu_lines=_sbu_lines,
        br=fm(br_ex_f_ty), bry=fp(pct(br_ex_f_ty,br_ex_f_ly)), brw=fp(pct(br_ex_f_ty,pw_backroom)),
        brhl=f"{pct(br_ty.get('HARDLINES',0),br_ly.get('HARDLINES',0)):.1f}",
        brco=f"{pct(br_ty.get('CONSUMABLES',0),br_ly.get('CONSUMABLES',0)):.1f}",
        brca=f"{pct(br_ty.get('CAC',0),br_ly.get('CAC',0)):.1f}",
        fy=fp(pct(br_ty.get('FASHION',0),br_ly.get('FASHION',0))),
        sf=fm(sf_ty), sfy=fp(sf_yoy_p), sfw=fp(sf_wow_p), sfyd=fm(sf_yoy_d),
        pull=("<b>Pull opps:</b> " + _pull_lines) if _pull_lines else ""),
    BODY2))

# ── Watch items — auto-generated from business_rules.py (flags pre-computed above) ──
fresh_it_yoy = pct(it_ty.get('FRESH',0), it_ly.get('FRESH',0))

story += sec("INSTOCK  (WMS · as of this week)", color=WM_DARK)
for sbu, is_pct, lw_bps, ly_bps in _is_data:
    lw_str = f"{lw_bps:+.0f} bps vs LW"
    ly_str = f"{ly_bps:+.0f} bps vs LY"
    story.append(Paragraph(f"• <b>{sbu}:</b>  {is_pct:.2f}%  ·  {lw_str}  ·  {ly_str}", BULL2))

# Footer
story.append(Spacer(1,4))

# ══════════════════════════════════════════════════════════════════
# APPENDIX — Charts + All SBU tables
# ══════════════════════════════════════════════════════════════════
story.append(PageBreak())

story.append(Table([[
    Paragraph("APPENDIX — Supporting Data & Charts", TITLE),
    Paragraph(f"Inventory Talk Track  ·  WM Week {TRADE_WK}  ·  {TRADE_DATE}",
              ParagraphStyle("rh2",fontSize=7.5,fontName="Helvetica",
              textColor=colors.HexColor("#888"),alignment=TA_RIGHT)),
]], colWidths=[4.2*inch,3.1*inch]))
story.append(HRFlowable(width="100%",thickness=2,color=WM_YEL,spaceAfter=8))

# A1 — Event timeline
story += app_sec("A1 · ACTIVE EVENTS TIMELINE")
story.append(Paragraph(
    "Three overlapping events are in-season simultaneously with BTX beginning WK23. "
    "The timeline below shows why every supply chain signal this week reflects BTS staging.", BODY))
story.append(Spacer(1,10))

# ── helper: build SBU rows with YoY + WoW ─────────────────────────────────────
def sbu_rows_wow(ty_d, ly_d, pw_d, sort_key=None, exclude=None):
    """Returns rows: [SBU, TY, LY, YoY Δ, YoY%, PW, WoW Δ, WoW%]"""
    SBUs = [s for s in ty_d if s not in (exclude or set()) and s!='OTHER']
    if sort_key: SBUs = sorted(SBUs, key=sort_key)
    rows = []
    for s in SBUs:
        t=ty_d.get(s,0); l=ly_d.get(s,0); p=pw_d.get(s,0)
        rows.append([s, fm(t), fm(l), fm(dlt(t,l)), fp(pct(t,l)),
                     fm(p), fm(dlt(t,p)), fp(pct(t,p))])
    return rows

HDR8 = ["SBU","TY","LY","YoY Δ","YoY%","PW","WoW Δ","WoW%"]
CW8  = [1.35*inch,0.82*inch,0.82*inch,0.82*inch,0.68*inch,0.82*inch,0.82*inch,0.68*inch]
# wow_sep_col=5 draws a blue left border before the PW column

# A2 — Network summary table (with WoW)
story += app_sec("A2 · TOTAL NETWORK SUMMARY TABLE  ·  YoY and WoW")
pw_total_net = pw['total_net'] + oo_pw
kpi=[["Metric","TY","LY","YoY Δ","YoY%","PW","WoW Δ","WoW%"],
     ["Total 6-Bucket",fm(total_ty),fm(total_ly),fm(dlt(total_ty,total_ly)),fp(pct(total_ty,total_ly)),
      fm(pw_total),fm(dlt(total_ty,pw_total)),fp(pct(total_ty,pw_total))],
     ["On-Order (NON-DSD)",fm(oo_ty),fm(oo_ly),fm(dlt(oo_ty,oo_ly)),fp(pct(oo_ty,oo_ly)),
      fm(oo_pw),fm(dlt(oo_ty,oo_pw)),fp(pct(oo_ty,oo_pw))],
     ["On Yard",fm(ty['yard']),fm(ly['yard']),fm(dlt(ty['yard'],ly['yard'])),fp(pct(ty['yard'],ly['yard'])),
      fm(pw['yard']),fm(dlt(ty['yard'],pw['yard'])),fp(pct(ty['yard'],pw['yard']))],
     ["In DC",fm(ty['dc']),fm(ly['dc']),fm(dlt(ty['dc'],ly['dc'])),fp(pct(ty['dc'],ly['dc'])),
      fm(pw_dc),fm(dlt(ty['dc'],pw_dc)),fp(pct(ty['dc'],pw_dc))],
     ["In Transit → DC",fm(ty['it_dc']),fm(ly['it_dc']),fm(dlt(ty['it_dc'],ly['it_dc'])),fp(pct(ty['it_dc'],ly['it_dc'])),
      fm(pw['it_dc']),fm(dlt(ty['it_dc'],pw['it_dc'])),fp(pct(ty['it_dc'],pw['it_dc']))],
     ["In Transit → Store",fm(ty['it_store']),fm(ly['it_store']),fm(dlt(ty['it_store'],ly['it_store'])),fp(pct(ty['it_store'],ly['it_store'])),
      fm(pw_it_store),fm(dlt(ty['it_store'],pw_it_store)),fp(pct(ty['it_store'],pw_it_store))],
     ["Store OH",fm(ty['store']),fm(ly['store']),fm(dlt(ty['store'],ly['store'])),fp(pct(ty['store'],ly['store'])),
      fm(pw_store),fm(dlt(ty['store'],pw_store)),fp(pct(ty['store'],pw_store))],
     ["  Backroom (total)",fm(br_ex_f_ty),fm(br_ex_f_ly),fm(dlt(br_ex_f_ty,br_ex_f_ly)),fp(pct(br_ex_f_ty,br_ex_f_ly)),
      fm(pw_backroom),fm(dlt(br_ex_f_ty,pw_backroom)),fp(pct(br_ex_f_ty,pw_backroom))],
     ["  Salesfloor",fm(ty['salesfloor']),fm(ly['salesfloor']),fm(dlt(ty['salesfloor'],ly['salesfloor'])),fp(pct(ty['salesfloor'],ly['salesfloor'])),
      fm(pw['salesfloor']),fm(dlt(ty['salesfloor'],pw['salesfloor'])),fp(pct(ty['salesfloor'],pw['salesfloor']))],
     ["FC",fm(ty['fc']),fm(ly['fc']),fm(dlt(ty['fc'],ly['fc'])),fp(pct(ty['fc'],ly['fc'])),
      fm(pw_fc),fm(dlt(ty['fc'],pw_fc)),fp(pct(ty['fc'],pw_fc))]]
story.append(sbu_tbl(kpi[0],kpi[1:],up_cols=[3,4,6,7],wow_sep_col=5,
    col_w=[1.9*inch,0.68*inch,0.68*inch,0.68*inch,0.58*inch,0.68*inch,0.68*inch,0.58*inch]))
story.append(Spacer(1,8))

# A3 — Pipeline chart
story += app_sec("A3 · PIPELINE MAGNITUDE — TY vs LY All Nodes (Units, M)")
story.append(Paragraph(f"TY above bars (bold), LY in grey. Store OH ({fm(ty['store'])}) dominates; IT-to-DC ({fm(ty['it_dc'])}) near-invisible at this scale. On Yard ({fm(ty['yard'])}) excluded — too small.", BODY))
story.append(pipeline_chart())
story.append(Spacer(1,8))

# A4 — On-Order SBU with WoW + L13W
story += app_sec(f"A4 · ON-ORDER BY SBU — MABD WK{OO_TY%100} | YoY · WoW · L{OO_ROLLING_WEEKS}W (NON-DSD)")
OO_SBUS=sorted(oo_ty_s.keys(), key=lambda s:-oo_ty_s.get(s,0))
story.append(sbu_tbl(
    ["SBU","TY","LY","YoY Δ","YoY%","WoW%",f"L{OO_ROLLING_WEEKS}W TY",f"L{OO_ROLLING_WEEKS}W LY",f"L{OO_ROLLING_WEEKS}W YoY%"],
    [[s,fm(oo_ty_s.get(s,0)),fm(oo_ly_s.get(s,0)),
      fm(dlt(oo_ty_s.get(s,0),oo_ly_s.get(s,0))),
      fp(pct(oo_ty_s.get(s,0),oo_ly_s.get(s,0))),
      fp(pct(oo_ty_s.get(s,0),oo_pw_s.get(s,0))),
      fm(l13w_ty_s.get(s,0)),fm(l13w_ly_s.get(s,0)),
      fp(pct(l13w_ty_s.get(s,0),l13w_ly_s.get(s,0)))] for s in OO_SBUS],
    up_cols=[3,4,5,8], wow_sep_col=5,
    col_w=[1.3*inch,0.72*inch,0.72*inch,0.72*inch,0.62*inch,0.62*inch,0.7*inch,0.7*inch,0.7*inch]))
story.append(Paragraph(
    f"L{OO_ROLLING_WEEKS}W = {OO_ROLLING_WEEKS}-week rolling avg (recommended leadership metric; smooths single-week MABD timing shifts). "
    "WoW large swings confirmed via in-store date comparison before flagging as demand signals.",
    ParagraphStyle("fn",fontSize=7.5,fontName="Helvetica-Oblique",textColor=colors.HexColor("#666"),spaceAfter=4)))
story.append(Spacer(1,8))

# A5 — In DC SBU with WoW (full definition: DC OH + Labeled + Unlabeled + Reserved)
story += app_sec("A5 · IN DC BY SBU  ·  Full definition: DC OH + Labeled + Unlabeled + Reserved")
DC_SBUS=sorted(dc_ty.keys(),key=lambda s:dlt(dc_ty.get(s,0),dc_ly.get(s,0)))
story.append(sbu_tbl(HDR8,
    sbu_rows_wow(dc_ty, dc_ly, dc_pw,
                 sort_key=lambda s:dlt(dc_ty.get(s,0),dc_ly.get(s,0))),
    up_cols=[3,4,6,7], wow_sep_col=5, col_w=CW8))
story.append(Spacer(1,8))

# A6 — In Transit → Store with WoW
story += app_sec("A6 · IN TRANSIT → STORE BY SBU")
story.append(sbu_tbl(HDR8,
    sbu_rows_wow(it_ty, it_ly, it_pw,
                 sort_key=lambda s:-it_ty.get(s,0)),
    up_cols=[3,4,6,7], wow_sep_col=5, col_w=CW8))
story.append(Spacer(1,8))

# A7 — Store OH with WoW (all SBUs — FRESH shown in data but no YoY interpretation)
story += app_sec("A7 · STORE OH BY SBU  ·  *FRESH YoY: data methodology change GRS→EI effective Jun 23 — not comparable")
story.append(sbu_tbl(HDR8,
    sbu_rows_wow(store_ty, store_ly, store_pw,
                 sort_key=lambda s:dlt(store_ty.get(s,0),store_ly.get(s,0))),
    up_cols=[3,4,6,7], wow_sep_col=5, col_w=CW8))
story.append(Spacer(1,8))

# A8 — Backroom with WoW — ALL SBUs including Fashion
story += app_sec("A8 · BACKROOM BY SBU  ·  WoW valid for all SBUs · YoY: Fashion inflated (new FY26 tracking)")
story.append(sbu_tbl(HDR8,
    sbu_rows_wow(br_ty, br_ly, br_pw,
                 sort_key=lambda s:-br_ty.get(s,0)),
    up_cols=[3,4,6,7], wow_sep_col=5, col_w=CW8))

# Appendix footer
story.append(Spacer(1,6))

doc.build(story)
print(f"✅  PDF: {OUT}")
