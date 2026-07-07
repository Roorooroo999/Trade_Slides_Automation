"""
BigQuery SQL query strings for the Inventory Health Dashboard.

Two source tables:
  HIST_ONORDER  — wm_week format YYWWW  (e.g. 12622 = FY26 Wk22)  LY offset -100
  HIST_COMBINED — WM_YR_WK_NBR format YYYYWW (e.g. 202622 = 2026 Wk22) LY offset -100

Strategy:
  CURRENT_WEEK_SNAPSHOT — fast query for node cards + table (2 weeks: TY + LY)
  TREND_ONORDER         — last N weeks of on-order for trend chart
  TREND_INVENTORY       — last N weeks of inventory nodes for trend chart
"""

# ── Current WM week helpers ───────────────────────────────────────────────────

# On-order: cap to FY25–FY26 range (12500–12699) to avoid far-future MABDs
SQL_CURRENT_OO_WEEK = """
SELECT MAX(wm_week) AS cur_week
FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER`
WHERE wm_week BETWEEN 12500 AND 12699
"""

SQL_CURRENT_INV_WEEK = """
SELECT MAX(WM_YR_WK_NBR) AS cur_week
FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED`
"""

# ── On-Order snapshot: current week + LY, by SBU/Dept/Catg ──────────────────
# @cur_week = current wm_week (e.g. 12622)
SQL_OO_SNAPSHOT = """
WITH ty AS (
  SELECT
    wm_week,
    sbu,
    OMNI_DEPT_NBR, OMNI_DEPT_DESC,
    OMNI_CATG_NBR, OMNI_CATG_DESC,
    SUM(units_ordered) AS units_ordered,
    SUM(cube_ordered)  AS cube_ordered
  FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER`
  WHERE wm_week = @cur_week
    AND dsd_ind = 'NON-DSD'
  GROUP BY 1,2,3,4,5,6
),
ly AS (
  SELECT
    sbu,
    OMNI_CATG_NBR,
    SUM(units_ordered) AS ly_units_ordered,
    SUM(cube_ordered)  AS ly_cube_ordered
  FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER`
  WHERE wm_week = @cur_week - 100
    AND dsd_ind = 'NON-DSD'
  GROUP BY 1,2
),
pw AS (
  SELECT
    sbu,
    OMNI_CATG_NBR,
    SUM(units_ordered) AS pw_units_ordered,
    SUM(cube_ordered)  AS pw_cube_ordered
  FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER`
  WHERE wm_week = @cur_week - 1
    AND dsd_ind = 'NON-DSD'
  GROUP BY 1,2
),
l13w AS (
  SELECT
    sbu,
    OMNI_CATG_NBR,
    AVG(SUM(units_ordered)) OVER (
      PARTITION BY sbu, OMNI_CATG_NBR
      ORDER BY wm_week
      ROWS BETWEEN 12 PRECEDING AND CURRENT ROW
    ) AS l13w_avg_units
  FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER`
  WHERE wm_week BETWEEN @cur_week - 12 AND @cur_week
    AND dsd_ind = 'NON-DSD'
    AND sbu != 'OTHER'
  GROUP BY wm_week, sbu, OMNI_CATG_NBR
  QUALIFY ROW_NUMBER() OVER (PARTITION BY sbu, OMNI_CATG_NBR ORDER BY wm_week DESC) = 1
),
l13w_ly AS (
  SELECT
    sbu,
    OMNI_CATG_NBR,
    AVG(SUM(units_ordered)) OVER (
      PARTITION BY sbu, OMNI_CATG_NBR
      ORDER BY wm_week
      ROWS BETWEEN 12 PRECEDING AND CURRENT ROW
    ) AS l13w_avg_units_ly
  FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER`
  WHERE wm_week BETWEEN @cur_week - 112 AND @cur_week - 100
    AND dsd_ind = 'NON-DSD'
    AND sbu != 'OTHER'
  GROUP BY wm_week, sbu, OMNI_CATG_NBR
  QUALIFY ROW_NUMBER() OVER (PARTITION BY sbu, OMNI_CATG_NBR ORDER BY wm_week DESC) = 1
)
SELECT
  ty.wm_week,
  ty.sbu,
  ty.OMNI_DEPT_NBR, ty.OMNI_DEPT_DESC,
  ty.OMNI_CATG_NBR, ty.OMNI_CATG_DESC,
  ty.units_ordered,
  ty.cube_ordered,
  -- Raw prior values for correct sum-based pct calculation in Python
  pw.pw_units_ordered                  AS pw_units_ordered,
  COALESCE(pw.pw_cube_ordered, 0)      AS pw_cube_ordered,
  ly.ly_units_ordered                  AS ly_units_ordered,
  COALESCE(ly.ly_cube_ordered, 0)      AS ly_cube_ordered,
  -- L13W
  l13w.l13w_avg_units,
  l13w_ly.l13w_avg_units_ly,
  SAFE_DIVIDE(l13w.l13w_avg_units - l13w_ly.l13w_avg_units_ly, l13w_ly.l13w_avg_units_ly) AS l13w_vs_ly_pct
FROM ty
LEFT JOIN ly      ON ty.sbu = ly.sbu           AND ty.OMNI_CATG_NBR = ly.OMNI_CATG_NBR
LEFT JOIN pw      ON ty.sbu = pw.sbu           AND ty.OMNI_CATG_NBR = pw.OMNI_CATG_NBR
LEFT JOIN l13w    ON ty.sbu = l13w.sbu         AND ty.OMNI_CATG_NBR = l13w.OMNI_CATG_NBR
LEFT JOIN l13w_ly ON ty.sbu = l13w_ly.sbu      AND ty.OMNI_CATG_NBR = l13w_ly.OMNI_CATG_NBR
ORDER BY ty.sbu, ty.OMNI_DEPT_NBR, ty.OMNI_CATG_NBR
"""

