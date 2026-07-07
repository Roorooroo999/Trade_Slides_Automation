"""
capture_buildburn.py
Builds a Store Build/Burn waterfall chart from HIST_COMBINED BQ data,
screenshots it via Chrome headless, and saves buildburn_chart.png.

Usage:  python capture_buildburn.py
Output: buildburn_chart.png  (ready to embed in PPTX slide 2)
"""

import json, os, subprocess, sys, tempfile, warnings
from datetime import datetime

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────
CHROME   = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
OUT_PNG  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "buildburn_chart.png")
PROJECT  = "wmt-execution-intel-prod"
BQ_TABLE = f"`{PROJECT}.WM_AD_HOC.R0C0JUG_WMUS_HIST_COMBINED`"
WIN_W, WIN_H = 1400, 820

# ── BQ query: weekly Store OH (WK01–current + LY) ────────────────────────────
SQL = """
WITH snap AS (
  SELECT WM_YR_WK_NBR, OMNI_CATG_NBR, MAX(BUS_DT) dt
  FROM {tbl}
  WHERE WM_YR_WK_NBR BETWEEN {fy_start} AND {fy_end}
  GROUP BY 1,2
),
snap_ly AS (
  SELECT WM_YR_WK_NBR, OMNI_CATG_NBR, MAX(BUS_DT) dt
  FROM {tbl}
  WHERE WM_YR_WK_NBR BETWEEN {ly_start} AND {ly_end}
  GROUP BY 1,2
)
SELECT c.WM_YR_WK_NBR AS wk,
       CAST(SUM(c.STORE_OH_UNITS) AS FLOAT64) AS store_oh
FROM {tbl} c
INNER JOIN snap s ON c.WM_YR_WK_NBR=s.WM_YR_WK_NBR
  AND c.OMNI_CATG_NBR=s.OMNI_CATG_NBR AND c.BUS_DT=s.dt
GROUP BY 1
UNION ALL
SELECT c.WM_YR_WK_NBR AS wk,
       CAST(SUM(c.STORE_OH_UNITS) AS FLOAT64) AS store_oh
FROM {tbl} c
INNER JOIN snap_ly s ON c.WM_YR_WK_NBR=s.WM_YR_WK_NBR
  AND c.OMNI_CATG_NBR=s.OMNI_CATG_NBR AND c.BUS_DT=s.dt
GROUP BY 1
ORDER BY 1
"""

def _bq(sql):
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=PROJECT)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = client.query(sql).result().to_dataframe()
        return df
    except Exception as e:
        print(f"[BQ] Error: {e}")
        return None


def _get_data():
    """Pull weekly Store OH for FY2026 WK01-WK26 and FY2025 WK01-WK26."""
    fy_start, fy_end = 202601, 202626
    ly_start, ly_end = 202501, 202526
    sql = SQL.format(tbl=BQ_TABLE,
                     fy_start=fy_start, fy_end=fy_end,
                     ly_start=ly_start, ly_end=ly_end)
    df = _bq(sql)
    if df is None or df.empty:
        return None, None

    ty = df[df["wk"].between(fy_start, fy_end)].sort_values("wk")
    ly = df[df["wk"].between(ly_start, ly_end)].sort_values("wk")

    # Week label: e.g. 202601 → "Wk 1"
    def wk_label(w): return f"Wk {int(str(w)[4:])}"

    ty["label"] = ty["wk"].apply(wk_label)
    ly["label"] = ly["wk"].apply(wk_label)

    return ty, ly


