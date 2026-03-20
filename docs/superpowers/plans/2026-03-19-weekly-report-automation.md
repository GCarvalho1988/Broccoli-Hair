# Weekly Report Automation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Flask web app that generates a weekly Sectra sales report as an editable HTML page (print to PDF), pulling live data from Smartsheet, capturing a dashboard screenshot, generating a quadrant chart, and using AI to draft deal updates in a single API call.

**Architecture:** Flask serves an input form; on submit, the app fetches Smartsheet data, captures the Smartsheet dashboard via Playwright, generates a matplotlib quadrant chart, runs a single Claude API call to draft all content, then renders a Jinja2 HTML report. The report is editable in the browser; a "Save & Publish" button persists content to history.json; "Print to PDF" triggers browser print with UI hidden via CSS.

**Tech Stack:** Python 3, Flask, Playwright (Python library), matplotlib, anthropic SDK, smartsheet-python-sdk, pdfplumber, python-dotenv, Jinja2 (via Flask), HTML/CSS.

**Python path:** `C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe`

---

## File Map

| File | Responsibility |
|---|---|
| `config.py` | Load env vars, define constants (sheet ID, stage colours, model name) |
| `history.py` | Load/save/query `reports/history.json`; deal inclusion logic |
| `smartsheet_client.py` | Fetch active deals from Smartsheet API; parse into dicts |
| `dashboard_capture.py` | Playwright headless Chromium; return PNG bytes |
| `charts.py` | Quadrant chart; repulsion for overlapping dots; return base64 PNG string |
| `pdf_reader.py` | Extract text from Portfolio Weekly PDF using pdfplumber |
| `ai_writer.py` | Single Claude API call; return structured dict of all AI content |
| `main.py` | Flask routes: `/` (form), `/generate` (POST), `/save` (POST) |
| `templates/index.html` | Input form: transcript textarea, PDF upload, Generate button |
| `templates/report.html` | Jinja2 report: editable fields, Save button, Print button, print CSS |
| `requirements.txt` | All Python dependencies |
| `reports/history.json` | Persistent deal data (created on first run) |
| `seed_history.py` | One-time script: seed history.json from SM WR 06th Mar.docx |

---

## Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Verify: `.env` (already exists)

- [ ] **Step 1: Write requirements.txt**

```
flask
smartsheet-python-sdk
anthropic
matplotlib
pdfplumber
python-dotenv
playwright
python-docx
```

- [ ] **Step 2: Install dependencies**

```
C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe -m pip install flask smartsheet-python-sdk anthropic matplotlib pdfplumber python-dotenv playwright python-docx
```

- [ ] **Step 3: Install Playwright browsers**

```
C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe -m playwright install chromium
```

- [ ] **Step 4: Write config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

SMARTSHEET_API_KEY = os.environ["SMARTSHEET_API_KEY"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
PIPELINE_SHEET_ID  = 5464922490097540
MODEL              = "claude-sonnet-4-6"

DASHBOARD_URL = "https://app.smartsheet.com/b/publish?EQBCT=13232135d0854d86b63655eca3dce19f"

# Sales stage colours (hex, for quadrant dots and report badges)
STAGE_COLOURS = {
    "0": "#888888",  # One to Watch — grey
    "1": "#E87722",  # Pre-Tender — orange
    "2": "#F5C400",  # Early Engagement — yellow
    "3": "#2E7D32",  # OBS — green
    "4": "#00838F",  # Demo/Site Visits — teal
    "5": "#1565C0",  # BAFO — blue
    "6": "#6A1B9A",  # Preferred Supplier — purple
}

NON_DEALS = {"demo kit", "conference diary", "click here"}
```

- [ ] **Step 5: Verify .env has both keys**

```
SMARTSHEET_API_KEY=mjpMbPsMwf42cWAFCSFK72Lxlm0wdDpgzJ1Pe
ANTHROPIC_API_KEY=<your key>
```

- [ ] **Step 6: Commit**

```
git add requirements.txt config.py
git commit -m "chore: project setup — config and dependencies"
```

---

## Task 2: history.py

**Files:**
- Create: `history.py`
- Create: `reports/` directory

The inclusion logic lives here. Two key dates per deal:
- `last_discussed_date` — last time the deal was mentioned in a transcript
- `last_included_date` — last time it appeared in a report (update or "No update.")

Top-level `_meta.last_run_date` tells us what the previous report date was.

- [ ] **Step 1: Create reports directory**

```
mkdir reports
```

- [ ] **Step 2: Write history.py**

```python
"""
Manages reports/history.json.

Per-deal structure:
{
  "display_name": "North Central London (Radiology)",
  "summary_lines": ["line1", ...],
  "last_update_lines": ["line1", ...],
  "last_discussed_date": "2026-03-13",
  "last_included_date": "2026-03-13"
}

Top-level _meta.last_run_date = date of the previous report run.
"""
import json, os, re
from datetime import date

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "reports", "history.json")


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"_meta": {"last_run_date": None}}