# ── Combined inventory snapshot: current week + LY, by SBU/Dept/Catg ────────
# @cur_week = current WM_YR_WK_NBR (e.g. 202622)
SQL_INV_SNAPSHOT = """
WITH latest AS (
  SELECT WM_YR_WK_NBR, OMNI_CATG_NBR, MAX(BUS_DT) AS latest_dt
  FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED`
  WHERE WM_YR_WK_NBR IN (@cur_week, @cur_week - 1, @cur_week - 100)
  GROUP BY WM_YR_WK_NBR, OMNI_CATG_NBR
),
base AS (
  SELECT
    c.WM_YR_WK_NBR,
    c.OMNI_CATG_NBR, c.OMNI_CATG_DESC,
    c.OMNI_DEPT_NBR, c.OMNI_DEPT_DESC,
    c.SBU,
    SUM(c.ON_YARD_UNITS)                                                    AS on_yard_units,
    SUM(COALESCE(c.ON_YARD_TOTAL_CUBE,0))                                   AS on_yard_cube,
    SUM(c.DC_OH_UNITS + c.DC_LABELED_UNITS + c.DC_UNLABELED_UNITS + c.DC_RESERVED_UNITS) AS in_dc_units,
    SUM(COALESCE(c.DC_OH_TOTAL_CUBE,0)+COALESCE(c.DC_LBL_TOTAL_CUBE,0)+COALESCE(c.DC_UNLBL_TOTAL_CUBE,0)+COALESCE(c.DC_RESERVED_TOTAL_CUBE,0)) AS in_dc_cube,
    SUM(c.INTRANSIT_TO_DC_UNITS)                                            AS it_dc_units,
    SUM(COALESCE(c.INTRANSIT_DC_TOTAL_CUBE,0))                              AS it_dc_cube,
    SUM(c.IN_TRANSIT_UNITS)                                                 AS it_store_units,
    SUM(COALESCE(c.TRANSIT_TOTAL_CUBE,0))                                   AS it_store_cube,
    SUM(c.STORE_OH_UNITS)                                                   AS store_oh_units,
    SUM(COALESCE(c.STORE_TOTAL_CUBE,0))                                     AS store_oh_cube,
    SUM(c.BACKROOM_UNITS)                                                   AS backroom_units,
    SUM(COALESCE(c.BACKROOM_TOTAL_CUBE,0))                                  AS backroom_cube,
    SUM(c.ON_FLOOR_UNITS)                                                   AS salesfloor_units,
    SUM(c.FC_OH_UNITS)                                                      AS fc_oh_units,
    SUM(COALESCE(c.FC_TOTAL_CUBE,0))                                        AS fc_oh_cube,
    SUM(c.TOTAL_NETWORK_UNITS)                                              AS total_network_units
  FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED` c
  INNER JOIN latest l
    ON c.WM_YR_WK_NBR = l.WM_YR_WK_NBR
    AND c.OMNI_CATG_NBR = l.OMNI_CATG_NBR
    AND c.BUS_DT = l.latest_dt
  GROUP BY 1,2,3,4,5,6
),
ty  AS (SELECT * FROM base WHERE WM_YR_WK_NBR = @cur_week),
pw  AS (SELECT * FROM base WHERE WM_YR_WK_NBR = @cur_week - 1),
ly  AS (SELECT * FROM base WHERE WM_YR_WK_NBR = @cur_week - 100)
SELECT
  ty.WM_YR_WK_NBR,
  ty.sbu, ty.OMNI_DEPT_NBR, ty.OMNI_DEPT_DESC, ty.OMNI_CATG_NBR, ty.OMNI_CATG_DESC,
  -- Current week values
  ty.on_yard_units,       ty.on_yard_cube,
  ty.in_dc_units,         ty.in_dc_cube,
  ty.it_dc_units,         ty.it_dc_cube,
  ty.it_store_units,      ty.it_store_cube,
  ty.it_dc_units + ty.it_store_units  AS it_total_units,
  ty.it_dc_cube  + ty.it_store_cube   AS it_total_cube,
  ty.store_oh_units,      ty.store_oh_cube,
  ty.backroom_units,      ty.backroom_cube,
  ty.salesfloor_units,
  ty.fc_oh_units,         ty.fc_oh_cube,
  ty.total_network_units,
  -- Raw PW values — used by Python to compute correct pct after aggregation
  -- (cannot average per-row pcts; must do (sum_TY - sum_PW) / sum_PW)
  COALESCE(pw.on_yard_units, 0)       AS pw_yard,
  COALESCE(pw.in_dc_units, 0)         AS pw_dc,
  COALESCE(pw.it_dc_units, 0)         AS pw_it_dc,
  COALESCE(pw.it_store_units, 0)      AS pw_it_store,
  COALESCE(pw.store_oh_units, 0)      AS pw_store,
  COALESCE(pw.backroom_units, 0)      AS pw_backroom,
  COALESCE(pw.fc_oh_units, 0)         AS pw_fc,
  COALESCE(pw.total_network_units, 0) AS pw_total,
  COALESCE(pw.on_yard_cube, 0)        AS pw_yard_cube,
  COALESCE(pw.in_dc_cube, 0)          AS pw_dc_cube,
  COALESCE(pw.it_dc_cube, 0)          AS pw_it_dc_cube,
  COALESCE(pw.it_store_cube, 0)       AS pw_it_store_cube,
  COALESCE(pw.store_oh_cube, 0)       AS pw_store_cube,
  COALESCE(pw.backroom_cube, 0)       AS pw_backroom_cube,
  COALESCE(pw.fc_oh_cube, 0)          AS pw_fc_cube,
  -- Raw LY values
  COALESCE(ly.on_yard_units, 0)       AS ly_yard,
  COALESCE(ly.on_yard_cube, 0)        AS ly_yard_cube,
  COALESCE(ly.in_dc_units, 0)         AS ly_dc,
  COALESCE(ly.in_dc_cube, 0)          AS ly_dc_cube,
  COALESCE(ly.it_dc_units, 0)         AS ly_it_dc,
  COALESCE(ly.it_dc_cube, 0)          AS ly_it_dc_cube,
  COALESCE(ly.it_store_units, 0)      AS ly_it_store,
  COALESCE(ly.it_store_cube, 0)       AS ly_it_store_cube,
  COALESCE(ly.store_oh_units, 0)      AS ly_store,
  COALESCE(ly.store_oh_cube, 0)       AS ly_store_cube,
  COALESCE(ly.backroom_units, 0)      AS ly_backroom,
  COALESCE(ly.backroom_cube, 0)       AS ly_backroom_cube,
  COALESCE(ly.fc_oh_units, 0)         AS ly_fc,
  COALESCE(ly.fc_oh_cube, 0)          AS ly_fc_cube,
  COALESCE(ly.total_network_units, 0) AS ly_total
FROM ty
LEFT JOIN pw  ON pw.sbu  = ty.sbu AND pw.OMNI_CATG_NBR  = ty.OMNI_CATG_NBR
LEFT JOIN ly  ON ly.sbu  = ty.sbu AND ly.OMNI_CATG_NBR  = ty.OMNI_CATG_NBR
ORDER BY ty.sbu, ty.OMNI_DEPT_NBR, ty.OMNI_CATG_NBR
"""

