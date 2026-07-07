"""
Vertex AI (Gemini) insights generator for the Inventory Health Dashboard.

Authentication pattern from server_otb.py (proven working):
  GCP_KEY.json  → service account SA key
    → OAuth2 token via requests + Walmart proxy
      → Vertex AI REST API via urllib + Walmart proxy
        → Gemini 2.0 Flash response

Proxy  : sysproxy.wal-mart.com:8080  (Walmart corporate)
SA key : svc-merch-execution-reporting@wmt-execution-intel-prod.iam.gserviceaccount.com
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from datetime import date

import pandas as pd

# ── GCP / Auth ────────────────────────────────────────────────────────────────
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest

# ── Config ────────────────────────────────────────────────────────────────────
_GCP_SCOPES    = ["https://www.googleapis.com/auth/cloud-platform"]
_HTTPS_PROXY   = os.environ.get("HTTPS_PROXY", "http://sysproxy.wal-mart.com:8080")
_VERTEX_PROJECT= "wmt-execution-intel-prod"

# SA key — use same key as the working OTB agent
_GCP_KEY_PATH  = os.path.join(
    os.path.expanduser("~"),
    "OneDrive - Walmart Inc",
    "Project", "FY27 Goal", "OTB Questions with Agent", "GCP_KEY.json",
)

# Model fallback list (mirrors server_otb.py)
_VERTEX_COMBOS = [
    ("gemini-2.0-flash-001", "us-central1"),
    ("gemini-2.0-flash-001", "us-east4"),
    ("gemini-1.5-flash-002", "us-central1"),
    ("gemini-1.5-flash-002", "us-east4"),
]

# CA bundle (optional — same location as server_otb.py)
_CA_BUNDLE = os.path.join(os.path.dirname(_GCP_KEY_PATH), "ca-bundle.crt")


def _make_ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if os.path.exists(_CA_BUNDLE):
        ctx.load_verify_locations(_CA_BUNDLE)
    return ctx


def _make_opener(ssl_ctx: ssl.SSLContext) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": _HTTPS_PROXY, "http": _HTTPS_PROXY}),
        urllib.request.HTTPSHandler(context=ssl_ctx),
    )


def _get_access_token() -> str:
    """Get a fresh OAuth2 bearer token via requests + Walmart proxy."""
    import requests
    creds = service_account.Credentials.from_service_account_file(
        _GCP_KEY_PATH, scopes=_GCP_SCOPES
    )
    session = requests.Session()
    session.proxies = {"https": _HTTPS_PROXY, "http": _HTTPS_PROXY}
    session.verify  = False          # Walmart corp SSL intercept
    import urllib3; urllib3.disable_warnings()
    auth_req = GoogleAuthRequest(session)
    creds.refresh(auth_req)
    return creds.token


def _call_vertex(system_prompt: str, user_message: str) -> str:
    """
    Call Vertex AI Gemini with proxy + SA key auth.
    Mirrors server_otb.py call_vertex() exactly.
    """
    token = _get_access_token()

    body = {
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "temperature":     0.3,
            "maxOutputTokens": 700,
        },
    }
    payload = json.dumps(body).encode("utf-8")

    ssl_ctx = _make_ssl_ctx()
    opener  = _make_opener(ssl_ctx)
    last_error = None

    for model, location in _VERTEX_COMBOS:
        endpoint = (
            f"https://{location}-aiplatform.googleapis.com/v1"
            f"/projects/{_VERTEX_PROJECT}/locations/{location}"
            f"/publishers/google/models/{model}:generateContent"
        )
        req = urllib.request.Request(endpoint, data=payload, method="POST")
        req.add_header("Content-Type",  "application/json")
        req.add_header("Authorization", f"Bearer {token}")
        print(f"  [Vertex] Trying {model} @ {location}...")

        try:
            with opener.open(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            print(f"  [Vertex] Success: {model} @ {location}")
            return result["candidates"][0]["content"]["parts"][0]["text"]

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code in (404, 403):
                print(f"  [Vertex] {e.code} on {model} @ {location} — trying next...")
                last_error = f"{e.code}: {err_body[:200]}"
                continue
            raise Exception(f"Vertex AI HTTP {e.code}: {err_body[:500]}")

        except urllib.error.URLError as e:
            if "CERTIFICATE" in str(e).upper() or "SSL" in str(e).upper():
                # Retry without SSL verification (corp proxy intercept)
                print("  [Vertex] SSL verify failed — retrying without verification...")
                ctx_nv = ssl.create_default_context()
                ctx_nv.check_hostname = False
                ctx_nv.verify_mode    = ssl.CERT_NONE
                opener2 = _make_opener(ctx_nv)
                try:
                    with opener2.open(req, timeout=120) as resp:
                        result = json.loads(resp.read().decode("utf-8"))
                    return result["candidates"][0]["content"]["parts"][0]["text"]
                except Exception as e2:
                    last_error = str(e2)
                    continue
            last_error = str(e)
            print(f"  [Vertex] URLError on {model} @ {location}: {last_error}")
            continue

    raise Exception(f"All Vertex AI model/location combos failed. Last: {last_error}")


# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """
You are a senior Walmart Merch Strategy & Enablement analyst writing for the
weekly Trade Meeting. Your audience is SVP/EVP-level leadership.