def save_history(history: dict) -> None:
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def get_deal(name: str, history: dict) -> dict | None:
    """Return the history entry for a deal, or None. Uses fuzzy match."""
    k = _key(name)
    if k in history:
        return history[k]
    return _fuzzy_get(k, history)


def _fuzzy_get(k: str, history: dict) -> dict | None:
    if len(k) >= 4:
        for key in history:
            if key == "_meta":
                continue
            if re.search(r"\b" + re.escape(k) + r"\b", key):
                return history[key]
    words = [w for w in re.split(r"\W+", k) if len(w) > 3]
    best_key, best_score = None, 0
    for key in history:
        if key == "_meta":
            continue
        score = sum(1 for w in words if w in key)
        if score > best_score:
            best_key, best_score = key, score
    if best_score >= 2:
        return history[best_key]
    return None


def should_include(name: str, history: dict, discussed: bool) -> bool:
    """
    Return True if this deal should appear in the Detailed Updates section.
    Rules:
      - Discussed this week → always include
      - Not discussed, but last_included_date == last_run_date → include ("No update.")
      - Otherwise → exclude
    """
    if discussed:
        return True
    last_run = history.get("_meta", {}).get("last_run_date")
    if not last_run:
        return False
    entry = get_deal(name, history)
    if not entry:
        return False
    return entry.get("last_included_date") == last_run


def update_deal(history: dict, name: str, *,
                summary_lines=None, update_lines=None,
                discussed: bool = False,
                report_date: str = None) -> None:
    """Write back a deal's data after a report run."""
    k = _key(name)
    today = report_date or date.today().isoformat()
    if k not in history:
        history[k] = {"display_name": name.strip()}
    entry = history[k]
    entry["display_name"] = name.strip()
    if summary_lines is not None:
        entry["summary_lines"] = summary_lines
    if update_lines is not None:
        entry["last_update_lines"] = update_lines
    entry["last_included_date"] = today
    if discussed:
        entry["last_discussed_date"] = today


def set_last_run_date(history: dict, d: str) -> None:
    history.setdefault("_meta", {})["last_run_date"] = d
```

- [ ] **Step 3: Smoke-test the inclusion logic**

```python
# Quick test — run with: python -c "exec(open('test_history.py').read())"
from history import load_history, should_include, update_deal, set_last_run_date

h = {"_meta": {"last_run_date": "2026-03-13"}}
# Simulate a deal that was in last report
h["newcastle"] = {"display_name": "Newcastle", "last_included_date": "2026-03-13"}

assert should_include("Newcastle", h, discussed=True)   == True
assert should_include("Newcastle", h, discussed=False)  == True  # in last report
assert should_include("SWASH", h, discussed=False)      == False  # never seen

print("history.py: all assertions passed")
```

Save as `test_history.py`, run it, verify output.

- [ ] **Step 4: Commit**

```
git add history.py reports/.gitkeep test_history.py
git commit -m "feat: history.py — deal data persistence and inclusion logic"
```

---

## Task 3: smartsheet_client.py

**Files:**
- Create: `smartsheet_client.py`

- [ ] **Step 1: Write smartsheet_client.py**

```python
import smartsheet
from config import SMARTSHEET_API_KEY, PIPELINE_SHEET_ID, NON_DEALS

_client = smartsheet.Smartsheet(SMARTSHEET_API_KEY)
_client.errors_as_exceptions(True)


