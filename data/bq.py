"""
BigQuery connector for the Inventory Health Dashboard.

Authentication (pick one):
  Local dev  : run `gcloud auth application-default login`
  Posit Connect: set GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
                 OR set BQ_PROJECT_ID (defaults to wmt-execution-intel-prod)

If BQ credentials are unavailable the module returns SAMPLE data so the app
renders immediately without a live connection.
"""

from __future__ import annotations

import os
import random
import warnings
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv

# Load .env before credential probe so GOOGLE_APPLICATION_CREDENTIALS is set
load_dotenv()

# ── Detect BQ availability ────────────────────────────────────────────────────
# Credentials: uses whatever GOOGLE_APPLICATION_CREDENTIALS points to
# (authorized_user from gcloud auth OR service_account JSON — both work via ADC)
_BQ_PROJECT   = os.getenv("BQ_PROJECT_ID", "wmt-execution-intel-prod")
_BQ_AVAILABLE = False

try:
    from google.cloud import bigquery
    import google.auth

    _bq_client: bigquery.Client | None = None

    def _get_client() -> bigquery.Client:
        global _bq_client
        if _bq_client is None:
            # ADC handles both authorized_user and service_account transparently
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _bq_client = bigquery.Client(project=_BQ_PROJECT)
        return _bq_client

    # Probe: can we get credentials at all?
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        google.auth.default()
        _BQ_AVAILABLE = True
    print(f"[BQ] Credentials found. Project: {_BQ_PROJECT}")

except Exception as _e:
    print(f"[BQ] No credentials available ({_e}). Will use sample data.")


def _run_query(sql: str) -> pd.DataFrame:
    """Run a BQ query; on any error fall back to sample data (returns empty df)."""
    try:
        client = _get_client()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return client.query(sql).result().to_dataframe()
    except Exception as exc:
        print(f"[BQ] Query failed, using sample data. Error: {exc}")
        return pd.DataFrame()   # caller checks for empty and falls back


# ── SBU / dimension constants ─────────────────────────────────────────────────
SBUS = ["CONSUMABLES", "FRESH", "CAC", "PANTRY", "FASHION", "ETS", "HARDLINES", "HOME"]

_DEPT_MAP = {
    "CONSUMABLES": ["Cleaning", "Personal Care", "Baby", "Pet"],
    "FRESH":       ["Produce", "Deli", "Bakery", "Dairy"],
    "CAC":         ["Candy", "Snacks", "Beverages", "Cereal"],
    "PANTRY":      ["Dry Grocery", "Condiments", "Baking"],
    "FASHION":     ["Womens", "Mens", "Kids", "Shoes"],
    "ETS":         ["Electronics", "Toys", "Sporting Goods"],
    "HARDLINES":   ["Automotive", "Hardware", "Garden", "Tools"],
    "HOME":        ["Furniture", "Bedding", "Kitchen", "Decor"],
}

# ── Sample data ───────────────────────────────────────────────────────────────
# Scale loosely based on the screenshot total: ~8.88B network units

_RNG = random.Random(42)

# Node weights: approximate share of total per SBU
_NODE_MEANS = {
    "on_order":    1_581_000_000,
    "on_yard":         1_100_000,
    "in_dc":       2_101_000_000,
    "it_dc":          13_000_000,
    "it_store":      155_000_000,
    "store_oh":    4_643_000_000,
    "backroom":      399_000_000,
    "fc":             63_600_000,
}

_SBU_WEIGHTS = {
    "CONSUMABLES": 0.18, "FRESH": 0.22, "CAC": 0.10, "PANTRY": 0.08,
    "FASHION": 0.12, "ETS": 0.10, "HARDLINES": 0.10, "HOME": 0.10,
}

# Cube ft³ per unit (approximate)
_CUBE_PER_UNIT = {
    "CONSUMABLES": 0.04, "FRESH": 0.06, "CAC": 0.05, "PANTRY": 0.05,
    "FASHION": 0.03, "ETS": 0.08, "HARDLINES": 0.10, "HOME": 0.12,
}


def _jitter(base: float, pct: float = 0.12) -> float:
    return base * (1 + _RNG.uniform(-pct, pct))