# ── Trend: On-Order last N weeks (for trend chart) ───────────────────────────
# @cur_week, @min_week = cur_week - N + 1
SQL_OO_TREND = """
SELECT
  wm_week,
  sbu,
  OMNI_DEPT_DESC,
  SUM(units_ordered) AS units_ordered,
  SUM(cube_ordered)  AS cube_ordered
FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER`
WHERE wm_week BETWEEN @min_week AND @cur_week
  AND dsd_ind = 'NON-DSD'
GROUP BY 1,2,3
ORDER BY 1,2,3
"""

# ── Trend: Inventory nodes last N weeks ──────────────────────────────────────
# @cur_week, @min_week = cur_week - N + 1
SQL_INV_TREND = """
WITH latest AS (
  SELECT WM_YR_WK_NBR, OMNI_CATG_NBR, MAX(BUS_DT) AS latest_dt
  FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED`
  WHERE WM_YR_WK_NBR BETWEEN @min_week AND @cur_week
  GROUP BY WM_YR_WK_NBR, OMNI_CATG_NBR
)
SELECT
  c.WM_YR_WK_NBR,
  c.SBU,
  c.OMNI_DEPT_DESC,
  SUM(c.ON_YARD_UNITS)                                                    AS on_yard_units,
  SUM(c.DC_OH_UNITS+c.DC_LABELED_UNITS+c.DC_UNLABELED_UNITS+c.DC_RESERVED_UNITS) AS in_dc_units,
  SUM(c.INTRANSIT_TO_DC_UNITS)                                            AS it_dc_units,
  SUM(c.IN_TRANSIT_UNITS)                                                 AS it_store_units,
  SUM(c.INTRANSIT_TO_DC_UNITS + c.IN_TRANSIT_UNITS)                      AS it_total_units,
  SUM(c.STORE_OH_UNITS)                                                   AS store_oh_units,
  SUM(c.BACKROOM_UNITS)                                                   AS backroom_units,
  SUM(c.ON_FLOOR_UNITS)                                                   AS salesfloor_units,
  SUM(c.FC_OH_UNITS)                                                      AS fc_oh_units,
  SUM(c.TOTAL_NETWORK_UNITS)                                              AS total_network_units
FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED` c
INNER JOIN latest l
  ON c.WM_YR_WK_NBR = l.WM_YR_WK_NBR
  AND c.OMNI_CATG_NBR = l.OMNI_CATG_NBR
  AND c.BUS_DT = l.latest_dt
GROUP BY 1,2,3
ORDER BY 1,2,3
"""