def fetch_pipeline_data() -> list[dict]:
    """
    Returns a list of dicts, one per active deal row.
    Filters out header rows, non-deal rows, and closed deals.
    """
    sheet = _client.Sheets.get_sheet(PIPELINE_SHEET_ID)
    headers = {col.id: col.title for col in sheet.columns}

    deals = []
    for row in sheet.rows:
        row_data = {headers[c.column_id]: c.display_value or c.value
                    for c in row.cells if c.column_id in headers}

        name  = str(row_data.get("Opportunity") or "").strip()
        stage = str(row_data.get("Sales Stage") or "").strip()

        if not name or not stage:
            continue
        if name.lower() in NON_DEALS:
            continue
        if any(skip in name.lower() for skip in NON_DEALS):
            continue
        if "closed" in stage.lower():
            continue

        deals.append({
            "Opportunity":      name,
            "Sales Stage":      stage,
            "Forecast Amount":  row_data.get("Forecast Amount", ""),
            "Sales Rep":        row_data.get("Sales Rep", ""),
            "Next Step":        row_data.get("Next Step", ""),
            "Expected Close":   row_data.get("Expected Close Date", ""),
            "Strategic Fit":    _to_float(row_data.get("Strategic Fit")),
            "Profitability":    _to_float(row_data.get("Profitability")),
            "Stage Number":     _stage_number(stage),
        })
    return deals


def _to_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _stage_number(stage: str) -> str:
    """Extract the leading digit from a stage string like '6 - Preferred Supplier'."""
    import re
    m = re.match(r"(\d)", stage.strip())
    return m.group(1) if m else "0"
```

- [ ] **Step 2: Smoke-test**

```
C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe -c "
from smartsheet_client import fetch_pipeline_data
deals = fetch_pipeline_data()
print(f'Fetched {len(deals)} active deals')
for d in deals[:3]:
    print(f'  {d[\"Opportunity\"]} | {d[\"Sales Stage\"]} | Fit={d[\"Strategic Fit\"]} Prof={d[\"Profitability\"]}')
"
```

Expected: 10–30 deals, no "Demo kit" or "Conference Diary".

- [ ] **Step 3: Commit**

```
git add smartsheet_client.py
git commit -m "feat: smartsheet_client — fetch active pipeline deals"
```

---

## Task 4: dashboard_capture.py

**Files:**
- Create: `dashboard_capture.py`

- [ ] **Step 1: Write dashboard_capture.py**

```python
"""
Captures the Smartsheet Sales Pipeline Overview dashboard as PNG bytes
using a headless Chromium browser via Playwright.
"""
from playwright.sync_api import sync_playwright
from config import DASHBOARD_URL


def capture_dashboard(timeout_ms: int = 25000) -> bytes:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 800})
        page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(4000)
        screenshot = page.screenshot(
            full_page=False,
            clip={"x": 0, "y": 50, "width": 1400, "height": 660}
        )
        browser.close()
    return screenshot
```

- [ ] **Step 2: Smoke-test**

```
C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe -c "
from dashboard_capture import capture_dashboard
data = capture_dashboard()
with open('dashboard_test.png', 'wb') as f: f.write(data)
print(f'Screenshot: {len(data)} bytes -> dashboard_test.png')
"
```

Open `dashboard_test.png` and verify it looks correct.

- [ ] **Step 3: Commit**

```
git add dashboard_capture.py
git commit -m "feat: dashboard_capture — Playwright screenshot of Smartsheet dashboard"
```

---

## Task 5: charts.py

**Files:**
- Create: `charts.py`

The quadrant is for exec consumption — readability over accuracy.
- Large dots (scatter marker size ~800)
- Large fonts (deal names, axis labels)
- Repulsion algorithm: if two dots are within `min_dist`, nudge them apart iteratively
- Return base64-encoded PNG string for embedding in HTML

- [ ] **Step 1: Write charts.py**

```python
"""
Generates the Strategic Fit vs Profitability quadrant chart.
Returns a base64-encoded PNG string suitable for embedding in HTML as:
  <img src="data:image/png;base64,{{ quadrant_b64 }}">
"""
import io, base64, math, random
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from config import STAGE_COLOURS


