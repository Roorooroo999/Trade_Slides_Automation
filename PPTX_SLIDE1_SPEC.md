# Trade Slides – Slide 1 Field Specification & Update Logic
_Source of truth for dashboard, PPTX download, and talk track PDF_

---

## Data Sources

| Table | Week Format | LY Offset | Notes |
|---|---|---|---|
| `HIST_COMBINED` | `WM_YR_WK_NBR` = YYYYWW (e.g. 202623) | -100 | All inventory nodes |
| `HIST_ONORDER` | `wm_week` = YYWWW (e.g. 12623) | -100 | On-Order only, NON-DSD only |

**Week conversion**: `YYYYWW → YYWWW` = `10000 + (YYYY-2000)*100 + WW`  
**Prior week (WoW)**: `wm_week - 1` for OO, `WM_YR_WK_NBR - 1` for HIST_COMBINED  
**LY week**: `wm_week - 100` for OO, `WM_YR_WK_NBR - 100` for HIST_COMBINED

---

## Summary Banner (TextBox 9)

```
6 buckets · TY X.XX B vs LY X.XX B · X.X%, X.XX B YoY · X.XX B store inv · X.X%, XXX M YoY
```

| Sub-field | Formula |
|---|---|
| TY total | `SUM(TOTAL_NETWORK_UNITS) + SUM(units_ordered)` |
| LY total | `SUM(ly_total) + SUM(ly_units_ordered)` |
| Store inv TY | `SUM(STORE_OH_UNITS)` |
| Store inv LY | `SUM(ly_store)` |

---

## Bucket 1 — ON ORDER (FACTORY) · NON-DSD only · MABD WK{current}

| Display Field | BQ Column | Formula | Shape |
|---|---|---|---|
| Total units | `units_ordered` | `SUM(units_ordered)` | TextBox 19 |
| vs LY % | `ly_units_ordered` | `(TY - LY) / LY` | TextBox 20 para 1 |
| vs LW % | `pw_units_ordered` | `(TY - PW) / PW` | TextBox 20 para 2 |
| L13W avg/wk | `l13w_avg_units` | `SUM(units 13wks) / 13` | TextBox 25 |
| L13W vs LY % | `l13w_avg_units_ly` | `(L13W_TY - L13W_LY) / L13W_LY` | TextBox 25 |
| Total cube ft³ | `cube_ordered` | `SUM(cube_ordered)` | ⚠️ NOT MAPPED |
| Cube vs LY % | `ly_cube_ordered` | `(TY_cube - LY_cube) / LY_cube` | ⚠️ NOT MAPPED |

**Business rules**:
- Filter: `dsd_ind = 'NON-DSD'`, exclude `sbu = 'OTHER'` for L13W
- LY week = current OO week - 100
- L13W window TY: `wm_week BETWEEN cur-12 AND cur`
- L13W window LY: `wm_week BETWEEN cur-112 AND cur-100`
- MABD label = current `wm_week % 100` (e.g. WK23)

---

## Bucket 2 — ON YARD (YARD – RDC & FDC)

| Display Field | BQ Column | Formula | Shape |
|---|---|---|---|
| Total units | `on_yard_units` | `SUM(ON_YARD_UNITS)` | TextBox 35 |
| vs LY % | `ly_yard` | `(TY - LY) / LY` | TextBox 36 |
| vs LW % | `pw_yard` | `(TY - PW) / PW` | TextBox 21 |
| Cube ft³ | `on_yard_cube` | `SUM(ON_YARD_TOTAL_CUBE)` | ⚠️ NOT MAPPED |
| Cube vs LY % | `ly_yard_cube` | `(TY_cube - LY_cube) / LY_cube` | ⚠️ NOT MAPPED |

**Business rules**:
- On Yard can be very small (<1M) → displays as "0.0 M" when < 500K units (correct)
- Units displayed as `X.X M` format (1 decimal), not rounded integer like other nodes

---

## Bucket 3 — IN DC (WAREHOUSE)

| Display Field | BQ Column | Formula | Shape |
|---|---|---|---|
| Total units | `in_dc_units` | `SUM(DC_OH + DC_LABELED + DC_UNLABELED + DC_RESERVED)` | TextBox 51 |
| vs LY % | `ly_dc` | `(TY - LY) / LY` | TextBox 52 |
| vs LW % | `pw_dc` | `(TY - PW) / PW` | TextBox 24 |
| Cube ft³ | `in_dc_cube` | `SUM(all DC cube columns)` | ⚠️ NOT MAPPED |
| Cube vs LY % | `ly_dc_cube` | `(TY_cube - LY_cube) / LY_cube` | ⚠️ NOT MAPPED |