Supply chain node order (upstream to downstream):
  1. ON ORDER   — POs with vendors, not yet at DC gate (NON-DSD only)
  2. ON YARD    — at RDC/FDC gate, not yet received
  3. IN DC      — warehouse: DC OH + Labeled + Unlabeled + DC Reserved
  4. IN TRANSIT → DC  — on trucks/rail inbound to RDC, FDC, ICC, ACC
  5. IN TRANSIT → Store — trucks from DC to stores
  6. STORE OH   — Backroom + Salesfloor
  7. FC         — fulfillment center for eComm

Cross-node signal rules:
  - Store OH down + On-Order up  = replenishment signal (positive)
  - Store OH down + IT-to-Store up = replenishment en route (positive)
  - Store OH down + ALL upstream down = supply risk (flag it)
  - IT-to-DC surge = import build or seasonal prep
  - In DC up + IT-to-Store flat = DC holding, not releasing
  - Backroom up + Salesfloor down = staging or space constraint
  - On-Order L13W above LY = forward commitment above prior year

Seasonal context (use only when data supports):
  Wk22-26 (Jun): Independence Day prep, summer peak
  Wk27-32 (Jul-Aug): Back-to-School
  Wk38-44 (Oct): Holiday import peak
  Wk45-52 (Nov-Dec): Black Friday, Christmas

Writing rules:
  1. Lead with total network change vs LY and vs LW in one sentence.
  2. Call out 2-3 most significant SBU/node movements with dept specifics.
  3. Link upstream to downstream outcomes.
  4. Flag any node below LY with no upstream offset as a risk.
  5. Format as email body: subject line, then 4-5 short paragraphs.
  6. Quantify every claim: units (M/B), cube (M ft3), % changes.
  7. Keep under 400 words. No markdown headers.
  8. Close with ONE watch item for leadership.