def generate_quadrant(deals: list[dict]) -> str:
    """Return base64 PNG string of the quadrant chart."""
    # Filter deals that have both axes populated
    plottable = [d for d in deals
                 if d.get("Strategic Fit") is not None
                 and d.get("Profitability") is not None]

    points = [{"x": d["Profitability"],
               "y": d["Strategic Fit"],
               "label": d["Opportunity"],
               "colour": STAGE_COLOURS.get(d.get("Stage Number", "0"), "#888888")}
              for d in plottable]

    points = _spread_points(points, min_dist=0.6, iterations=120)

    with plt.xkcd():
        fig, ax = plt.subplots(figsize=(12, 10))

        # Quadrant background shading
        ax.axhspan(5, 10, xmin=0.5, xmax=1.0, alpha=0.06, color="green")
        ax.axhspan(0,  5, xmin=0.0, xmax=0.5, alpha=0.06, color="red")

        # Quadrant dividers
        ax.axhline(5, color="#cccccc", linewidth=1, linestyle="--")
        ax.axvline(5, color="#cccccc", linewidth=1, linestyle="--")

        for pt in points:
            ax.scatter(pt["x"], pt["y"], s=900, color=pt["colour"],
                       alpha=0.85, zorder=3, edgecolors="white", linewidths=1.5)
            ax.annotate(pt["label"], (pt["x"], pt["y"]),
                        textcoords="offset points",
                        xytext=_label_offset(pt["x"], pt["y"]),
                        fontsize=9, fontweight="bold",
                        ha="center", va="center",
                        bbox=dict(boxstyle="round,pad=0.3",
                                  fc="white", ec=pt["colour"],
                                  alpha=0.9, linewidth=1.2))

        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.set_xlabel("Profitability →", fontsize=13, fontweight="bold")
        ax.set_ylabel("Strategic Fit →", fontsize=13, fontweight="bold")
        ax.set_title("Deal Quadrant Analysis", fontsize=16, fontweight="bold", pad=15)
        ax.tick_params(labelsize=10)

        # Quadrant labels
        for txt, x, y in [("High Fit\nHigh Profit", 7.5, 7.5),
                           ("High Fit\nLow Profit",  2.5, 7.5),
                           ("Low Fit\nHigh Profit",  7.5, 2.5),
                           ("Low Fit\nLow Profit",   2.5, 2.5)]:
            ax.text(x, y, txt, fontsize=9, color="#aaaaaa",
                    ha="center", va="center", style="italic")

        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        plt.close(fig)

    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _spread_points(points: list[dict], min_dist: float = 0.6,
                   iterations: int = 120) -> list[dict]:
    """Nudge overlapping points apart so labels don't stack."""
    import copy
    pts = copy.deepcopy(points)
    for _ in range(iterations):
        moved = False
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                dx = pts[i]["x"] - pts[j]["x"]
                dy = pts[i]["y"] - pts[j]["y"]
                dist = math.hypot(dx, dy)
                if dist < min_dist and dist > 0:
                    factor = (min_dist - dist) / dist * 0.5
                    pts[i]["x"] += dx * factor
                    pts[i]["y"] += dy * factor
                    pts[j]["x"] -= dx * factor
                    pts[j]["y"] -= dy * factor
                    moved = True
                elif dist == 0:
                    pts[i]["x"] += random.uniform(-0.05, 0.05)
                    pts[i]["y"] += random.uniform(-0.05, 0.05)
                    moved = True
        # Clamp to axis bounds
        for pt in pts:
            pt["x"] = max(0.3, min(9.7, pt["x"]))
            pt["y"] = max(0.3, min(9.7, pt["y"]))
        if not moved:
            break
    return pts


def _label_offset(x: float, y: float) -> tuple[int, int]:
    """Offset label away from the centre of the chart."""
    ox = 18 if x >= 5 else -18
    oy = 18 if y >= 5 else -18
    return (ox, oy)
```

- [ ] **Step 2: Smoke-test**

```
C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe -c "
from smartsheet_client import fetch_pipeline_data
from charts import generate_quadrant
deals = fetch_pipeline_data()
b64 = generate_quadrant(deals)
import base64
with open('quadrant_test.png', 'wb') as f: f.write(base64.b64decode(b64))
print(f'Chart generated -> quadrant_test.png ({len(b64)} b64 chars)')
"
```

Open `quadrant_test.png` — verify dots are spread, labels readable, no overlap.

- [ ] **Step 3: Commit**

```
git add charts.py
git commit -m "feat: charts — exec-style quadrant chart with repulsion algorithm"
```

---

## Task 6: pdf_reader.py

**Files:**
- Create: `pdf_reader.py`

- [ ] **Step 1: Write pdf_reader.py**

```python
"""Extracts text from the Portfolio Weekly Report PDF."""
import pdfplumber