**Business rules**:
- DC definition = `DC_OH_UNITS + DC_LABELED_UNITS + DC_UNLABELED_UNITS + DC_RESERVED_UNITS`
- This is the FULL DC inventory (not just OH)

---

## Bucket 4 — IN TRANSIT (total + breakdown)

### IT Total
| Display Field | BQ Column | Formula | Shape |
|---|---|---|---|
| Total units | computed | `it_store + it_dc` | TextBox 1034 |
| vs LY % | `ly_it_store + ly_it_dc` | `(TY - LY) / LY` | TextBox 1036 |
| vs LW % | `pw_it_store + pw_it_dc` | `(TY - PW) / PW` | TextBox 1037 |
| Cube ft³ | `it_total_cube` | `it_dc_cube + it_store_cube` | ⚠️ NOT MAPPED |
| Cube vs LY % | computed | `(TY_cube - LY_cube) / LY_cube` | ⚠️ NOT MAPPED |

### IT → DC (INTRANSIT_TO_DC)
| Display Field | BQ Column | Formula | Shape |
|---|---|---|---|
| Units | `it_dc_units` | `SUM(INTRANSIT_TO_DC_UNITS)` | TextBox 1039 |
| vs LY % | `ly_it_dc` | `(TY - LY) / LY` | TextBox 1040 |
| vs LW % | `pw_it_dc` | `(TY - PW) / PW` | TextBox 1041 |
| Cube ft³ | `it_dc_cube` | `SUM(INTRANSIT_DC_TOTAL_CUBE)` | ⚠️ NOT MAPPED |
| Cube vs LY % | `ly_it_dc_cube` | `(TY_cube - LY_cube) / LY_cube` | ⚠️ NOT MAPPED |

### IT → Store (IN_TRANSIT)
| Display Field | BQ Column | Formula | Shape |
|---|---|---|---|
| Units | `it_store_units` | `SUM(IN_TRANSIT_UNITS)` | TextBox 1042 |
| vs LY % | `ly_it_store` | `(TY - LY) / LY` | TextBox 1043 |
| vs LW % | `pw_it_store` | `(TY - PW) / PW` | TextBox 1044 |
| Cube ft³ | `it_store_cube` | `SUM(TRANSIT_TOTAL_CUBE)` | ⚠️ NOT MAPPED |
| Cube vs LY % | `ly_it_store_cube` | `(TY_cube - LY_cube) / LY_cube` | ⚠️ NOT MAPPED |

---

## Bucket 5 — STORE (Store OH + Backroom + Salesfloor)

### Store OH
| Display Field | BQ Column | Formula | Shape |
|---|---|---|---|
| Units | `store_oh_units` | `SUM(STORE_OH_UNITS)` | TextBox 178 |
| vs LY % | `ly_store` | `(TY - LY) / LY` | TextBox 184 |
| vs LW % | `pw_store` | `(TY - PW) / PW` | TextBox 185 |
| Cube ft³ | `store_oh_cube` | `SUM(STORE_TOTAL_CUBE)` | ⚠️ NOT MAPPED |
| Cube vs LY % | `ly_store_cube` | `(TY_cube - LY_cube) / LY_cube` | ⚠️ NOT MAPPED |

### Backroom
| Display Field | BQ Column | Formula | Shape |
|---|---|---|---|
| Units | `backroom_units` | `SUM(BACKROOM_UNITS)` | TextBox 188 |
| vs LY % | `ly_backroom` | `(TY - LY) / LY` | TextBox 189 |
| vs LW % | `pw_backroom` | `(TY - PW) / PW` | TextBox 190 |
| Cube ft³ | `backroom_cube` | `SUM(BACKROOM_TOTAL_CUBE)` | ⚠️ NOT MAPPED |
| Cube vs LY % | `ly_backroom_cube` | `(TY_cube - LY_cube) / LY_cube` | ⚠️ NOT MAPPED |

**⚠️ Known pipeline issue**: `BACKROOM_UNITS` for the current week may be 0 until mid-week (pipeline loads late).  
**Fallback**: If `backroom_units == 0` AND `pw_backroom > 0`, substitute prior week values. Implemented in `data/bq.py → fetch_inv_snapshot()`.

### Salesfloor
| Display Field | Formula | Shape |
|---|---|---|
| Units | `store_oh_units - backroom_units` | TextBox 1028 |
| vs LY % | `(sf_ty - sf_ly) / sf_ly` | TextBox 1030 |
| vs LW % | `(sf_ty - sf_pw) / sf_pw` | TextBox 1032 |
| Cube ft³ | `store_oh_cube - backroom_cube` | ⚠️ NOT MAPPED |
| Cube vs LY % | computed difference | ⚠️ NOT MAPPED |

