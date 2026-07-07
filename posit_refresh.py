"""
posit_refresh.py
Weekly refresh job for Posit Connect.

Deploy this as a separate Posit Connect content item (type: Script)
and schedule it for every Wednesday at 07:00.

It will:
  1. Capture the Build/Burn chart using kaleido (no Chrome needed on Linux)
  2. Update the PPTX template (slide 1 metrics + slide 2 chart)
  3. Save buildburn_chart.png and updated pptx_template.pptx in the app directory
     so the next PPTX download picks up the fresh chart automatically

Note: The dashboard app itself handles BQ data refresh every 4 hours (Wed-Sat).
This job only refreshes the static outputs (chart PNG + PPTX template).
"""
import os, sys, datetime, warnings
warnings.filterwarnings("ignore")

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def main():
    log("=" * 55)
    log("POSIT WEEKLY REFRESH STARTED")
    log("=" * 55)

    # ── Step 1: Build/Burn chart (kaleido on Linux) ───────────────────────────
    log("Step 1: Capturing Build/Burn chart...")
    try:
        import capture_buildburn
        chart_png = os.path.join(DIR, "buildburn_chart.png")
        ok = capture_buildburn.capture(out_png=chart_png)
        if ok:
            log(f"  Chart saved: {os.path.getsize(chart_png):,} bytes")
        else:
            log("  [WARN] Chart capture failed — will use existing PNG if available")
    except Exception as e:
        log(f"  [WARN] Chart error: {e}")

    # ── Step 2: Update PPTX template with latest BQ numbers ───────────────────
    log("Step 2: Updating PPTX template with live BQ data...")
    try:
        from data.bq import fetch_inv_snapshot, fetch_oo_snapshot, _get_current_oo_week
        import io
        from pptx import Presentation
        from dotenv import load_dotenv
        load_dotenv(os.path.join(DIR, ".env"))

        inv = fetch_inv_snapshot()
        oo  = fetch_oo_snapshot()
        cur_wk = int(oo["wm_week"].max()) if "wm_week" in oo.columns else _get_current_oo_week()

        template = os.path.join(DIR, "pptx_template.pptx")
        if not os.path.exists(template):
            log("  No pptx_template.pptx — skipping PPTX update")
        else:
            import app as _app
            with open(template, "rb") as f:
                prs = Presentation(io.BytesIO(f.read()))
            prs = _app._update_slide1(prs, inv, oo, cur_wk)
            prs = _app._update_slide2_chart(prs)

            # Save updated template back in place
            buf = io.BytesIO()
            prs.save(buf)
            buf.seek(0)
            with open(template, "wb") as f:
                f.write(buf.read())
            log(f"  PPTX template updated: {os.path.getsize(template):,} bytes")
    except Exception as e:
        log(f"  [WARN] PPTX update error: {e}")

    log("=" * 55)
    log("POSIT WEEKLY REFRESH COMPLETE")
    log("=" * 55)


if __name__ == "__main__":
    main()