def extract_portfolio_text(pdf_path: str) -> str:
    """Return all text from the PDF, truncated to 4000 chars."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)[:4000]
    except Exception as e:
        print(f"PDF read failed: {e}")
        return ""
```

- [ ] **Step 2: Smoke-test with the uploaded PDF**

```
C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe -c "
from pdf_reader import extract_portfolio_text
text = extract_portfolio_text('uploads/Weekly Report - Week 11.pdf')
print(f'{len(text)} chars extracted')
print(text[:300])
"
```

- [ ] **Step 3: Commit**

```
git add pdf_reader.py
git commit -m "feat: pdf_reader — extract Portfolio Weekly PDF text"
```

---

## Task 7: ai_writer.py

**Files:**
- Create: `ai_writer.py`

This is the most critical file. A single API call does everything:
1. Resolves transcript mentions to Smartsheet deal names (handles abbreviations)
2. Drafts 1–2 bullet updates for mentioned deals
3. Suggests summary updates for deals with significant new info
4. Drafts new summaries for deals with no history
5. Builds the High-Level Summary table one-liners
6. Extracts upsell items from the portfolio PDF

Response is structured JSON parsed in Python.

- [ ] **Step 1: Write ai_writer.py**

```python
"""
Single Claude API call that produces all AI content for the report.
Returns a structured dict — see draft_report_content() docstring.
"""
import json, re
import anthropic
from config import ANTHROPIC_API_KEY, MODEL
from history import get_deal

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def draft_report_content(deals: list[dict], transcript: str,
                         portfolio_text: str, history: dict) -> dict:
    """
    Returns:
    {
      "high_level_summary": [
        {"deal": str, "stage": str, "one_liner": str, "forecast": str}
      ],
      "deal_updates": [
        {
          "deal": str,           # matched to Smartsheet name
          "mentioned": bool,
          "update_lines": [str],
          "summary_action": "unchanged" | "updated" | "new",
          "summary_lines": [str]   # new or updated lines (or existing if unchanged)
        }
      ],
      "upsell_items": [str]
    }
    """
    deals_text = _format_deals(deals, history)
    existing_summaries = _format_summaries(deals, history)

    prompt = f"""You are helping a Sales Manager at Sectra (UK medical imaging software) write a weekly sales report.

ACTIVE DEALS IN SMARTSHEET (in pipeline order):
{deals_text}

EXISTING DEAL SUMMARIES (from previous reports):
{existing_summaries}

MEETING TRANSCRIPT (Teams auto-generated — may use abbreviations or informal names):
{transcript[:8000]}

PORTFOLIO WEEKLY REPORT (for upsell items):
{portfolio_text[:3000]}

---

TASK: Produce a JSON response with exactly this structure (no markdown, no extra text — raw JSON only):

{{
  "high_level_summary": [
    {{
      "deal": "<exact Smartsheet deal name>",
      "stage": "<Sales Stage value>",
      "one_liner": "<one sentence summary of current status>",
      "forecast": "<Forecast Amount or empty string>"
    }}
  ],
  "deal_updates": [
    {{
      "deal": "<exact Smartsheet deal name>",
      "mentioned": <true|false>,
      "update_lines": ["<bullet 1>", "<bullet 2>"],
      "summary_action": "<unchanged|updated|new>",
      "summary_lines": ["<line 1>", "<line 2>", "..."]
    }}
  ],
  "upsell_items": ["<item 1>", "<item 2>"]
}}

RULES:
1. DEAL NAME MATCHING: Map every transcript mention to the exact Smartsheet deal name.
   The meeting follows Smartsheet pipeline order — use this to resolve abbreviations.
   Examples: NCL → North Central London (Radiology), Barts → Barts Health, NENC → North East and North Cumbria Digital Pathology.

2. HIGH-LEVEL SUMMARY: Include only deals mentioned in the transcript. One sentence per deal.

3. DEAL UPDATES: Include ALL active deals, not just mentioned ones.
   - If mentioned: write 1–2 concise bullet points summarising the discussion. No fluff.
   - If not mentioned: set mentioned=false, update_lines=["No update."]
   - Do not use markdown bold (**). Do not repeat the deal name in the update text.

4. SUMMARY LINES: Each deal needs a summary covering: customer background, sites covered,
   current vendors, deal value, and key events to date — in bullet-point format.
   - summary_action="unchanged": existing summary is fine, return it as-is
   - summary_action="updated": there is significant new info — return the full updated summary
   - summary_action="new": no existing summary — draft one from Smartsheet data and transcript.
     If you have very little data, draft what you can and flag the first line as "[AI DRAFT — please review]"

5. UPSELL: Extract upsell opportunities from the Portfolio PDF and transcript. If none: [].
"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    return _parse_response(message.content[0].text, deals, history)


def _format_deals(deals: list[dict], history: dict) -> str:
    lines = []
    for d in deals:
        fit  = d.get("Strategic Fit", "?")
        prof = d.get("Profitability", "?")
        lines.append(
            f"- {d['Opportunity']} | Stage: {d['Sales Stage']} | "
            f"£{d.get('Forecast Amount', 'N/A')} | Rep: {d.get('Sales Rep', '')} | "
            f"Fit: {fit} | Profit: {prof} | Next: {d.get('Next Step', '')}"
        )
    return "\n".join(lines)