**Business rule**: Salesfloor = Store OH − Backroom (identity, ensures reconciliation).  
Do NOT use `ON_FLOOR_UNITS` directly (excludes orphan backroom rows).

---

## Bucket 6 — FC

| Display Field | BQ Column | Formula | Shape |
|---|---|---|---|
| Units | `fc_oh_units` | `SUM(FC_OH_UNITS)` | TextBox 117 |
| vs LY % | `ly_fc` | `(TY - LY) / LY` | TextBox 118 |
| vs LW % | `pw_fc` | `(TY - PW) / PW` | TextBox 40 |
| Cube ft³ | `fc_oh_cube` | `SUM(FC_TOTAL_CUBE)` | ⚠️ NOT MAPPED |
| Cube vs LY % | `ly_fc_cube` | `(TY_cube - LY_cube) / LY_cube` | ⚠️ NOT MAPPED |

---

## Insights Section (Rounded Rectangle 10)

| Bullet | Content | Source |
|---|---|---|
| Headline 1 | Bold — weekly narrative headline | Hardcoded weekly, update manually |
| Body 1 | OO, DC, IT→Store values with YoY | Auto-generated from live data |
| Headline 2 | Bold — "X M in backroom (Y% vs LY)" | Auto-generated from live data |
| Body 2 | Salesfloor, backroom pull narrative | Auto-generated from live data |

---

## Cube Shape Map (discovered Jul 7 2026)

| Shape Name | Node | BQ Column TY | BQ Column LY |
|---|---|---|---|
| TextBox 183 | OO (Factory) cube | `cube_ordered` (OO df) | `ly_cube_ordered` |
| TextBox 181 | On Yard cube | `on_yard_cube` | `ly_yard_cube` |
| TextBox 180 | In DC cube | `in_dc_cube` | `ly_dc_cube` |
| TextBox 1038 | IT Total cube | `it_store_cube + it_dc_cube` | `ly_it_store_cube + ly_it_dc_cube` |
| TextBox 54 | IT→DC cube | `it_dc_cube` | `ly_it_dc_cube` |
| TextBox 34 | IT→Store cube | `it_store_cube` | `ly_it_store_cube` |
| TextBox 179 | Store OH cube | `store_oh_cube` | `ly_store_cube` |
| TextBox 41 | Backroom cube | `backroom_cube` | `ly_backroom_cube` |
| TextBox 50 | Salesfloor cube | `store_oh_cube - backroom_cube` | `ly_store_cube - ly_backroom_cube` |
| TextBox 3 | FC cube | `fc_oh_cube` | `ly_fc_cube` |

All cube fields now implemented in `app.py → _update_slide1()` using `sc(value, pct)` helper.

---

## Format Rules

| Type | Format | Example |
|---|---|---|
| Units ≥ 1,000M | `X,XXX M` | `1,344 M` |
| Units < 1,000M | `XXX M` | `419 M` |
| Units On Yard | `X.X M` (1 decimal) | `0.3 M` |
| % positive | `+X.X% vs LY` | `+2.7% vs LY` |
| % negative | `(X.X%) vs LY` | `(7.5%) vs LY` |
| L13W | `XXXM/wk (+X.X% YoY)` | `1,366M/wk (+1.3% YoY)` |
| Cube combined | `XXX M ft³, +X.X% vs. LY` | `321 M ft³, -21.1% vs. LY` |

---

## Known Gaps vs "Where Is My Stuff" Dashboard (validated Jul 7 2026)

| Node | Our Value | WMS Value | Gap | Root Cause |
|---|---|---|---|---|
| In DC | 1,933M (4-comp) | 1,910M | -23M | WMS may exclude certain SBU/DC types |
| IT→Store | 145M | 130.5M | -14.5M | WMS likely excludes FC/eComm transit |
| On Floor | 4,655M | 4,630M | -25M | WMS applies additional SBU scope filter |
| OO WoW | -8.5% | +9.7% | opposite sign | Different definition: we compare MABD WK vs WK; WMS compares total open position WoW |

**Our numbers are correct per HIST_COMBINED spec.** Gaps trace to WMS applying additional filters not visible in raw HIST_COMBINED. FC and On-Order match closely when compared on same basis.

---

## Weekly Refresh Checklist

- [ ] Run `weekly_refresh.bat` (generates PDF + PPTX + restarts dashboard)
- [ ] Verify `backroom_units > 0` in log (or confirm pipeline pending note)
- [ ] Check On Yard — if < 500K it shows as "0.0 M" (correct, not a bug)
- [ ] Update Insights bullet 1 headline manually (weekly narrative)
- [ ] Rename saved template to exactly `pptx_template.pptx` (no double extension)
- [ ] Open dashboard in **Chrome/Edge** (not VS Code browser) to use download button