# ── On-Order: L4W Rolling Average + In-Store-Date View ───────────────────────
# @cur_week = current wm_week (YYWWW, e.g. 12622)
# @win      = ±weeks around cur_week for in-store window (use 2 for ±2wk)
#
# Why L4W?  Single-week MABD views are noisy (import PO timing shifts
#            all land in one week).  L4W rolling avg smooths this out.
# Why In-Store?  Only populated for ~15-52% of units by SBU (domestic POs).
#                 Use ins_cov_pct to judge reliability per SBU.
SQL_OO_INSTORE_L4W = """
SELECT
  sbu,
  -- Current MABD week
  SUM(CASE WHEN wm_week = @cur_week       THEN units_ordered ELSE 0 END) AS mabd_ty,
  SUM(CASE WHEN wm_week = @cur_week - 1   THEN units_ordered ELSE 0 END) AS mabd_pw,
  SUM(CASE WHEN wm_week = @cur_week - 100 THEN units_ordered ELSE 0 END) AS mabd_ly,
  -- L4W rolling avg (last 4 MABD weeks TY vs same window LY)
  SUM(CASE WHEN wm_week BETWEEN @cur_week - 3     AND @cur_week
           THEN units_ordered ELSE 0 END) / 4      AS l4w_avg_ty,
  SUM(CASE WHEN wm_week BETWEEN @cur_week - 103   AND @cur_week - 100
           THEN units_ordered ELSE 0 END) / 4      AS l4w_avg_ly,
  -- In-Store date coverage % (of MABD cur_week units)
  SAFE_DIVIDE(
    SUM(CASE WHEN wm_week = @cur_week AND in_store_wm_week IS NOT NULL
             THEN units_ordered ELSE 0 END),
    NULLIF(SUM(CASE WHEN wm_week = @cur_week
                    THEN units_ordered ELSE 0 END), 0)
  ) * 100                                           AS ins_cov_pct,
  -- In-Store ±win week window TY vs LY
  SUM(CASE WHEN in_store_wm_week BETWEEN @cur_week - @win
                                     AND @cur_week + @win
           THEN units_ordered ELSE 0 END)           AS instore_win_ty,
  SUM(CASE WHEN in_store_wm_week BETWEEN @cur_week - 100 - @win
                                     AND @cur_week - 100 + @win
           THEN units_ordered ELSE 0 END)           AS instore_win_ly
FROM `wmt-execution-intel-prod.WM_AD_HOC.R0C0JUG_WMUS_HIST_ONORDER`
WHERE wm_week BETWEEN @cur_week - 103 AND @cur_week
  AND dsd_ind = 'NON-DSD'
  AND sbu != 'OTHER'
GROUP BY sbu
ORDER BY mabd_ty DESC
"""