def _sample_onorder(num_weeks: int = 60) -> pd.DataFrame:
    """Generate weekly on-order sample data with WoW/YoY/L13W columns."""
    today_wk = 12626  # approx FY26 Wk26 (Jul 2026)
    rows = []
    for w_offset in range(num_weeks - 1, -1, -1):
        wm_week = today_wk - w_offset
        ly_week = wm_week - 100
        for sbu in SBUS:
            for dept in _DEPT_MAP[sbu]:
                base_units = _NODE_MEANS["on_order"] * _SBU_WEIGHTS[sbu] / len(_DEPT_MAP[sbu])
                units = _jitter(base_units, 0.15)
                cube  = units * _CUBE_PER_UNIT.get(sbu, 0.05)
                rows.append({
                    "wm_week": wm_week,
                    "sbu": sbu,
                    "OMNI_DEPT_NBR": hash(dept) % 99 + 1,
                    "OMNI_DEPT_DESC": dept,
                    "OMNI_CATG_NBR": hash(dept) % 99 + 101,
                    "OMNI_CATG_DESC": dept + " General",
                    "units_ordered": units,
                    "cube_ordered":  cube,
                    # Approximate analytics (real values computed by BQ)
                    "wow_units_delta":  _jitter(0, 1) * base_units * 0.05,
                    "wow_units_pct":    _RNG.uniform(-0.08, 0.10),
                    "wow_cube_delta":   _jitter(0, 1) * base_units * 0.05 * _CUBE_PER_UNIT.get(sbu, 0.05),
                    "wow_cube_pct":     _RNG.uniform(-0.08, 0.10),
                    "ly_units_ordered": _jitter(base_units, 0.12),
                    "yoy_units_delta":  _jitter(0, 1) * base_units * 0.03,
                    "yoy_units_pct":    _RNG.uniform(-0.15, 0.20),
                    "yoy_cube_delta":   _jitter(0, 1) * base_units * 0.03 * _CUBE_PER_UNIT.get(sbu, 0.05),
                    "yoy_cube_pct":     _RNG.uniform(-0.15, 0.20),
                    "l13w_avg_units":   _jitter(base_units, 0.05),
                    "l13w_avg_cube":    _jitter(base_units * _CUBE_PER_UNIT.get(sbu, 0.05), 0.05),
                    "l13w_avg_units_ly":_jitter(base_units * 0.97, 0.05),
                    "l13w_vs_ly_pct":   _RNG.uniform(-0.05, 0.12),
                })
    return pd.DataFrame(rows)


