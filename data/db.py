"""
Snowflake data connector for Inventory Health Dashboard.

Set environment variables (or populate .env):
    SNOWFLAKE_ACCOUNT   e.g. walmart.us-east-1
    SNOWFLAKE_USER
    SNOWFLAKE_PASSWORD
    SNOWFLAKE_DATABASE
    SNOWFLAKE_SCHEMA
    SNOWFLAKE_WAREHOUSE
    SNOWFLAKE_ROLE      (optional)

If credentials are not set, the module falls back to SAMPLE data so the
app renders immediately during development.
"""

import os
import random
from datetime import date, timedelta

import pandas as pd

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
_SNOWFLAKE_AVAILABLE = False
try:
    from sqlalchemy import create_engine, text as sa_text

    _CREDS = {
        "account":   os.getenv("SNOWFLAKE_ACCOUNT", ""),
        "user":      os.getenv("SNOWFLAKE_USER", ""),
        "password":  os.getenv("SNOWFLAKE_PASSWORD", ""),
        "database":  os.getenv("SNOWFLAKE_DATABASE", ""),
        "schema":    os.getenv("SNOWFLAKE_SCHEMA", ""),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", ""),
        "role":      os.getenv("SNOWFLAKE_ROLE", ""),
    }
    _SNOWFLAKE_AVAILABLE = all(
        _CREDS[k] for k in ("account", "user", "password", "database", "schema", "warehouse")
    )
except ImportError:
    pass


def _get_engine():
    from sqlalchemy import create_engine
    conn_str = (
        f"snowflake://{_CREDS['user']}:{_CREDS['password']}"
        f"@{_CREDS['account']}/{_CREDS['database']}/{_CREDS['schema']}"
        f"?warehouse={_CREDS['warehouse']}"
    )
    if _CREDS["role"]:
        conn_str += f"&role={_CREDS['role']}"
    return create_engine(conn_str)


# ---------------------------------------------------------------------------
# Sample / fallback data
# ---------------------------------------------------------------------------
DEPARTMENTS = [
    "Food",
    "Consumables",
    "Fashion",
    "ETS / Electronics",
    "Hardlines",
    "Home",
]

random.seed(42)


def _sample_summary(as_of: date) -> pd.DataFrame:
    """Generate realistic-looking inventory summary for development."""
    rows = []
    for dept in DEPARTMENTS:
        onhand      = random.randint(400_000, 3_000_000)
        it_dc       = random.randint(50_000, 400_000)
        it_store    = random.randint(20_000, 200_000)
        on_order    = random.randint(100_000, 800_000)
        cube_value  = round(random.uniform(2_000_000, 25_000_000), 0)
        wow_pct     = round(random.uniform(-0.08, 0.10), 4)
        yoy_pct     = round(random.uniform(-0.15, 0.20), 4)
        rows.append({
            "department":        dept,
            "on_hand_units":     onhand,
            "in_transit_dc":     it_dc,
            "in_transit_store":  it_store,
            "on_order_units":    on_order,
            "cube_value":        cube_value,
            "wow_units_chg_pct": wow_pct,
            "yoy_units_chg_pct": yoy_pct,
        })
    df = pd.DataFrame(rows)
    df["in_transit_total"] = df["in_transit_dc"] + df["in_transit_store"]
    return df


def _sample_trend(days: int) -> pd.DataFrame:
    """Daily trend data for the last `days` calendar days."""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    rows = []
    for d in dates:
        for dept in DEPARTMENTS:
            rows.append({
                "report_date":      d,
                "department":       dept,
                "on_hand_units":    random.randint(400_000, 3_000_000),
                "in_transit_dc":    random.randint(50_000, 400_000),
                "in_transit_store": random.randint(20_000, 200_000),
                "on_order_units":   random.randint(100_000, 800_000),
            })
    df = pd.DataFrame(rows)
    df["in_transit_total"] = df["in_transit_dc"] + df["in_transit_store"]
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# ── Snowflake SQL templates (edit to match your schema) ──────────────────────
_SQL_SUMMARY = """
SELECT
    dept_nm                                      AS department,
    SUM(on_hand_qty)                             AS on_hand_units,
    SUM(CASE WHEN node_type = 'DC' THEN in_transit_qty ELSE 0 END)    AS in_transit_dc,
    SUM(CASE WHEN node_type = 'STORE' THEN in_transit_qty ELSE 0 END) AS in_transit_store,
    SUM(in_transit_qty)                          AS in_transit_total,
    SUM(on_order_qty)                            AS on_order_units,
    SUM(total_cube_value)                        AS cube_value,
    (SUM(on_hand_qty) - SUM(prior_week_on_hand_qty))
        / NULLIF(SUM(prior_week_on_hand_qty), 0) AS wow_units_chg_pct,
    (SUM(on_hand_qty) - SUM(prior_year_on_hand_qty))
        / NULLIF(SUM(prior_year_on_hand_qty), 0) AS yoy_units_chg_pct
FROM your_schema.inventory_node_snapshot     -- ← replace with your table
WHERE report_date = :as_of_date
GROUP BY dept_nm
ORDER BY dept_nm
"""

_SQL_TREND = """
SELECT
    report_date,
    dept_nm                      AS department,
    SUM(on_hand_qty)             AS on_hand_units,
    SUM(CASE WHEN node_type = 'DC'    THEN in_transit_qty ELSE 0 END) AS in_transit_dc,
    SUM(CASE WHEN node_type = 'STORE' THEN in_transit_qty ELSE 0 END) AS in_transit_store,
    SUM(in_transit_qty)          AS in_transit_total,
    SUM(on_order_qty)            AS on_order_units
FROM your_schema.inventory_node_snapshot     -- ← replace with your table
WHERE report_date >= :start_date
  AND report_date <= :end_date
GROUP BY report_date, dept_nm
ORDER BY report_date, dept_nm
"""


def fetch_inventory_summary(as_of: date | None = None) -> pd.DataFrame:
    """Return per-department inventory snapshot for a given date."""
    if as_of is None:
        as_of = date.today()

    if not _SNOWFLAKE_AVAILABLE:
        return _sample_summary(as_of)

    engine = _get_engine()
    with engine.connect() as conn:
        df = pd.read_sql(
            sa_text(_SQL_SUMMARY),
            conn,
            params={"as_of_date": str(as_of)},
        )
    return df


def fetch_trend_data(days: int = 30, dept_filter: str | None = None) -> pd.DataFrame:
    """Return daily trend rows for the last `days` days."""
    end   = date.today()
    start = end - timedelta(days=days - 1)

    if not _SNOWFLAKE_AVAILABLE:
        df = _sample_trend(days)
    else:
        engine = _get_engine()
        with engine.connect() as conn:
            df = pd.read_sql(
                sa_text(_SQL_TREND),
                conn,
                params={"start_date": str(start), "end_date": str(end)},
            )

    if dept_filter and dept_filter != "All Departments":
        df = df[df["department"] == dept_filter]

    return df


def get_departments() -> list[str]:
    """Return list of department names."""
    return DEPARTMENTS
