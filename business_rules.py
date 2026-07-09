"""
business_rules.py — Weekly Inventory Talk Track: Learned Business Logic
========================================================================

Captures institutional knowledge built during WK22 analysis so that:
  1. The dashboard auto-applies these rules on refresh each week
  2. The talk track PDF auto-assesses watch items rather than hard-coding them
  3. Future analysts understand WHY certain metrics are treated the way they are

Update this file when business rules change (e.g., new tracking starts, thresholds shift).
"""

from __future__ import annotations

# ── Week format helpers ───────────────────────────────────────────────────────
# HIST_ONORDER   uses wm_week  = YYWWW  (e.g. 12622 = FY26 Wk22), LY offset -100
# HIST_COMBINED  uses WM_YR_WK = YYYYWW (e.g. 202622 = 2026 Wk22), LY offset -100

def yyyyww_to_yywww(yyyyww: int) -> int:
    """Convert HIST_COMBINED week (202622) → on-order week (12622)."""
    yr = (yyyyww // 100) - 2000
    wk = yyyyww % 100
    return 10000 + yr * 100 + wk


# ── On-Order: MABD vs In-Store Date ──────────────────────────────────────────
# LEARNING (WK22-2026):
#   Single-week MABD view is noisy — import POs can shift MABD by 1 week,
#   causing ±40-60% WoW swings that have no demand signal.
#   The L4W rolling average is the recommended leadership metric.
#   In-store date provides a demand signal but only where populated.
#
# COVERAGE THRESHOLDS (confirmed WK22):
#   SBU           In-Store Coverage   Reliable?
#   HOME          52%                 YES — use for YoY
#   ETS           46%                 YES — use for YoY
#   FASHION       31%                 YES — use for YoY
#   HARDLINES     15%                 LOW — use with caveat
#   CONSUMABLES    4%                 NO  — do not rely on
#   CAC            2%                 NO
#   PANTRY         1%                 NO
#   FRESH          0.1%               NO

OO_INSTORE_MIN_COV_PCT = 10.0   # minimum % to show in-store YoY (below = "⚠ low coverage")
OO_INSTORE_WIN_WEEKS   = 2      # ±N weeks around current week for in-store window

# MABD watch item rules:
#   Flag a SBU as a watch item if:
#     abs(WoW%) > OO_WOW_FLAG_THRESHOLD
#   AND one of:
#     (a) L4W YoY is also negative  → likely real demand signal
#     (b) L4W YoY > 0 but WoW is dramatic  → MABD shift, note as timing
#
#   Auto-DROP from watch list if:
#     abs(WoW%) < OO_WOW_FLAG_THRESHOLD (no flag needed)
#     OR L4W YoY > OO_L4W_SAFE_THRESHOLD (healthy underlying demand)
#        AND in-store YoY is within OO_INSTORE_ALIGNED_THRESHOLD of L4W YoY
#           (in-store date confirms no real shift)

OO_WOW_FLAG_THRESHOLD      = 20.0   # abs WoW% above this triggers evaluation
OO_L13W_SAFE_THRESHOLD     = -5.0   # L13W YoY above this = underlying demand healthy
OO_L13W_CONCERN_THRESHOLD  = -10.0  # L13W YoY below this = real demand concern, always flag
OO_INSTORE_ALIGNED_PCT     = 15.0   # if |instore_YoY - mabd_YoY| < this → no MABD shift

# Rolling window for smoothed on-order average
# LEARNING: L13W (13 weeks = one quarter) is preferred over L4W —
#   captures full seasonal cycle, less distorted by single import PO drops.
#   WK22 example: HARDLINES L13W +7.0% vs LY shows category is healthy
#   even when single-week MABD shows -51.4% WoW.
OO_ROLLING_WEEKS = 13   # number of weeks for rolling average (was 4, upgraded to 13)


def assess_oo_watch(sbu: str, mabd_wow_pct: float, l13w_yoy_pct: float,
                    instore_cov_pct: float, instore_yoy_pct: float | None,
                    mabd_yoy_pct: float) -> dict:
    """
    Returns a dict with:
      flag   : bool   — should this SBU appear in watch list?
      level  : str    — "concern" | "timing" | "clear"
      reason : str    — human-readable explanation
    """
    wow_abs = abs(mabd_wow_pct)

    # Not a big WoW move — no flag needed
    if wow_abs < OO_WOW_FLAG_THRESHOLD:
        return {"flag": False, "level": "clear",
                "reason": f"WoW {mabd_wow_pct:+.1f}% within normal range"}

    # Real demand concern: L13W also negative
    if l13w_yoy_pct < OO_L13W_CONCERN_THRESHOLD:
        return {"flag": True, "level": "concern",
                "reason": f"WoW {mabd_wow_pct:+.1f}% AND L13W {l13w_yoy_pct:+.1f}% YoY — "
                          "underlying demand signal is weakening. Escalate to buying team."}

    # Check in-store date if coverage is sufficient
    if instore_cov_pct >= OO_INSTORE_MIN_COV_PCT and instore_yoy_pct is not None:
        shift = abs((instore_yoy_pct or 0) - mabd_yoy_pct)
        if shift < OO_INSTORE_ALIGNED_PCT:
            # In-store date confirms no real shift → auto-drop from watch list
            return {"flag": False, "level": "clear",
                    "reason": f"WoW {mabd_wow_pct:+.1f}% but in-store YoY ({instore_yoy_pct:+.1f}%) "
                              f"aligns with MABD YoY ({mabd_yoy_pct:+.1f}%) — no real demand shift. "
                              "MABD timing only. Dropped from watch list."}
        # Special case: MABD WoW large negative but InStr WoW positive → definitive MABD shift
        # LEARNING (WK22): HARDLINES MABD -51.4% WoW but InStr +22.6% WoW → orders genuinely UP
        if mabd_wow_pct < -OO_WOW_FLAG_THRESHOLD and instore_yoy_pct > 0:
            return {"flag": False, "level": "clear",
                    "reason": f"MABD WoW {mabd_wow_pct:+.1f}% (large drop) but in-store date shows "
                              f"{instore_yoy_pct:+.1f}% YoY — orders are INCREASING when measured by "
                              "delivery date. MABD date shift confirmed. Dropped from watch list."}
        else:
            # In-store confirms real shift even though L13W is OK
            return {"flag": True, "level": "timing",
                    "reason": f"WoW {mabd_wow_pct:+.1f}%, L13W healthy ({l13w_yoy_pct:+.1f}% YoY) "
                              f"but in-store date shift detected ({instore_yoy_pct:+.1f}% vs MABD {mabd_yoy_pct:+.1f}%). "
                              "Monitor for 2 weeks."}

    # In-store coverage too low — rely on L13W only
    if l13w_yoy_pct > OO_L13W_SAFE_THRESHOLD:
        return {"flag": True, "level": "timing",
                "reason": f"WoW {mabd_wow_pct:+.1f}% (large single-week MABD drop), "
                          f"but L13W avg is healthy at {l13w_yoy_pct:+.1f}% YoY. "
                          f"In-store date coverage {instore_cov_pct:.0f}% (too low to confirm). "
                          "Likely MABD timing — confirm import PO schedule with buying team."}

    return {"flag": True, "level": "concern",
            "reason": f"WoW {mabd_wow_pct:+.1f}%, L13W {l13w_yoy_pct:+.1f}% YoY — "
                      "both metrics below threshold. Investigate with buying team."}


# ── Store OH: FRESH data methodology change ──────────────────────────────────
# LEARNING (WK22-2026, effective Jun 23, 2026):
#   Fresh store OH data was converted from GRS OH (Grocery Replenishment System)
#   to EI (Execution Intelligence) effective June 23, 2026.
#   TY data  (current weeks) → EI methodology
#   LY data  (same week LY)  → GRS OH methodology
#   These two systems are NOT directly comparable — YoY decline for FRESH store OH
#   is a data methodology artifact, NOT a supply signal.
#
#   Impact: FRESH shows ~-9% to -15% YoY in store OH that would otherwise suggest
#           seasonal depletion. This number CANNOT be used for leadership commentary
#           until a full year of EI data is available for LY comparison (FY27+).
#
#   RULE: Exclude FRESH (and sub-categories Produce, Dairy, Frozen, etc.) from
#         store OH YoY commentary. Mention the data methodology note if FRESH store
#         YoY is flagged. DO NOT use IT-to-Store surge as a "replenishment response"
#         to FRESH store decline — that linkage is data-driven, not demand-driven.
#
#   Revisit: FY27 WK01 — when LY will also be on EI, comparison becomes valid.

STORE_YOY_EXCLUDE_SBUS = set()       # EI system updated Jul 2026 — all SBUs YoY now valid
STORE_YOY_EXCLUDE_NOTE = ""          # No exclusions

# EI system fully updated — both TY and LY now on same source (EI)
# All FRESH/Produce YoY and WoW comparisons are valid
FRESH_WOW_VALID       = True
FRESH_YOY_MERCH1_NOTE = ""           # No caveat needed

# ── Backroom: Fashion YoY exclusion ──────────────────────────────────────────
# LEARNING (WK22-2026):
#   Fashion backroom tracking BEGAN FY26.
#   LY data is partial-year — YoY comparison is not meaningful until FY27.
#   Rule: never show Fashion backroom YoY in network totals.
#   Show Fashion backroom as a directional note only (staging context).
#   Revisit in FY27 when full-year LY baseline exists.

BACKROOM_YOY_EXCLUDE_SBUS = set()   # Fashion is now INCLUDED in all numbers

# RULE (updated):
#   DATA: Fashion IS included in all backroom totals (dashboard, tables, charts)
#   TALK TRACK - YoY: Do NOT call out Fashion-driven YoY increase as a supply signal
#                     Fashion backroom tracking added end of LY → YoY always inflated
#                     Say: "Fashion YoY not comparable (new tracking)" if YoY is referenced
#   TALK TRACK - WoW: CAN include Fashion — Fashion WAS in backroom last week → valid comparison
BACKROOM_YOY_FASHION_NOTE = (
    "Fashion YoY not comparable — backroom tracking added end of LY. WoW trend is valid."
)


# ── Store: FRESH depletion context ────────────────────────────────────────────
# LEARNING (WK22-2026):
#   FRESH store declines are often natural summer/seasonal depletion, not a risk signal.
#   Check IT-to-Store for FRESH before flagging:
#     If IT-to-Store FRESH YoY > 20%, depletion is covered → no store risk flag
#     If IT-to-Store FRESH YoY < 5%,  depletion is NOT covered → flag store risk

FRESH_REPLEN_COVERED_THRESHOLD = 20.0    # IT-to-Store YoY% above = depletion covered
FRESH_REPLEN_RISK_THRESHOLD    = 5.0     # IT-to-Store YoY% below = flag store risk


# ── Event calendar (used for seasonal context in talk track) ─────────────────
# Source: wmlink/event (Seasonal & Event Transition Hub)
# Update at start of each fiscal quarter

ACTIVE_EVENTS = [
    # (name, emoji, wk_start, wk_end, note)
    ("A250 (250th Anniversary)",    "🇺🇸", 18, 22, "Patriotic, BBQ, outdoor — ends WK22"),
    ("Summer Seasonal",             "☀️",  18, 24, "Outdoor, patio, BBQ, Lawn & Garden"),
    ("World Cup 2026",              "⚽",  18, 30, "Jerseys, Electronics, Food & Bev — 25% through WK22"),
    ("BTX 2026 (Back-to-School)",   "🛍️", 23, 32, "School supplies, Electronics, Apparel, Dorm — starts WK23"),
    ("Halloween",                   "🎃", 38, 44, "Costumes, Candy, Decor"),
    ("Holiday Peak (BF/CM)",        "🎄", 45, 52, "Black Friday, Christmas, peak season"),
]

BQ_EVENT_TABLE = "wmt-execution-intel-prod.EVENT_REPORTING"   # World Cup: ER_WORLD_CUP_OMNI_SALES


# ── Watch item auto-assessment thresholds ─────────────────────────────────────
# These govern which items appear in the "Watch Items" section of the talk track.
# Items that pass all checks are automatically DROPPED from the watch list.

WATCH_THRESHOLDS = {
    # Key: metric name → threshold for auto-flagging
    "dc_yoy_decline_flag":     -15.0,    # YoY% below = flag DC SBU
    "dc_yoy_build_flag":       +15.0,    # YoY% above = note DC SBU building
    "store_yoy_decline_flag":   -5.0,    # YoY% below = check IT-to-Store coverage
    "it_store_all_up_threshold": 0.0,    # all SBUs above this = positive signal, no flag
    "backroom_surge_flag":      +50.0,   # YoY% above = note potential staging concern
}


# ── Refresh schedule ──────────────────────────────────────────────────────────
# Dashboard auto-refresh days (same logic as app.py)
# Data available: Wed evening (mid-week) through Sat end-of-week snapshot
REFRESH_WEEKDAYS = {2, 3, 4, 5}   # Mon=0 … Sun=6; here: Wed=2, Thu=3, Fri=4, Sat=5
REFRESH_INTERVAL_HOURS = 4