def _sample_inventory(num_weeks: int = 30) -> pd.DataFrame:
    """Generate weekly combined-inventory sample data."""
    today_wk = 202626  # approx YYYYWW for FY26 Wk26
    rows = []
    for w_offset in range(num_weeks - 1, -1, -1):
        wm_yrwk = today_wk - w_offset
        for sbu in SBUS:
            for dept in _DEPT_MAP[sbu]:
                w = _SBU_WEIGHTS[sbu] / len(_DEPT_MAP[sbu])
                cu = _CUBE_PER_UNIT.get(sbu, 0.06)

                yard      = _jitter(_NODE_MEANS["on_yard"]   * w, 0.20)
                in_dc     = _jitter(_NODE_MEANS["in_dc"]     * w, 0.12)
                it_dc     = _jitter(_NODE_MEANS["it_dc"]     * w, 0.15)
                it_store  = _jitter(_NODE_MEANS["it_store"]  * w, 0.12)
                store_oh  = _jitter(_NODE_MEANS["store_oh"]  * w, 0.08)
                backroom  = _jitter(_NODE_MEANS["backroom"]  * w, 0.10)
                fc        = _jitter(_NODE_MEANS["fc"]        * w, 0.10)
                salesfloor = max(0, store_oh - backroom)

                def _wow(v: float)  -> float: return _RNG.uniform(-0.08, 0.10)
                def _yoy(v: float)  -> float: return _RNG.uniform(-0.15, 0.20)
                def _delta(v: float, pct: float) -> float: return v * pct

                wow_yard_pct       = _wow(yard)
                wow_dc_pct         = _wow(in_dc)
                wow_it_total_pct   = _wow(it_dc + it_store)
                wow_it_dc_pct      = _wow(it_dc)
                wow_it_store_pct   = _wow(it_store)
                wow_store_pct      = _wow(store_oh)
                wow_backroom_pct   = _wow(backroom)
                wow_fc_pct         = _wow(fc)
                wow_total_pct      = _wow(store_oh + in_dc + fc)

                yoy_yard_pct       = _yoy(yard)
                yoy_dc_pct         = _yoy(in_dc)
                yoy_it_dc_pct      = _yoy(it_dc)
                yoy_it_store_pct   = _yoy(it_store)
                yoy_it_total_pct   = _yoy(it_dc + it_store)
                yoy_store_pct      = _yoy(store_oh)
                yoy_backroom_pct   = _yoy(backroom)
                yoy_fc_pct         = _yoy(fc)
                yoy_total_pct      = _yoy(store_oh + in_dc + fc)

                rows.append({
                    "WM_YR_WK_NBR": wm_yrwk,
                    "sbu": sbu,
                    "OMNI_DEPT_NBR":   hash(dept) % 99 + 1,
                    "OMNI_DEPT_DESC":  dept,
                    "OMNI_CATG_NBR":   hash(dept) % 99 + 101,
                    "OMNI_CATG_DESC":  dept + " General",
                    # Units
                    "on_yard_units":    yard,
                    "on_yard_cube":     yard * cu,
                    "in_dc_units":      in_dc,
                    "in_dc_cube":       in_dc * cu,
                    "it_dc_units":      it_dc,
                    "it_dc_cube":       it_dc * cu,
                    "it_store_units":   it_store,
                    "it_store_cube":    it_store * cu,
                    "it_total_units":   it_dc + it_store,
                    "it_total_cube":    (it_dc + it_store) * cu,
                    "store_oh_units":   store_oh,
                    "store_oh_cube":    store_oh * cu,
                    "backroom_units":   backroom,
                    "backroom_cube":    backroom * cu,
                    "salesfloor_units": salesfloor,
                    "fc_oh_units":      fc,
                    "fc_oh_cube":       fc * cu,
                    "total_network_units": yard + in_dc + it_dc + it_store + store_oh + fc,
                    # WoW
                    "wow_yard_pct":      wow_yard_pct,
                    "wow_yard_delta":    _delta(yard, wow_yard_pct),
                    "wow_yard_cube_delta": _delta(yard * cu, wow_yard_pct),
                    "wow_dc_pct":        wow_dc_pct,
                    "wow_dc_delta":      _delta(in_dc, wow_dc_pct),
                    "wow_dc_cube_delta": _delta(in_dc * cu, wow_dc_pct),
                    "wow_it_total_pct":  wow_it_total_pct,
                    "wow_it_total_delta":_delta(it_dc + it_store, wow_it_total_pct),
                    "wow_it_dc_pct":     wow_it_dc_pct,
                    "wow_it_dc_delta":   _delta(it_dc, wow_it_dc_pct),
                    "wow_it_store_pct":  wow_it_store_pct,
                    "wow_it_store_delta":_delta(it_store, wow_it_store_pct),
                    "wow_store_pct":     wow_store_pct,
                    "wow_store_delta":   _delta(store_oh, wow_store_pct),
                    "wow_store_cube_delta": _delta(store_oh * cu, wow_store_pct),
                    "wow_backroom_pct":  wow_backroom_pct,
                    "wow_backroom_delta":_delta(backroom, wow_backroom_pct),
                    "wow_fc_pct":        wow_fc_pct,
                    "wow_fc_delta":      _delta(fc, wow_fc_pct),
                    "wow_fc_cube_delta": _delta(fc * cu, wow_fc_pct),
                    "wow_total_pct":     wow_total_pct,
                    "wow_total_delta":   _delta(yard + in_dc + it_dc + it_store + store_oh + fc, wow_total_pct),
                    # YoY
                    "ly_yard":    _jitter(yard, 0.12),   "ly_yard_cube":    _jitter(yard * cu, 0.12),
                    "yoy_yard_pct": yoy_yard_pct,        "yoy_yard_delta":  _delta(yard, yoy_yard_pct),
                    "yoy_yard_cube_delta": _delta(yard * cu, yoy_yard_pct), "yoy_yard_cube_pct": yoy_yard_pct,
                    "ly_dc":      _jitter(in_dc, 0.10),  "ly_dc_cube":      _jitter(in_dc * cu, 0.10),
                    "yoy_dc_pct": yoy_dc_pct,            "yoy_dc_delta":    _delta(in_dc, yoy_dc_pct),
                    "yoy_dc_cube_delta": _delta(in_dc * cu, yoy_dc_pct), "yoy_dc_cube_pct": yoy_dc_pct,
                    "ly_it_dc":   _jitter(it_dc, 0.15),  "ly_it_dc_cube":   _jitter(it_dc * cu, 0.15),
                    "yoy_it_dc_pct": yoy_it_dc_pct,      "yoy_it_dc_delta": _delta(it_dc, yoy_it_dc_pct),
                    "yoy_it_dc_cube_delta": _delta(it_dc * cu, yoy_it_dc_pct), "yoy_it_dc_cube_pct": yoy_it_dc_pct,
                    "ly_it_store":_jitter(it_store, 0.12),"ly_it_store_cube":_jitter(it_store * cu, 0.12),
                    "yoy_it_store_pct": yoy_it_store_pct,"yoy_it_store_delta": _delta(it_store, yoy_it_store_pct),
                    "yoy_it_store_cube_delta": _delta(it_store * cu, yoy_it_store_pct), "yoy_it_store_cube_pct": yoy_it_store_pct,
                    "yoy_it_total_pct": yoy_it_total_pct,"yoy_it_total_delta": _delta(it_dc + it_store, yoy_it_total_pct),
                    "ly_store":   _jitter(store_oh, 0.08),"ly_store_cube":   _jitter(store_oh * cu, 0.08),
                    "yoy_store_pct": yoy_store_pct,      "yoy_store_delta": _delta(store_oh, yoy_store_pct),
                    "yoy_store_cube_delta": _delta(store_oh * cu, yoy_store_pct), "yoy_store_cube_pct": yoy_store_pct,
                    "ly_backroom":_jitter(backroom, 0.10),"ly_backroom_cube":_jitter(backroom * cu, 0.10),
                    "yoy_backroom_pct": yoy_backroom_pct,"yoy_backroom_delta": _delta(backroom, yoy_backroom_pct),
                    "ly_fc":      _jitter(fc, 0.10),      "ly_fc_cube":      _jitter(fc * cu, 0.10),
                    "yoy_fc_pct": yoy_fc_pct,             "yoy_fc_delta":    _delta(fc, yoy_fc_pct),
                    "yoy_fc_cube_delta": _delta(fc * cu, yoy_fc_pct), "yoy_fc_cube_pct": yoy_fc_pct,
                    "ly_total":   _jitter(store_oh + in_dc + fc, 0.08),
                    "yoy_total_pct": yoy_total_pct,
                    "yoy_total_delta": _delta(store_oh + in_dc + fc, yoy_total_pct),
                })
    return pd.DataFrame(rows)