"""


# ── Data block builder ────────────────────────────────────────────────────────

def _fmt(n: float) -> str:
    return f"{n/1_000_000:.1f}M"

def _pct(p: float | None) -> str:
    if p is None: return "N/A"
    return f"{'+' if p >= 0 else ''}{p*100:.1f}%"

def _s(df: pd.DataFrame, col: str) -> float:
    return float(df[col].sum()) if col in df.columns else 0.0

def _wpct(df: pd.DataFrame, ty_col: str, pw_col: str) -> float | None:
    ty = _s(df, ty_col); pw = _s(df, pw_col)
    if pw == 0: return None
    return (ty - pw) / pw


def _build_data_block(inv: pd.DataFrame, oo: pd.DataFrame,
                      cur_wk: int, prior_wk: int) -> str:
    lines = [
        f"WM Week: {cur_wk}  |  Prior Week: {prior_wk}",
        "",
        "=== TOTAL NETWORK ===",
        f"  TY Total : {_fmt(_s(inv,'total_network_units'))} units",
        f"  LY Total : {_fmt(_s(inv,'ly_total'))} units",
        f"  YoY      : {_pct(_wpct(inv,'total_network_units','ly_total'))}",
        f"  WoW      : {_pct(_wpct(inv,'total_network_units','pw_total'))}",
        "",
        f"{'Node':<26} {'TY':>10} {'WoW%':>7} {'YoY%':>7} {'Cube TY':>10}",
        "-" * 64,
    ]
    nodes = [
        ("On-Order (NON-DSD)",  oo,  "units_ordered",   "pw_units_ordered", "ly_units_ordered", "cube_ordered"),
        ("On-Yard",             inv, "on_yard_units",    "pw_yard",          "ly_yard",          "on_yard_cube"),
        ("In DC",               inv, "in_dc_units",      "pw_dc",            "ly_dc",            "in_dc_cube"),
        ("In Transit -> DC",    inv, "it_dc_units",      "pw_it_dc",         "ly_it_dc",         "it_dc_cube"),
        ("In Transit -> Store", inv, "it_store_units",   "pw_it_store",      "ly_it_store",      "it_store_cube"),
        ("Store OH",            inv, "store_oh_units",   "pw_store",         "ly_store",         "store_oh_cube"),
        ("  Backroom",          inv, "backroom_units",   "pw_backroom",      "ly_backroom",      "backroom_cube"),
        ("FC",                  inv, "fc_oh_units",      "pw_fc",            "ly_fc",            "fc_oh_cube"),
    ]
    for lbl, src, uc, pwc, lyc, cc in nodes:
        lines.append(
            f"{lbl:<26} {_fmt(_s(src,uc)):>10} "
            f"{_pct(_wpct(src,uc,pwc)):>7} {_pct(_wpct(src,uc,lyc)):>7} "
            f"{_fmt(_s(src,cc)):>10}"
        )

    lines += [
        "",
        f"On-Order L13W Avg : {_fmt(_s(oo,'l13w_avg_units'))}/wk",
        f"L13W vs LY        : {_pct(_wpct(oo,'l13w_avg_units','l13w_avg_units_ly'))}",
    ]

    if "sbu" in inv.columns and len(inv):
        sbu_g = inv.groupby("sbu")[["store_oh_units","ly_store","pw_store",
                                    "in_dc_units","it_store_units"]].sum()
        lines += ["", "=== SBU STORE OH ==="]
        for sbu, row in sbu_g.sort_values("store_oh_units", ascending=False).iterrows():
            wow = (row["store_oh_units"]-row["pw_store"])/row["pw_store"]*100 if row["pw_store"] else 0
            yoy = (row["store_oh_units"]-row["ly_store"])/row["ly_store"]*100  if row["ly_store"]  else 0
            lines.append(f"  {sbu:<18} {_fmt(row['store_oh_units'])}  WoW:{wow:+.1f}%  YoY:{yoy:+.1f}%  "
                         f"InDC:{_fmt(row['in_dc_units'])}  IT->Str:{_fmt(row['it_store_units'])}")

    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_weekly_insights(
    inv_week_df: pd.DataFrame,
    oo_week_df: pd.DataFrame,
    current_wm_week: int,
    prior_wm_week: int,
    current_date: date | None = None,
) -> str:
    """
    Generate executive weekly inventory narrative using Vertex AI Gemini.
    Uses the same auth + proxy pattern as server_otb.py (proven working).
    """
    if current_date is None:
        current_date = date.today()

    if not os.path.exists(_GCP_KEY_PATH):
        return (
            f"[ERROR] GCP key not found at:\n{_GCP_KEY_PATH}\n\n"
            "Update _GCP_KEY_PATH in ai/insights.py if the file was moved."
        )

    seasonal_hint = (
        f"Today is {current_date.strftime('%B %d, %Y')} "
        f"(WM week {current_wm_week}). Apply seasonal context where data supports it."
    )
    data_block = _build_data_block(inv_week_df, oo_week_df, current_wm_week, prior_wm_week)
    user_msg   = (
        f"{seasonal_hint}\n\n"
        "Write the weekly inventory executive update for the Trade Meeting "
        "based on the supply chain data below.\n\n"
        f"```\n{data_block}\n```"
    )

    # ── Try Google AI Studio key first (fastest, no corp infrastructure needed) ──
    google_api_key = os.getenv("GOOGLE_API_KEY", "")
    if google_api_key:
        try:
            from google import genai
            from google.genai import types
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                client = genai.Client(api_key=google_api_key)
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=user_msg,
                    config=types.GenerateContentConfig(
                        system_instruction=_SYSTEM_PROMPT,
                        max_output_tokens=700,
                        temperature=0.3,
                    ),
                )
            return response.text
        except Exception as exc:
            print(f"  [AI] Google AI Studio failed: {exc}")

    # ── Try Vertex AI via SA key + Walmart proxy ──────────────────────────────
    if os.path.exists(_GCP_KEY_PATH):
        try:
            return _call_vertex(_SYSTEM_PROMPT, user_msg)
        except Exception as exc:
            vertex_err = str(exc)
            print(f"  [AI] Vertex AI failed: {vertex_err[:100]}")
    else:
        vertex_err = f"GCP key not found: {_GCP_KEY_PATH}"

    # ── No working AI path ────────────────────────────────────────────────────
    return (
        "[AI INSIGHTS NOT CONFIGURED]\n\n"
        "To enable the Generate Insights button, choose one option:\n\n"
        "OPTION A — Free Gemini API (fastest, 2 min):\n"
        "  1. Go to https://aistudio.google.com  → Get API Key\n"
        "  2. Add to .env file:\n"
        "       GOOGLE_API_KEY=AIzaSy...\n"
        "  3. Restart the dashboard\n\n"
        "OPTION B — Vertex AI (ask GCP admin):\n"
        "  Run: gcloud services enable aiplatform.googleapis.com \\\n"
        f"         --project={_VERTEX_PROJECT}\n"
        "  Then ensure SA has 'Vertex AI User' role\n\n"
        f"Last error: {vertex_err[:200]}"
    )