def _format_summaries(deals: list[dict], history: dict) -> str:
    lines = []
    for d in deals:
        entry = get_deal(d["Opportunity"], history)
        if entry and entry.get("summary_lines"):
            lines.append(f"\n{d['Opportunity']}:")
            for s in entry["summary_lines"]:
                lines.append(f"  - {s}")
        else:
            lines.append(f"\n{d['Opportunity']}: (no summary on record)")
    return "\n".join(lines)


def _parse_response(raw: str, deals: list[dict], history: dict) -> dict:
    """Parse the JSON response, falling back gracefully on errors."""
    # Strip any accidental markdown code fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"AI response was not valid JSON:\n{raw[:500]}")
        return _empty_result(deals, history)

    # Ensure every active deal has an entry
    existing = {item["deal"].lower(): item for item in data.get("deal_updates", [])}
    for d in deals:
        if d["Opportunity"].lower() not in existing:
            entry = get_deal(d["Opportunity"], history)
            data.setdefault("deal_updates", []).append({
                "deal": d["Opportunity"],
                "mentioned": False,
                "update_lines": ["No update."],
                "summary_action": "unchanged",
                "summary_lines": entry.get("summary_lines", []) if entry else [],
            })

    return data


def _empty_result(deals: list[dict], history: dict) -> dict:
    updates = []
    for d in deals:
        entry = get_deal(d["Opportunity"], history)
        updates.append({
            "deal": d["Opportunity"],
            "mentioned": False,
            "update_lines": ["No update."],
            "summary_action": "unchanged",
            "summary_lines": entry.get("summary_lines", []) if entry else [],
        })
    return {"high_level_summary": [], "deal_updates": updates, "upsell_items": []}
```

- [ ] **Step 2: Smoke-test**

```
C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe -c "
from docx import Document
import io
with open('uploads/Weekly Sales Meeting (1).docx', 'rb') as f: data = f.read()
transcript = '\n'.join(p.text for p in Document(io.BytesIO(data)).paragraphs if p.text.strip())

from smartsheet_client import fetch_pipeline_data
from history import load_history
from ai_writer import draft_report_content

deals = fetch_pipeline_data()
history = load_history()
result = draft_report_content(deals, transcript, '', history)