# ── Public API ────────────────────────────────────────────────────────────────

def _yyyyww_to_yywww(yyyyww: int) -> int:
    """
    Convert HIST_COMBINED week format to on-order week format.
    YYYYWW (202622)  ->  YYWWW (12622)
    Formula: 10000 + (YYYY - 2000) * 100 + WW
    e.g. 202622 -> 10000 + 26*100 + 22 = 12622
    """
    yr   = (yyyyww // 100) - 2000   # 2026 -> 26
    wk   = yyyyww % 100             # 22
    return 10000 + yr * 100 + wk


def _get_current_inv_week() -> int:
    """Query BQ for the latest WM_YR_WK_NBR in HIST_COMBINED."""
    from data.queries import SQL_CURRENT_INV_WEEK
    df = _run_query(SQL_CURRENT_INV_WEEK)
    if df.empty or "cur_week" not in df.columns:
        return 202622  # safe fallback
    return int(df["cur_week"].iloc[0])


def _get_current_oo_week() -> int:
    """
    Derive current on-order week from HIST_COMBINED's latest week.
    Avoids using MAX(wm_week) from on-order table which includes far-future MABDs.
    202622 (YYYYWW) -> 12622 (YYWWW)
    """
    inv_week = _get_current_inv_week()
    return _yyyyww_to_yywww(inv_week)


def fetch_oo_snapshot(cur_week: int | None = None) -> pd.DataFrame:
    """
    On-order for current week + WoW + YoY + L13W.
    Uses BQ if available, else sample data.
    """
    if not _BQ_AVAILABLE:
        print("[BQ] No credentials -> sample on-order")
        return _sample_onorder(num_weeks=1)
    if cur_week is None:
        cur_week = _get_current_oo_week()
    from data.queries import SQL_OO_SNAPSHOT
    from google.cloud import bigquery as _bq
    client = _get_client()
    job_config = _bq.QueryJobConfig(
        query_parameters=[_bq.ScalarQueryParameter("cur_week", "INT64", cur_week)]
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = client.query(SQL_OO_SNAPSHOT, job_config=job_config).result().to_dataframe()
        if df.empty:
            print("[BQ] OO snapshot empty -> sample")
            return _sample_onorder(num_weeks=1)
        print(f"[BQ] OO snapshot loaded: {len(df)} rows, wm_week={cur_week}")
        return df
    except Exception as exc:
        print(f"[BQ] OO snapshot failed ({exc}) -> sample")
        return _sample_onorder(num_weeks=1)


def fetch_inv_snapshot(cur_week: int | None = None) -> pd.DataFrame:
    """
    Combined inventory for current week + WoW + YoY.
    Uses BQ if available, else sample data.
    """
    if not _BQ_AVAILABLE:
        print("[BQ] No credentials -> sample inventory")
        return _sample_inventory(num_weeks=1)
    if cur_week is None:
        cur_week = _get_current_inv_week()
    from data.queries import SQL_INV_SNAPSHOT
    from google.cloud import bigquery as _bq
    client = _get_client()
    job_config = _bq.QueryJobConfig(
        query_parameters=[_bq.ScalarQueryParameter("cur_week", "INT64", cur_week)]
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = client.query(SQL_INV_SNAPSHOT, job_config=job_config).result().to_dataframe()
        if df.empty:
            print("[BQ] INV snapshot empty -> sample")
            return _sample_inventory(num_weeks=1)
        # ── Backroom fallback: pipeline sometimes loads BACKROOM_UNITS late ──
        # If current week backroom = 0 but prior week has data, use PW as proxy.
        br_ty = df["backroom_units"].sum()   if "backroom_units" in df.columns else 0
        br_pw = df["pw_backroom"].sum()      if "pw_backroom"    in df.columns else 0
        if br_ty == 0 and br_pw > 0:
            print(f"[BQ] WK{cur_week} backroom=0 (pipeline pending) — using PW ({br_pw/1e6:.0f}M) as proxy")
            for col_ty, col_pw in [
                ("backroom_units", "pw_backroom"),
                ("backroom_cube",  "pw_backroom_cube"),
            ]:
                if col_ty in df.columns and col_pw in df.columns:
                    df[col_ty] = df[col_pw]
        print(f"[BQ] INV snapshot loaded: {len(df)} rows, week={cur_week}")
        return df
    except Exception as exc:
        print(f"[BQ] INV snapshot failed ({exc}) -> sample")
        return _sample_inventory(num_weeks=1)


def fetch_oo_trend(cur_week: int, n_weeks: int = 13) -> pd.DataFrame:
    """On-order weekly trend for last N weeks."""
    if not _BQ_AVAILABLE:
        return _sample_onorder(num_weeks=n_weeks)
    from data.queries import SQL_OO_TREND
    from google.cloud import bigquery as _bq
    client = _get_client()
    job_config = _bq.QueryJobConfig(query_parameters=[
        _bq.ScalarQueryParameter("cur_week", "INT64", cur_week),
        _bq.ScalarQueryParameter("min_week", "INT64", cur_week - n_weeks + 1),
    ])
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = client.query(SQL_OO_TREND, job_config=job_config).result().to_dataframe()
        return df if not df.empty else _sample_onorder(num_weeks=n_weeks)
    except Exception as exc:
        print(f"[BQ] OO trend failed ({exc}) -> sample")
        return _sample_onorder(num_weeks=n_weeks)


def fetch_inv_trend(cur_week: int, n_weeks: int = 13) -> pd.DataFrame:
    """Inventory nodes weekly trend for last N weeks."""
    if not _BQ_AVAILABLE:
        return _sample_inventory(num_weeks=n_weeks)
    from data.queries import SQL_INV_TREND
    from google.cloud import bigquery as _bq
    client = _get_client()
    job_config = _bq.QueryJobConfig(query_parameters=[
        _bq.ScalarQueryParameter("cur_week", "INT64", cur_week),
        _bq.ScalarQueryParameter("min_week", "INT64", cur_week - n_weeks + 1),
    ])
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = client.query(SQL_INV_TREND, job_config=job_config).result().to_dataframe()
        return df if not df.empty else _sample_inventory(num_weeks=n_weeks)
    except Exception as exc:
        print(f"[BQ] INV trend failed ({exc}) -> sample")
        return _sample_inventory(num_weeks=n_weeks)


def fetch_oo_instore_l4w(cur_week: int | None = None, win: int = 2) -> pd.DataFrame:
    """
    L4W rolling average + In-Store-Date window comparison by SBU.
    win = ±weeks around cur_week for in-store window (default 2 = ±2wk).

    Returns columns:
      sbu, mabd_ty, mabd_pw, mabd_ly, l4w_avg_ty, l4w_avg_ly,
      ins_cov_pct, instore_win_ty, instore_win_ly
    """
    if not _BQ_AVAILABLE:
        # Return minimal sample data
        return pd.DataFrame()
    if cur_week is None:
        cur_week = _get_current_oo_week()
    from data.queries import SQL_OO_INSTORE_L4W
    from google.cloud import bigquery as _bq
    client = _get_client()
    job_config = _bq.QueryJobConfig(query_parameters=[
        _bq.ScalarQueryParameter("cur_week", "INT64", cur_week),
        _bq.ScalarQueryParameter("win",      "INT64", win),
    ])
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = client.query(SQL_OO_INSTORE_L4W, job_config=job_config).result().to_dataframe()
        print(f"[BQ] OO instore/L4W loaded: {len(df)} SBUs")
        return df
    except Exception as exc:
        print(f"[BQ] OO instore/L4W failed ({exc})")
        return pd.DataFrame()


# ── Utility helpers ───────────────────────────────────────────────────────────

def get_sbus(df: pd.DataFrame) -> list[str]:
    col = "sbu" if "sbu" in df.columns else "SBU"
    return sorted(df[col].dropna().unique().tolist()) if col in df.columns else SBUS


def get_depts(df: pd.DataFrame, sbu: str | None = None) -> list[str]:
    sub = df if sbu is None else df[df.get("sbu", df.get("SBU", pd.Series())) == sbu]
    return sorted(sub["OMNI_DEPT_DESC"].dropna().unique().tolist()) if "OMNI_DEPT_DESC" in sub.columns else []


# Legacy aliases kept for compatibility
def fetch_onorder_analytics() -> pd.DataFrame:
    return fetch_oo_snapshot()

def fetch_inventory_analytics() -> pd.DataFrame:
    return fetch_inv_snapshot()

def get_current_onorder_week(df: pd.DataFrame) -> int:
    return int(df["wm_week"].max()) if "wm_week" in df.columns else 12622

def get_current_inventory_week(df: pd.DataFrame) -> int:
    return int(df["WM_YR_WK_NBR"].max()) if "WM_YR_WK_NBR" in df.columns else 202622

def filter_to_week(df: pd.DataFrame, week_col: str, week: int) -> pd.DataFrame:
    return df[df[week_col] == week].copy() if week_col in df.columns else df


def get_depts(df: pd.DataFrame, sbu: str | None = None) -> list[str]:
    sub = df if sbu is None else df[df["sbu"] == sbu]
    return sorted(sub["OMNI_DEPT_DESC"].dropna().unique().tolist())
