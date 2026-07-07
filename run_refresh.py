"""
run_refresh.py
Weekly auto-refresh orchestrator — called by Windows Scheduled Task every Wednesday 7 AM.
Runs all steps, logs to scheduler.log, then starts the dashboard.
"""
import os, sys, subprocess, datetime

DIR    = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
LOG    = os.path.join(DIR, "scheduler.log")

os.environ["PYTHONUTF8"]       = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run(script, label):
    log(f"Starting: {label}")
    r = subprocess.run(
        [PYTHON, os.path.join(DIR, script)],
        cwd=DIR, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if r.stdout: log(r.stdout.strip()[:500])
    if r.returncode != 0:
        log(f"[WARN] {label} exited with code {r.returncode}: {r.stderr[:200]}")
    else:
        log(f"Done: {label}")
    return r.returncode == 0

def kill_dashboard():
    subprocess.run(["taskkill", "/F", "/IM", "python.exe", "/T"],
                   capture_output=True)

def start_dashboard():
    log("Starting dashboard (minimized)...")
    subprocess.Popen(
        [PYTHON, os.path.join(DIR, "app.py")],
        cwd=DIR, creationflags=0x00000008,  # DETACHED_PROCESS
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )
    log("Dashboard started at http://127.0.0.1:8050")


if __name__ == "__main__":
    log("=" * 60)
    log("WEEKLY REFRESH STARTED")
    log("=" * 60)

    run("capture_buildburn.py",         "Build/Burn chart capture")
    run("generate_talk_track_pdf.py",   "Talk Track PDF")
    run("update_pptx.py",               "Trade Slides PPTX update")

    kill_dashboard()
    start_dashboard()

    log("=" * 60)
    log("WEEKLY REFRESH COMPLETE")
    log("=" * 60)