def _build_html(ty, ly):
    """Generate self-contained Plotly HTML for the Build/Burn waterfall chart."""

    # Compute WoW deltas (build = positive, burn = negative)
    vals      = ty["store_oh"].tolist()
    labels    = ty["label"].tolist()
    ly_vals   = ly["store_oh"].tolist() if ly is not None else []
    ly_labels = ly["label"].tolist()    if ly is not None else []

    start_inv = vals[0] if vals else 0
    deltas = [vals[i] - vals[i-1] for i in range(1, len(vals))]
    bar_colors = ["#b22222" if d >= 0 else "#2e7d32" for d in deltas]
    bar_text   = [f"{'+' if d>=0 else ''}{d/1e6:.0f}M" for d in deltas]

    # Running total for the line trace
    cumulative = [start_inv] + [start_inv + sum(deltas[:i+1]) for i in range(len(deltas))]
    line_labels = labels

    # LY line
    ly_line = ly_vals if ly_vals else []

    # Current week (last actual)
    cur_wk_idx = len(vals) - 1

    trace_bars = {
        "type": "bar",
        "x": labels[1:],
        "y": [d/1e6 for d in deltas],
        "marker": {"color": bar_colors},
        "text": bar_text,
        "textposition": "outside",
        "name": "WoW Delta (M units)",
        "yaxis": "y2",
        "showlegend": True,
    }

    trace_ty = {
        "type": "scatter",
        "x": line_labels,
        "y": [v/1e9 for v in cumulative],
        "mode": "lines+markers",
        "line": {"color": "#111", "width": 2},
        "marker": {"size": 5, "color": "#111"},
        "name": f"TY FY26 Store OH (B)",
        "yaxis": "y",
    }

    trace_ly = {
        "type": "scatter",
        "x": ly_labels,
        "y": [v/1e9 for v in ly_line],
        "mode": "lines",
        "line": {"color": "#888", "width": 1.5, "dash": "dot"},
        "name": "LY FY25 Store OH (B)",
        "yaxis": "y",
    } if ly_line else None

    # Add vertical dashed line at current week
    cur_wk_label = labels[cur_wk_idx] if cur_wk_idx < len(labels) else labels[-1]

    data = [trace_ty]
    if trace_ly:
        data.append(trace_ly)
    data.append(trace_bars)

    layout = {
        "title": {
            "text": f"Store Build/Burn — FY26 WK01–WK26 vs FY25 (WoW deltas + trajectory)",
            "font": {"size": 16, "family": "Walmart Sans, Arial"},
        },
        "xaxis": {"title": "", "tickfont": {"size": 10}},
        "yaxis":  {"title": "Store OH (B units)", "side": "left",  "showgrid": True},
        "yaxis2": {"title": "WoW Delta (M units)", "side": "right", "overlaying": "y",
                   "showgrid": False, "zeroline": True},
        "shapes": [{
            "type": "line", "x0": cur_wk_label, "x1": cur_wk_label,
            "y0": 0, "y1": 1, "yref": "paper",
            "line": {"color": "#003087", "width": 2, "dash": "dash"},
        }],
        "annotations": [{
            "x": cur_wk_label, "y": 1.02, "yref": "paper", "xref": "x",
            "text": "← Actual | Projected →",
            "showarrow": False, "font": {"size": 10, "color": "#003087"},
        }],
        "legend": {"orientation": "h", "y": -0.15},
        "plot_bgcolor": "white",
        "paper_bgcolor": "white",
        "margin": {"t": 60, "b": 80, "l": 70, "r": 70},
        "height": 600,
    }

    return {"data": data, "layout": layout}


def _export_png_kaleido(fig_dict, out_png):
    """Export Plotly figure to PNG using kaleido — works on Linux (Posit Connect)."""
    import plotly.graph_objects as go
    fig = go.Figure(fig_dict)
    fig.write_image(out_png, width=WIN_W, height=WIN_H, scale=1.5)
    if os.path.exists(out_png) and os.path.getsize(out_png) > 5000:
        print(f"[Chart] kaleido PNG saved: {out_png} ({os.path.getsize(out_png):,} bytes)")
        return True
    return False


def _export_png_chrome(fig_dict, out_png):
    """Export via Chrome headless — works on Windows."""
    html_str = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script></head>
<body style="margin:0;background:white">
<div id="chart" style="width:{WIN_W}px;height:{WIN_H}px"></div>
<script>
Plotly.newPlot('chart', {json.dumps(fig_dict['data'])}, {json.dumps(fig_dict['layout'])},
  {{displayModeBar:false,staticPlot:true}});
</script></body></html>"""

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html_str); tmp = f.name

    url = f"file:///{tmp.replace(os.sep, '/')}"
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
           f"--screenshot={out_png}", f"--window-size={WIN_W},{WIN_H}",
           "--run-all-compositor-stages-before-draw", "--virtual-time-budget=5000", url]
    print(f"[Chart] Running Chrome headless...")
    subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    os.unlink(tmp)

    if os.path.exists(out_png) and os.path.getsize(out_png) > 5000:
        print(f"[Chart] Chrome PNG saved: {out_png} ({os.path.getsize(out_png):,} bytes)")
        return True
    print("[Chart] Chrome screenshot failed")
    return False


def _render_png(fig_dict, out_png):
    """Auto-detect best renderer: kaleido on Linux, Chrome on Windows."""
    import sys
    if sys.platform != "win32":
        # Posit Connect / Linux — use kaleido
        try:
            return _export_png_kaleido(fig_dict, out_png)
        except Exception as e:
            print(f"[Chart] kaleido failed: {e}")
            return False
    else:
        # Windows — try kaleido first, fall back to Chrome
        try:
            return _export_png_kaleido(fig_dict, out_png)
        except Exception:
            return _export_png_chrome(fig_dict, out_png)


def capture(out_png=OUT_PNG):
    """Main entry: pull BQ data → build chart HTML → Chrome screenshot → PNG."""
    print("[Chart] Pulling Store OH data from BigQuery...")
    ty, ly = _get_data()

    if ty is None or ty.empty:
        print("[Chart] No BQ data — cannot build chart")
        return False

    print(f"[Chart] Got {len(ty)} TY weeks, {len(ly) if ly is not None else 0} LY weeks")
    fig_dict = _build_html(ty, ly)
    return _render_png(fig_dict, out_png)


if __name__ == "__main__":
    ok = capture()
    sys.exit(0 if ok else 1)