print(f'Summary rows: {len(result[\"high_level_summary\"])}')
print(f'Deal updates: {len(result[\"deal_updates\"])}')
mentioned = [d for d in result[\"deal_updates\"] if d[\"mentioned\"]]
print(f'Mentioned deals: {len(mentioned)}')
for d in mentioned[:3]:
    print(f'  {d[\"deal\"]}: {d[\"update_lines\"]}')
" 2>&1 | grep -v findfont
```

- [ ] **Step 3: Commit**

```
git add ai_writer.py
git commit -m "feat: ai_writer — single API call for all report content"
```

---

## Task 8: Seed history.json from previous report

**Files:**
- Create: `seed_history.py` (one-time script, reuse logic from archive/v1)

- [ ] **Step 1: Write seed_history.py**

```python
"""
One-time script: parse SM WR 06th Mar.docx and seed reports/history.json.
Run once: python seed_history.py
"""
import os, re
from docx import Document
from history import load_history, save_history, update_deal, set_last_run_date

REPORT_PATH = os.path.join(os.path.dirname(__file__), "SM WR 06th Mar.docx")
REPORT_DATE = "2026-03-06"

_SECTION_HEADERS = {
    "general updates:", "high-level summary:", "detailed updates:",
    "other portfolio upsell", "other team updates", "summary:", "update:",
}


def _is_bold(para):
    return any(r.bold and r.text.strip() for r in para.runs)


def extract_summaries(docx_path):
    doc = Document(docx_path)
    paragraphs = list(doc.paragraphs)

    detailed_start = next(
        (i for i, p in enumerate(paragraphs)
         if re.search(r"detailed updates", p.text, re.IGNORECASE)), None)
    if detailed_start is None:
        return {}

    section_end = next(
        (i for i in range(detailed_start + 1, len(paragraphs))
         if paragraphs[i].text.strip().lower() in
            {"other portfolio upsell", "other team updates"}),
        len(paragraphs))

    summaries, current_deal, collecting, lines = {}, None, None, []

    for p in paragraphs[detailed_start + 1: section_end]:
        text = p.text.strip()
        if not text:
            continue
        if re.match(r"^summary\s*:", text, re.IGNORECASE) and not _is_bold(p):
            collecting = "summary"
            after = re.sub(r"^summary\s*:\s*", "", text, flags=re.IGNORECASE).strip()
            if after:
                lines.append(after)
            continue
        if re.match(r"^update\s*:", text, re.IGNORECASE) and not _is_bold(p):
            collecting = "update"
            continue
        if (_is_bold(p) and len(text) < 100
                and text.strip().lower().rstrip(":") not in
                {h.rstrip(":") for h in _SECTION_HEADERS}):
            if current_deal and lines:
                summaries[current_deal] = lines[:]
            current_deal, lines, collecting = text, [], None
            continue
        if collecting == "summary" and current_deal:
            lines.append(text)

    if current_deal and lines:
        summaries[current_deal] = lines[:]
    return summaries


def main():
    print(f"Parsing {REPORT_PATH} ...")
    summaries = extract_summaries(REPORT_PATH)
    if not summaries:
        print("No summaries found.")
        return

    history = load_history()
    for name, lines in summaries.items():
        update_deal(history, name, summary_lines=lines,
                    report_date=REPORT_DATE)
        print(f"  Seeded: {name!r} ({len(lines)} lines)")

    set_last_run_date(history, REPORT_DATE)
    save_history(history)
    print(f"\nDone — {len(summaries)} deals seeded, last_run_date={REPORT_DATE}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

```
C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe seed_history.py
```

Expected: 7 deals seeded.

- [ ] **Step 3: Commit**

```
git add seed_history.py reports/history.json
git commit -m "chore: seed history.json from SM WR 06th Mar.docx"
```

---

## Task 9: templates/report.html

**Files:**
- Create: `templates/report.html`

This is the main output. Use the `frontend-design` skill for this task.

Key requirements:
- Sectra navy blue (#1B3A6B) branding
- Formal document aesthetic, readability first
- Dashboard image (full width)
- Quadrant chart (full width)
- High-level summary: table with stage badge, deal name, one-liner, forecast
- Detailed updates: deal heading + stage badge, Summary section, Update section (editable textarea)
- Summary section also editable (textarea), flagged if AI-drafted
- Upsell section
- "Save & Publish" button (top, hidden on print)
- "Print to PDF" button (top, hidden on print)
- `@media print`: hide all controls, clean pagination, page breaks before each major section
- Stage badge colours from STAGE_COLOURS
- All images embedded as base64 (passed in as Jinja2 variables)

Jinja2 variables available:
- `report_date` — string e.g. "19 March 2026"
- `dashboard_b64` — base64 PNG or None
- `quadrant_b64` — base64 PNG
- `high_level_summary` — list of {deal, stage, stage_num, one_liner, forecast}
- `deal_updates` — list of {deal, stage, stage_num, mentioned, update_lines, summary_action, summary_lines}
- `upsell_items` — list of strings
- `stage_colours` — dict of stage_num → hex colour

- [ ] **Step 1: Invoke frontend-design skill and build report.html**

Use the `frontend-design` skill with the requirements above.
Save output to `templates/report.html`.

- [ ] **Step 2: Commit**

```
git add templates/report.html
git commit -m "feat: report.html — HTML report template with print CSS"
```

---

## Task 10: templates/index.html

**Files:**
- Create: `templates/index.html`

Simple, clean input form. Use `frontend-design` skill.

Elements:
- Sectra branding header
- Step 1: Transcript textarea (large, paste Teams transcript here)
- Step 2: Portfolio PDF upload (optional)
- Generate button — shows spinner while processing
- Status message area
- Note: "Dashboard & Smartsheet data fetched automatically"

- [ ] **Step 1: Invoke frontend-design skill and build index.html**

- [ ] **Step 2: Commit**

```
git add templates/index.html
git commit -m "feat: index.html — report generation input form"
```

---

## Task 11: main.py

**Files:**
- Create: `main.py`
- Create: `uploads/` directory

Three routes:
- `GET /` — serves index.html
- `POST /generate` — runs the full pipeline, returns rendered report.html
- `POST /save` — receives edited content as JSON, saves to history.json, returns `{"ok": true}`

- [ ] **Step 1: Write main.py**

```python
import os, io, base64, json
from datetime import date
from flask import Flask, render_template, request, jsonify

from config import STAGE_COLOURS
from smartsheet_client import fetch_pipeline_data
from dashboard_capture import capture_dashboard
from charts import generate_quadrant
from pdf_reader import extract_portfolio_text
from ai_writer import draft_report_content
from history import (load_history, save_history, update_deal,
                     set_last_run_date, should_include)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    transcript = request.form.get("transcript", "").strip()
    if not transcript:
        return "Please paste the meeting transcript.", 400

    portfolio_text = ""
    pdf_file = request.files.get("portfolio_pdf")
    if pdf_file and pdf_file.filename:
        path = os.path.join(UPLOAD_FOLDER, "portfolio.pdf")
        pdf_file.save(path)
        portfolio_text = extract_portfolio_text(path)

    # Dashboard screenshot
    dashboard_b64 = None
    try:
        png = capture_dashboard()
        dashboard_b64 = base64.b64encode(png).decode("utf-8")
    except Exception as e:
        print(f"Dashboard capture failed: {e}")

    # Pipeline data + chart
    deals = fetch_pipeline_data()
    quadrant_b64 = generate_quadrant(deals)

    # History + AI
    history = load_history()
    ai = draft_report_content(deals, transcript, portfolio_text, history)

    # Apply inclusion logic — filter deal_updates to only those that should appear
    today = date.today().isoformat()
    filtered_updates = []
    for item in ai["deal_updates"]:
        mentioned = item.get("mentioned", False)
        if should_include(item["deal"], history, discussed=mentioned):
            filtered_updates.append(item)

    # Enrich with stage info for template
    deal_stage_map = {d["Opportunity"].lower(): d for d in deals}
    for item in filtered_updates:
        d = deal_stage_map.get(item["deal"].lower(), {})
        item["stage"]     = d.get("Sales Stage", "")
        item["stage_num"] = d.get("Stage Number", "0")

    for item in ai.get("high_level_summary", []):
        d = deal_stage_map.get(item["deal"].lower(), {})
        item["stage"]     = d.get("Sales Stage", "")
        item["stage_num"] = d.get("Stage Number", "0")

    report_date = date.today().strftime("%-d %B %Y") if os.name != "nt" else date.today().strftime("%d %B %Y").lstrip("0")

    return render_template("report.html",
        report_date=report_date,
        dashboard_b64=dashboard_b64,
        quadrant_b64=quadrant_b64,
        high_level_summary=ai.get("high_level_summary", []),
        deal_updates=filtered_updates,
        upsell_items=ai.get("upsell_items", []),
        stage_colours=STAGE_COLOURS,
    )


@app.route("/save", methods=["POST"])
def save():
    """
    Receives JSON: { deals: [{deal, summary_lines, update_lines}], run_date }
    Saves to history.json.
    """
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400

    history = load_history()
    today = data.get("run_date", date.today().isoformat())

    for item in data.get("deals", []):
        update_deal(history, item["deal"],
                    summary_lines=item.get("summary_lines"),
                    update_lines=item.get("update_lines"),
                    discussed=item.get("mentioned", False),
                    report_date=today)

    set_last_run_date(history, today)
    save_history(history)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
```

- [ ] **Step 2: Commit**

```
git add main.py uploads/.gitkeep
git commit -m "feat: main.py — Flask routes for generate and save"
```

---

## Task 12: End-to-End Test

- [ ] **Step 1: Start the server**

```
C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe main.py
```

- [ ] **Step 2: Open browser at http://localhost:5000**

Verify the input form loads.

- [ ] **Step 3: Paste transcript and click Generate**

Use `uploads/Weekly Sales Meeting (1).docx` content as transcript.

- [ ] **Step 4: Verify report**

- Dashboard screenshot visible
- Quadrant chart visible with labelled dots, no overlapping
- High-level summary table populated
- Detailed updates show correct deals (mentioned ones with updates, others with "No update.")
- Deals with no summary are flagged
- Upsell section populated

- [ ] **Step 5: Edit an update, click Save & Publish**

Verify history.json is updated.

- [ ] **Step 6: Click Print to PDF**

Verify print preview shows clean report — no buttons, no textareas, just content.

- [ ] **Final commit**

```
git add .
git commit -m "feat: complete v2 weekly report automation"
```

---

## Notes for Execution

- Python path: `C:\Users\gu-car\AppData\Local\Programs\Python\Python314\python.exe`
- Run commands in `cmd.exe` (not PowerShell) due to execution policy restrictions
- The `frontend-design` skill should be invoked for Tasks 9 and 10
- `seed_history.py` (Task 8) must run before the first full end-to-end test
- `dashboard_capture.py` requires Playwright Chromium — installed in Task 1 Step 3
