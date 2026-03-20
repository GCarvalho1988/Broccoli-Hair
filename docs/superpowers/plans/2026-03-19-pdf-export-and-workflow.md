# PDF Export & Workflow Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `window.print()` with a Playwright-generated PDF download, make the transcript optional, remove the Regenerate button, and have Finalise use AI to update history summaries before saving and generating the PDF.

**Architecture:** The `/generate` route splits on transcript presence — with transcript it calls AI as before (minus portfolio), without it loads history directly. A new `/pdf` route replaces `/save` + `window.print()`: it runs AI summary updates for edited deals, saves history, renders a clean `pdf.html` template, and uses Playwright to produce an A4 PDF download. `ai_writer.py` is refactored into three focused functions.

**Tech Stack:** Python 3.14, Flask, Jinja2, Playwright sync API (already installed), Anthropic claude-sonnet-4-6, matplotlib, Smartsheet SDK.

**Specs:** `docs/superpowers/specs/2026-03-19-pdf-export-design.md` and `docs/superpowers/specs/2026-03-19-workflow-simplification-design.md`

---

## File Map

| File | Status | Purpose |
|---|---|---|
| `pdf_renderer.py` | **Create** | Playwright PDF rendering — single function `render_pdf(html) → bytes` |
| `templates/pdf.html` | **Create** | Clean A4 Jinja2 template for PDF output |
| `ai_writer.py` | **Modify** | Remove `draft_report_content`; add `draft_updates_from_transcript`, `extract_upsell_items`, `update_summaries_from_updates` |
| `main.py` | **Modify** | Update `/generate`; add `/pdf`; remove `/regenerate` and `/save` |
| `templates/report.html` | **Modify** | Remove Regenerate button + JS; remove HLS section; update `collectDeals()` and `finalise()` |
| `templates/index.html` | **Modify** | Make transcript textarea optional |

---

## Task 1: `pdf_renderer.py` — Playwright PDF module

**Files:**
- Create: `pdf_renderer.py`

- [ ] **Step 1: Create `pdf_renderer.py`**

```python
"""
Renders an HTML string to A4 PDF bytes using Playwright (Chromium).
Uses the sync API — same as dashboard_capture.py.
"""
from playwright.sync_api import sync_playwright

_FOOTER = (
    '<div style="font-size:8px;color:#aaa;width:100%;'
    'text-align:center;font-family:Arial,sans-serif;">'
    'Page <span class="pageNumber"></span>'
    ' &nbsp;·&nbsp; Confidential — Sectra UK&amp;I</div>'
)


def render_pdf(html: str) -> bytes:
    """
    Render HTML to A4 PDF and return raw bytes.
    Raises on Playwright error — caller must handle.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            return page.pdf(
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template="<div></div>",
                footer_template=_FOOTER,
                margin={
                    "top":    "12mm",
                    "bottom": "16mm",
                    "left":   "14mm",
                    "right":  "14mm",
                },
            )
        finally:
            browser.close()
```

- [ ] **Step 2: Smoke-test the renderer manually**

Start a Python shell in the project root:
```python
from pdf_renderer import render_pdf
pdf = render_pdf("<html><body><h1>Test</h1></body></html>")
assert isinstance(pdf, bytes) and pdf[:4] == b'%PDF'
print("OK — got", len(pdf), "bytes")
```
Expected: `OK — got NNNN bytes` (typically 20–60 KB for trivial HTML).

- [ ] **Step 3: Commit**

```bash
git add pdf_renderer.py
git commit -m "feat: add Playwright PDF renderer module"
```

---

## Task 2: `ai_writer.py` — Refactor into three focused functions

**Files:**
- Modify: `ai_writer.py`

The existing `draft_report_content()` is renamed and simplified. Two new functions are added. `generate_high_level_summary()` is unchanged.

- [ ] **Step 1: Replace `ai_writer.py` with the refactored version**

Write the entire file (preserving `generate_high_level_summary` and all helpers):

```python
"""
Claude API calls for the weekly report.

draft_updates_from_transcript() — AI drafts deal updates from a transcript.
extract_upsell_items()           — AI extracts upsell items from a portfolio PDF.
update_summaries_from_updates()  — AI merges new update text into existing summaries.
generate_high_level_summary()    — One-liner per deal, used at PDF generation time.
"""
import json, re
import anthropic
from config import ANTHROPIC_API_KEY, MODEL
from history import get_deal

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ─── 1. Draft updates from transcript ────────────────────────────────────────

def draft_updates_from_transcript(deals: list[dict], transcript: str,
                                   history: dict) -> dict:
    """
    Returns:
    {
      "deal_updates": [
        {
          "deal": str,
          "mentioned": bool,
          "update_lines": [str],
          "summary_action": "unchanged" | "updated" | "new",
          "summary_lines": [str]
        }
      ]
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

---

TASK: Produce a JSON response with exactly this structure (no markdown, no extra text — raw JSON only):

{{
  "deal_updates": [
    {{
      "deal": "<exact Smartsheet deal name>",
      "mentioned": <true|false>,
      "update_lines": ["<bullet 1>", "<bullet 2>"],
      "summary_action": "<unchanged|updated|new>",
      "summary_lines": ["<line 1>", "<line 2>", "..."]
    }}
  ]
}}

RULES:
1. DEAL NAME MATCHING: Map every transcript mention to the exact Smartsheet deal name.
   The meeting follows Smartsheet pipeline order — use this to resolve abbreviations.
   Examples: NCL → North Central London (Radiology), Barts → Barts Health, NENC → North East and North Cumbria Digital Pathology.

2. DEAL UPDATES: Include ALL active deals, not just mentioned ones.
   - If mentioned: write 1–2 concise bullet points summarising the discussion. No fluff.
   - If not mentioned: set mentioned=false, update_lines=["No update."]
   - Do not use markdown bold (**). Do not repeat the deal name in the update text.

3. SUMMARY LINES: Each deal needs a summary covering: customer background, sites covered,
   current vendors, deal value, and key events to date — in bullet-point format.
   - summary_action="unchanged": existing summary is fine, return it as-is
   - summary_action="updated": there is significant new info — return the full updated summary
   - summary_action="new": no existing summary — draft one from Smartsheet data and transcript.
     If you have very little data, draft what you can and flag the first line as "[AI DRAFT — please review]"

4. PRESERVE DETAILS: Never remove or overwrite specific factual details already in the existing summary.
   This includes: NHS trust/ICB/CCG/board names, number of sites, current incumbent vendors,
   deal values and contract periods, key dates, clinical/pathology context, geography.
   If there is new information, ADD it. Summaries should grow and improve, never shrink or lose facts.
"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=10000,
        messages=[{"role": "user", "content": prompt}]
    )

    if not message.content:
        print("Empty response from AI")
        return _empty_result(deals, history)
    raw = message.content[0].text
    return _parse_response(raw, deals, history)


# ─── 2. Extract upsell items from portfolio PDF ───────────────────────────────

def extract_upsell_items(portfolio_text: str) -> list[str]:
    """
    Extract upsell / cross-sell opportunities from a portfolio report.
    Returns a list of short opportunity strings, or [] if none found.
    """
    if not portfolio_text.strip():
        return []

    prompt = f"""You are helping a UK medical imaging software sales team identify upsell and cross-sell opportunities.

Extract concrete opportunities from the portfolio report below.
Include: product upgrades, contract renewals, expansion to new sites, new module sales, support contract extensions.
Be specific — name the customer and opportunity where possible. If none, return [].

PORTFOLIO REPORT:
{portfolio_text[:3000]}

Respond with raw JSON only — a list of strings (no markdown):
["<opportunity 1>", "<opportunity 2>", ...]"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    if not message.content:
        return []
    raw = message.content[0].text
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        print(f"extract_upsell_items: invalid JSON: {raw[:200]}")
        return []


# ─── 3. Update summaries from written updates ─────────────────────────────────

def update_summaries_from_updates(deals: list[dict]) -> dict[str, list[str]]:
    """
    For each deal with new update_lines, merge them into the existing summary.

    Input:  [{"deal": str, "existing_summary_lines": [str], "update_lines": [str]}]
    Returns: {"deal name": [updated_summary_lines], ...}

    Deals not present in the input are not returned (caller only passes deals with updates).
    Returns {} on error — caller falls back to existing summaries.
    """
    if not deals:
        return {}

    deals_block = ""
    for d in deals:
        deals_block += f"\n\n=== {d['deal']} ===\n"
        deals_block += "EXISTING SUMMARY:\n"
        for line in d["existing_summary_lines"]:
            deals_block += f"  - {line}\n"
        deals_block += "NEW UPDATE THIS WEEK:\n"
        for line in d["update_lines"]:
            deals_block += f"  - {line}\n"

    prompt = f"""You are updating deal summaries for a UK medical imaging software sales pipeline (Sectra UK&I).

For each deal below, produce an updated summary by merging the NEW UPDATE into the EXISTING SUMMARY.

RULES:
1. PRESERVE all existing factual details: NHS trust/ICB/CCG/board names, number of sites,
   current incumbent vendors, deal values and contract periods, key dates, clinical/pathology
   context, geography, stage history. Never remove or overwrite these facts.
2. ADD information from the new update. If the update is already captured in the summary,
   return the summary unchanged.
3. Summaries must be a bullet-point list of concise factual statements.
4. Do not add padding or repetition. Summaries should grow in accuracy, not length.
{deals_block}

Respond with raw JSON only (no markdown):
{{
  "<exact deal name>": ["updated bullet 1", "updated bullet 2", ...],
  ...
}}"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}]
    )

    if not message.content:
        return {}
    raw = message.content[0].text
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        result = json.loads(raw)
        return {k: v for k, v in result.items() if isinstance(v, list)}
    except json.JSONDecodeError:
        print(f"update_summaries_from_updates: invalid JSON: {raw[:200]}")
        return {}


# ─── 4. High-level summary (unchanged) ───────────────────────────────────────

def generate_high_level_summary(deals: list[dict]) -> list[dict]:
    """
    Generate a one-liner per deal from its summary lines only.
    Input:   [{"deal", "stage", "stage_num", "summary_lines", "forecast"}]
    Returns: [{"deal", "stage", "stage_num", "one_liner", "forecast"}]
    """
    if not deals:
        return []

    deals_text = "\n\n".join(
        f'{d["deal"]}:\n' + "\n".join(
            f"  - {s}" for s in (d.get("summary_lines") or ["(no summary)"])
        )
        for d in deals
    )

    prompt = f"""You are helping write a weekly sales pipeline report for Sectra UK.

For each deal below, write ONE concise sentence describing the current pipeline status.
Base your answer ONLY on the summary provided. Do not add external information.
Be specific and direct. Use present tense. Do not start with the deal name.

{deals_text}

Respond with raw JSON only — no markdown, no extra text:
[
  {{"deal": "<exact deal name>", "one_liner": "<one sentence>"}},
  ...
]"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    if not message.content:
        return [_hls_fallback(d) for d in deals]

    raw = message.content[0].text
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)

    try:
        items = json.loads(raw)
        result_map = {item["deal"].lower(): item["one_liner"]
                      for item in items if "deal" in item}
        return [
            {
                "deal":      d["deal"],
                "stage":     d.get("stage", ""),
                "stage_num": d.get("stage_num", "0"),
                "one_liner": result_map.get(d["deal"].lower(), ""),
                "forecast":  d.get("forecast", ""),
            }
            for d in deals
        ]
    except (json.JSONDecodeError, KeyError):
        return [_hls_fallback(d) for d in deals]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _hls_fallback(d: dict) -> dict:
    lines = d.get("summary_lines") or []
    return {
        "deal":      d["deal"],
        "stage":     d.get("stage", ""),
        "stage_num": d.get("stage_num", "0"),
        "one_liner": lines[0] if lines else "",
        "forecast":  d.get("forecast", ""),
    }


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
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)

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
    return {"deal_updates": updates}
```

- [ ] **Step 2: Verify Python syntax**

```bash
python -c "import ai_writer; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ai_writer.py
git commit -m "refactor: split ai_writer into focused functions; add update_summaries_from_updates and extract_upsell_items"
```

---

## Task 3: `main.py` — Update `/generate` route and save dashboard image

**Files:**
- Modify: `main.py`

The `/generate` route splits on transcript presence. Portfolio PDF goes via `extract_upsell_items()`. Dashboard b64 is written to disk for the `/pdf` route.

- [ ] **Step 1: Replace the `/generate` route in `main.py`**

Replace the entire `generate()` function (lines 49–103) with:

```python
@app.route("/generate", methods=["POST"])
def generate():
    transcript = request.form.get("transcript", "").strip()

    # Store transcript for reference (kept for session but no longer drives regenerate)
    session["transcript"] = transcript

    # ── Portfolio PDF → upsell items ─────────────────────────────────────────
    portfolio_text = ""
    upsell_items   = []
    pdf_file = request.files.get("portfolio_pdf")
    if pdf_file and pdf_file.filename:
        path = os.path.join(UPLOAD_FOLDER, "portfolio.pdf")
        pdf_file.save(path)
        portfolio_text = extract_portfolio_text(path)
    if portfolio_text:
        upsell_items = extract_upsell_items(portfolio_text)

    # ── Dashboard screenshot ──────────────────────────────────────────────────
    dashboard_b64 = None
    try:
        png = capture_dashboard()
        dashboard_b64 = base64.b64encode(png).decode("utf-8")
        # Persist for /pdf route (single-user app — last generate wins)
        with open(os.path.join(UPLOAD_FOLDER, "last_dashboard.b64"), "w") as fh:
            fh.write(dashboard_b64)
    except Exception as e:
        print(f"Dashboard capture failed: {e}")

    # ── Pipeline data + chart ─────────────────────────────────────────────────
    deals = fetch_pipeline_data()
    quadrant_b64 = generate_quadrant(deals)

    # ── Deal updates: transcript path vs. no-transcript path ─────────────────
    history        = load_history()
    deal_stage_map = {d["Opportunity"].lower(): d for d in deals}

    if transcript:
        ai          = draft_updates_from_transcript(deals, transcript, history)
        all_updates = ai.get("deal_updates", [])
        _enrich_stage(all_updates, deal_stage_map)
        for item in all_updates:
            mentioned       = item.get("mentioned", False)
            item["excluded"] = not should_include(item["deal"], history, discussed=mentioned)
    else:
        all_updates = []
        for d in deals:
            entry = get_deal(d["Opportunity"], history)
            all_updates.append({
                "deal":           d["Opportunity"],
                "mentioned":      False,
                "update_lines":   [],
                "summary_action": "unchanged",
                "summary_lines":  entry.get("summary_lines", []) if entry else [],
                "excluded":       not should_include(d["Opportunity"], history, discussed=False),
            })
        _enrich_stage(all_updates, deal_stage_map)

    # Excluded deals sink to bottom; within each group preserve Smartsheet order
    all_updates.sort(key=lambda x: 1 if x.get("excluded") else 0)

    return render_template("report.html",
        report_date=_report_date_str(),
        fy_week=_fy_week(),
        dashboard_b64=dashboard_b64,
        quadrant_b64=quadrant_b64,
        deal_updates=all_updates,
        upsell_items=upsell_items,
        stage_colours=STAGE_COLOURS,
    )
```

- [ ] **Step 2: Update imports at top of `main.py`**

Replace the current import line:
```python
from ai_writer import draft_report_content, generate_high_level_summary
```
With:
```python
from ai_writer import (draft_updates_from_transcript, extract_upsell_items,
                        update_summaries_from_updates, generate_high_level_summary)
```

Also add `get_deal` to the history import:
```python
from history import (load_history, save_history, update_deal,
                     set_last_run_date, should_include, get_deal)
```

- [ ] **Step 3: Verify Python syntax**

```bash
python -c "import main; print('OK')"
```
Expected: `OK` (will warn about missing env vars if .env not loaded — that's fine)

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: make transcript optional in /generate; persist dashboard image for PDF route"
```

---

## Task 4: `main.py` — Add `/pdf` route

**Files:**
- Modify: `main.py`

This is the new Finalise endpoint. It runs AI summary updates, saves history, renders the PDF template, and returns the file download.

- [ ] **Step 1: Add `pdf_renderer` import at top of `main.py`**

```python
from pdf_renderer import render_pdf
```

- [ ] **Step 2: Add the `/pdf` route to `main.py`** (add after the `/generate` route)

```python
@app.route("/pdf", methods=["POST"])
def generate_pdf():
    """
    Finalise: AI-update summaries → save history → render PDF → download.
    Accepts JSON: { deals, upsell_items, report_date, fy_week }
    """
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400

    client_deals = data.get("deals", [])
    upsell_items = data.get("upsell_items", [])
    report_date  = data.get("report_date", _report_date_str())
    fy_week      = data.get("fy_week", _fy_week())

    # ── 1. Enrich with stage data from Smartsheet ─────────────────────────────
    try:
        deals_from_sheet = fetch_pipeline_data()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Smartsheet fetch failed: {e}"}), 500

    deal_stage_map = {d["Opportunity"].lower(): d for d in deals_from_sheet}
    _enrich_stage(client_deals, deal_stage_map)

    # ── 2. AI: merge update text into summaries (only edited, non-excluded deals) ──
    deals_needing_update = [
        {
            "deal":                   item["deal"],
            "existing_summary_lines": item.get("summary_lines", []),
            "update_lines":           item["update_lines"],
        }
        for item in client_deals
        if item.get("update_lines") and not item.get("excluded", False)
        and any(l.strip() and l.strip() != "No update." for l in item["update_lines"])
    ]
    if deals_needing_update:
        updated_summaries = update_summaries_from_updates(deals_needing_update)
        for item in client_deals:
            if item["deal"] in updated_summaries:
                item["summary_lines"] = updated_summaries[item["deal"]]

    # ── 3. Save history ───────────────────────────────────────────────────────
    history = load_history()
    today   = data.get("run_date", date.today().isoformat())
    for item in client_deals:
        if item.get("excluded", False):
            continue
        mentioned = item.get("mentioned", False)
        update_deal(
            history, item["deal"],
            summary_lines=item.get("summary_lines"),
            update_lines=item.get("update_lines"),
            discussed=mentioned,
            report_date=today,
        )
    set_last_run_date(history, today)
    save_history(history)

    # ── 4. Charts and images ──────────────────────────────────────────────────
    dashboard_b64 = None
    b64_path = os.path.join(UPLOAD_FOLDER, "last_dashboard.b64")
    if os.path.exists(b64_path):
        with open(b64_path) as fh:
            dashboard_b64 = fh.read().strip() or None

    try:
        quadrant_b64 = generate_quadrant(deals_from_sheet)
    except Exception as e:
        print(f"Quadrant generation failed: {e}")
        quadrant_b64 = None

    # ── 5. High-level summary ─────────────────────────────────────────────────
    non_excluded = [
        {
            "deal":          item["deal"],
            "stage":         item.get("stage", ""),
            "stage_num":     item.get("stage_num", "0"),
            "summary_lines": item.get("summary_lines", []),
            "forecast":      item.get("forecast", ""),
        }
        for item in client_deals
        if not item.get("excluded", False)
    ]
    high_level_summary = generate_high_level_summary(non_excluded)
    _enrich_stage(high_level_summary, deal_stage_map)

    # ── 6. Render PDF ─────────────────────────────────────────────────────────
    html = render_template(
        "pdf.html",
        deal_updates=client_deals,
        upsell_items=upsell_items,
        high_level_summary=high_level_summary,
        dashboard_b64=dashboard_b64,
        quadrant_b64=quadrant_b64,
        report_date=report_date,
        fy_week=fy_week,
        stage_colours=STAGE_COLOURS,
    )

    try:
        pdf_bytes = render_pdf(html)
    except Exception as e:
        print(f"PDF render failed: {e}")
        return jsonify({"ok": False, "error": f"PDF generation failed: {e}"}), 500

    filename = f"SM_Weekly_Report_Week_{fy_week}.pdf"
    from flask import Response as FlaskResponse
    return FlaskResponse(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 3: Verify syntax**

```bash
python -c "import main; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add /pdf route — AI summary updates, history save, Playwright PDF download"
```

---

## Task 5: `main.py` — Remove `/regenerate` and `/save` routes

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Delete the `/regenerate` route** (the entire `regenerate()` function, approximately lines 106–161 of the original file)

Remove the function decorated with `@app.route("/regenerate", methods=["POST"])` and its entire body.

- [ ] **Step 2: Delete the `/save` route** (the entire `save()` function)

Remove the function decorated with `@app.route("/save", methods=["POST"])` and its entire body.

Also remove `update_deal` from the `from ai_writer import` line if it was only used there (it's used in `/pdf` now so keep it in the history import).

- [ ] **Step 3: Verify syntax and that no other code references the removed functions**

```bash
python -c "import main; print('OK')"
grep -n "regenerate\|/save" main.py
```
Expected: `OK`, and grep shows no remaining route definitions for these paths (only comments or test code if any).

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: remove /regenerate and /save routes — replaced by /pdf"
```

---

## Task 6: `templates/pdf.html` — Clean A4 PDF template

**Files:**
- Create: `templates/pdf.html`

- [ ] **Step 1: Create `templates/pdf.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>S&amp;M Weekly Report — Week {{ fy_week }}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Barlow:wght@300;400;500;600&family=Barlow+Condensed:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --navy:   #004688;
      --deep:   #003260;
      --orange: #F58025;
      --cyan:   #0A93CD;
      --pale:   #EEF4FB;
      --border: #c5d5e8;
      --body:   #1e2d3d;
      --muted:  #5a6a7a;
      --white:  #ffffff;
    }

    html {
      font-size: 11px;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }

    body {
      font-family: 'Barlow', Arial, sans-serif;
      color: var(--body);
      background: var(--white);
    }

    /* ── Page breaks ─────────────────────────────────────────────────────── */
    .page-break { page-break-after: always; }

    /* ── Page header strip (appears on every section) ────────────────────── */
    .page-header {
      background: var(--deep);
      padding: 5mm 0 4mm;
      margin-bottom: 6mm;
      display: flex;
      align-items: baseline;
      gap: 6mm;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    .page-header-wordmark {
      font-family: 'Barlow Condensed', Arial Narrow, sans-serif;
      font-size: 1.2rem;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--white);
    }
    .page-header-sub {
      font-size: 0.75rem;
      font-weight: 300;
      color: rgba(255,255,255,0.55);
      letter-spacing: 0.06em;
    }
    .page-header-week {
      margin-left: auto;
      font-family: 'Barlow Condensed', Arial Narrow, sans-serif;
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--orange);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    /* ── Cover page ──────────────────────────────────────────────────────── */
    .cover-page {
      display: flex;
      flex-direction: column;
      height: 240mm;
    }
    .cover-images {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 5mm;
      overflow: hidden;
    }
    .cover-dashboard { flex: 55; overflow: hidden; }
    .cover-quadrant  { flex: 45; overflow: hidden; }
    .cover-dashboard img,
    .cover-quadrant  img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      object-position: top center;
      display: block;
    }
    .cover-no-dashboard {
      display: flex;
      align-items: center;
      justify-content: center;
      flex: 1;
    }

    /* ── Section wrapper ─────────────────────────────────────────────────── */
    .section-card {
      border-top: 3px solid var(--orange);
      border-radius: 2px;
      overflow: hidden;
      margin-bottom: 6mm;
    }
    .section-heading {
      font-family: 'Barlow Condensed', Arial Narrow, sans-serif;
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--white);
      background: var(--navy);
      padding: 3mm 5mm;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }

    /* ── High-level summary table ─────────────────────────────────────────── */
    .hls-table { width: 100%; border-collapse: collapse; }
    .hls-table th {
      font-family: 'Barlow Condensed', Arial Narrow, sans-serif;
      font-size: 0.62rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      padding: 3mm 4mm;
      border-bottom: 1.5px solid var(--border);
      text-align: left;
    }
    .hls-table td {
      padding: 2.5mm 4mm;
      font-size: 0.82rem;
      font-weight: 300;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }
    .hls-table tr:last-child td { border-bottom: none; }
    .hls-table tr:nth-child(even) td { background: var(--pale); }
    .hls-deal  { font-weight: 600; color: var(--navy); width: 22%; white-space: nowrap; }
    .hls-stage { width: 22%; }
    .hls-fore  { width: 12%; text-align: right; white-space: nowrap; font-size: 0.78rem; }

    /* ── Stage badge ──────────────────────────────────────────────────────── */
    .badge {
      display: inline-block;
      font-family: 'Barlow Condensed', Arial Narrow, sans-serif;
      font-size: 0.6rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 0.2em 0.6em;
      border-radius: 2px;
      color: #fff;
      white-space: nowrap;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    .badge--light { color: #3a2d00; }

    /* ── Deal blocks ──────────────────────────────────────────────────────── */
    .deals-body { padding: 0 5mm 3mm; }
    .deal-block {
      break-inside: avoid;
      border-bottom: 1px solid var(--border);
      padding: 4mm 0 4mm 5mm;
      border-left: 3px solid transparent;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    .deal-block:last-child { border-bottom: none; }

    .deal-header {
      display: flex;
      align-items: center;
      gap: 4mm;
      margin-bottom: 3mm;
      flex-wrap: wrap;
    }
    .deal-name {
      font-family: 'Barlow Condensed', Arial Narrow, sans-serif;
      font-size: 1rem;
      font-weight: 700;
      letter-spacing: 0.01em;
      color: var(--navy);
    }
    .discussed-pill {
      display: inline-block;
      font-family: 'Barlow Condensed', Arial Narrow, sans-serif;
      font-size: 0.58rem;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      padding: 0.15em 0.6em;
      border-radius: 2px;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    .discussed-pill--yes {
      background: rgba(245,128,37,0.12);
      color: var(--orange);
      border: 1px solid rgba(245,128,37,0.35);
    }
    .discussed-pill--no {
      background: var(--pale);
      color: var(--muted);
      border: 1px solid var(--border);
    }
    .deal-meta {
      font-size: 0.7rem;
      font-weight: 300;
      color: var(--muted);
      margin-left: auto;
    }

    .deal-section { margin-bottom: 2.5mm; }
    .deal-section-label {
      font-family: 'Barlow Condensed', Arial Narrow, sans-serif;
      font-size: 0.58rem;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 1.5mm;
    }
    .deal-section-lines { padding-left: 3mm; }
    .deal-line {
      font-size: 0.8rem;
      font-weight: 300;
      line-height: 1.55;
      color: var(--body);
      padding-left: 0.8em;
      text-indent: -0.8em;
    }
    .deal-line::before { content: "–  "; color: var(--muted); }

    /* ── Upsell section ───────────────────────────────────────────────────── */
    .upsell-body { padding: 4mm 5mm; }
    .upsell-line {
      font-size: 0.82rem;
      font-weight: 300;
      line-height: 1.6;
      padding-left: 0.8em;
      text-indent: -0.8em;
    }
    .upsell-line::before { content: "–  "; color: var(--muted); }
  </style>
</head>
<body>

  {# ── Page 1: Dashboard + Quadrant ──────────────────────────────────────── #}
  <div class="page-break">
    <div class="page-header">
      <span class="page-header-wordmark">Sectra</span>
      <span class="page-header-sub">Sales &amp; Marketing · UK&amp;I</span>
      <span class="page-header-week">Week {{ fy_week }} &nbsp;·&nbsp; {{ report_date }}</span>
    </div>

    <div class="cover-page">
      {% if dashboard_b64 or quadrant_b64 %}
      <div class="cover-images">
        {% if dashboard_b64 %}
        <div class="cover-dashboard">
          <img src="data:image/png;base64,{{ dashboard_b64 }}" alt="Pipeline Dashboard">
        </div>
        {% endif %}
        {% if quadrant_b64 %}
        <div class="cover-quadrant">
          <img src="data:image/png;base64,{{ quadrant_b64 }}" alt="Deal Quadrant">
        </div>
        {% endif %}
      </div>
      {% else %}
      <div class="cover-no-dashboard" style="color: #999; font-size: 0.85rem;">
        No dashboard image available for this report.
      </div>
      {% endif %}
    </div>
  </div>

  {# ── Page 2: High-Level Summary ─────────────────────────────────────────── #}
  <div class="page-break">
    <div class="page-header">
      <span class="page-header-wordmark">Sectra</span>
      <span class="page-header-sub">Sales &amp; Marketing · UK&amp;I</span>
      <span class="page-header-week">Week {{ fy_week }} &nbsp;·&nbsp; {{ report_date }}</span>
    </div>

    <div class="section-card">
      <div class="section-heading">High-Level Summary</div>
      <table class="hls-table">
        <thead>
          <tr>
            <th>Deal</th>
            <th>Stage</th>
            <th>Status</th>
            <th class="hls-fore">Forecast</th>
          </tr>
        </thead>
        <tbody>
          {% for item in high_level_summary %}
          {%- set colour = stage_colours.get(item.stage_num, '#888888') -%}
          {%- set light  = (item.stage_num == '2') -%}
          <tr>
            <td class="hls-deal">{{ item.deal }}</td>
            <td class="hls-stage">
              <span class="badge{% if light %} badge--light{% endif %}"
                    style="background-color:{{ colour }}">{{ item.stage }}</span>
            </td>
            <td>{{ item.one_liner }}</td>
            <td class="hls-fore">{{ item.forecast }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  {# ── Pages 3+: Detailed Updates ─────────────────────────────────────────── #}
  <div>
    <div class="page-header">
      <span class="page-header-wordmark">Sectra</span>
      <span class="page-header-sub">Sales &amp; Marketing · UK&amp;I</span>
      <span class="page-header-week">Week {{ fy_week }} &nbsp;·&nbsp; {{ report_date }}</span>
    </div>

    <div class="section-card">
      <div class="section-heading">Detailed Updates</div>
      <div class="deals-body">
        {% for item in deal_updates %}
        {% if not item.excluded %}
        {%- set colour = stage_colours.get(item.stage_num, '#888888') -%}
        {%- set light  = (item.stage_num == '2') -%}
        <div class="deal-block" style="border-left-color:{{ colour }}">
          <div class="deal-header">
            <span class="deal-name">{{ item.deal }}</span>
            <span class="badge{% if light %} badge--light{% endif %}"
                  style="background-color:{{ colour }}">{{ item.stage }}</span>
            {% if item.mentioned %}
              <span class="discussed-pill discussed-pill--yes">&#10003; Discussed</span>
            {% else %}
              <span class="discussed-pill discussed-pill--no">No update</span>
            {% endif %}
            {% if item.forecast or item.rep %}
            <span class="deal-meta">
              {% if item.forecast %}{{ item.forecast }}{% endif %}
              {% if item.forecast and item.rep %} · {% endif %}
              {% if item.rep %}{{ item.rep }}{% endif %}
            </span>
            {% endif %}
          </div>

          {% if item.summary_lines %}
          <div class="deal-section">
            <div class="deal-section-label">Summary</div>
            <div class="deal-section-lines">
              {% for line in item.summary_lines %}
              <div class="deal-line">{{ line }}</div>
              {% endfor %}
            </div>
          </div>
          {% endif %}

          {% set real_updates = item.update_lines | selectattr('__str__', 'ne', 'No update.') | list %}
          {% if item.update_lines and (item.update_lines | join('') | trim) and item.update_lines != ['No update.'] %}
          <div class="deal-section">
            <div class="deal-section-label">Update</div>
            <div class="deal-section-lines">
              {% for line in item.update_lines %}
              {% if line.strip() and line.strip() != 'No update.' %}
              <div class="deal-line">{{ line }}</div>
              {% endif %}
              {% endfor %}
            </div>
          </div>
          {% endif %}
        </div>
        {% endif %}
        {% endfor %}
      </div>
    </div>

    {% if upsell_items %}
    <div class="section-card">
      <div class="section-heading">Upsell &amp; Other Updates</div>
      <div class="upsell-body">
        {% for item in upsell_items %}
        <div class="upsell-line">{{ item }}</div>
        {% endfor %}
      </div>
    </div>
    {% endif %}
  </div>

</body>
</html>
```

- [ ] **Step 2: Verify Jinja2 syntax by running the app and loading `/history-editor`** (just a smoke test that Flask loads templates without parse errors)

```bash
python main.py &
curl -s http://localhost:5000/history-editor | grep -c "deal-card\|No deals"
```
Expected: returns a number ≥ 0 (page loads without 500 error). Kill the background server after.

- [ ] **Step 3: Commit**

```bash
git add templates/pdf.html
git commit -m "feat: add clean A4 PDF template for Playwright rendering"
```

---

## Task 7: `templates/report.html` — Remove Regenerate, update Finalise, remove HLS

**Files:**
- Modify: `templates/report.html`

Four changes: (1) add `data-fy-week` to body, (2) remove Regenerate button, (3) remove HLS section, (4) replace `regenerate()` + `finalise()` JS with new `finalise()`.

- [ ] **Step 1: Update the `<body>` tag** to add `data-fy-week`

Change:
```html
<body data-report-date="{{ report_date | e }}">
```
To:
```html
<body data-report-date="{{ report_date | e }}" data-fy-week="{{ fy_week }}">
```

- [ ] **Step 2: Remove the Regenerate button from the toolbar**

Remove this line from the toolbar:
```html
<button id="regenerateBtn" class="btn btn--regenerate" onclick="regenerate()">Regenerate</button>
```

Also remove the `.btn--regenerate` CSS rule (the `background: transparent; color: rgba(255,255,255,0.8)...` block).

- [ ] **Step 3: Remove the High-Level Summary section**

Remove the entire `<section class="report-section summary-section section--hidden" id="highLevelSection">` block (including its `</section>` closing tag). This section was only populated by Regenerate.

- [ ] **Step 4: Replace the JS functions** — remove `regenerate()`, update `collectDeals()`, replace `finalise()`

In the `<script>` block, replace everything from `/* ── Exclude checkbox behaviour */` down to `</script>` with:

```javascript
    /* ── Reorder deals: included first, excluded last ───────────────── */
    function reorderDeals() {
      const list = document.querySelector('.deals-list');
      if (!list) return;
      const blocks = [...list.querySelectorAll('.deal-block')];
      const included = blocks.filter(b => !b.querySelector('.exclude-checkbox')?.checked);
      const excluded  = blocks.filter(b =>  b.querySelector('.exclude-checkbox')?.checked);
      [...included, ...excluded].forEach(b => list.appendChild(b));
    }

    /* ── Exclude checkbox behaviour ─────────────────────────────────── */
    function initExclude() {
      document.querySelectorAll('.exclude-checkbox').forEach(cb => {
        cb.closest('.deal-block').classList.toggle('deal-block--excluded', cb.checked);
        cb.addEventListener('change', () => {
          cb.closest('.deal-block').classList.toggle('deal-block--excluded', cb.checked);
          reorderDeals();
        });
      });
    }
    initExclude();

    /* ── Collect current deal state from DOM ────────────────────────── */
    function collectDeals() {
      const deals = [];
      document.querySelectorAll('.deal-block').forEach(block => {
        const summaryTA = block.querySelector('.summary-textarea');
        const updateTA  = block.querySelector('.update-textarea');
        const excludeCB = block.querySelector('.exclude-checkbox');
        const rawUpdate = updateTA ? updateTA.value.trim() : '';
        const hasUpdate = rawUpdate !== '' && rawUpdate !== 'No update.';
        deals.push({
          deal:          block.dataset.deal,
          mentioned:     hasUpdate || block.dataset.mentioned === 'true',
          excluded:      excludeCB ? excludeCB.checked : false,
          summary_lines: summaryTA ? summaryTA.value.split('\n').filter(l => l.trim()) : [],
          update_lines:  updateTA  ? updateTA.value.split('\n').filter(l => l.trim())  : [],
        });
      });
      return deals;
    }

    /* ── Escape HTML ────────────────────────────────────────────────── */
    function esc(s) {
      return String(s)
        .replace(/&/g,'&amp;').replace(/</g,'&lt;')
        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    /* ── Finalise: AI updates summaries → save → PDF download ──────── */
    async function finalise() {
      const btn    = document.getElementById('finaliseBtn');
      const status = document.getElementById('actionStatus');
      const upsellTA = document.getElementById('upsellTextarea');

      btn.disabled = true;
      status.textContent = 'Saving & generating PDF… (~30s)';
      status.className = '';

      const fyWeek    = parseInt(document.body.dataset.fyWeek, 10);
      const reportDate = document.body.dataset.reportDate || '';

      try {
        const res = await fetch('/pdf', {
          method:  'POST',
          headers: {'Content-Type': 'application/json'},
          body:    JSON.stringify({
            deals:       collectDeals(),
            upsell_items: upsellTA ? upsellTA.value.split('\n').filter(l => l.trim()) : [],
            report_date: reportDate,
            fy_week:     fyWeek,
          }),
        });

        if (!res.ok) {
          let msg = 'PDF generation failed';
          try { const d = await res.json(); msg = d.error || msg; } catch (_) {}
          throw new Error(msg);
        }

        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `SM_Weekly_Report_Week_${fyWeek}.pdf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        status.textContent = '✓ Saved & downloaded';
        status.className   = 'ok';
      } catch (e) {
        status.textContent = '✗ ' + e.message;
        status.className   = 'err';
      } finally {
        btn.disabled = false;
        setTimeout(() => { status.textContent = ''; status.className = ''; }, 8000);
      }
    }
```

- [ ] **Step 5: Verify the template renders** — load the generate page and confirm no JS errors in browser console

Start the app, navigate to `/`, submit the form (with or without transcript), verify the report page loads and the Finalise button is the only action button in the toolbar.

- [ ] **Step 6: Commit**

```bash
git add templates/report.html
git commit -m "feat: remove Regenerate, remove HLS section, update Finalise to POST /pdf and download"
```

---

## Task 8: `templates/index.html` — Make transcript optional

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Find the transcript textarea and its label in `index.html`**

Search for the transcript field label and the `<textarea>` element.

- [ ] **Step 2: Update the label to mark transcript as optional**

Change the label text from "Meeting Transcript" (or similar) to:
```
Meeting Transcript <span style="font-weight:300;opacity:0.6">(optional)</span>
```

- [ ] **Step 3: Remove `required` attribute from transcript textarea if present**

Find `<textarea ... name="transcript"` and remove `required` if present.

- [ ] **Step 4: Update placeholder text** to explain what happens without it:

```
Paste the Teams meeting transcript here. Leave blank to manually fill in updates.
```

- [ ] **Step 5: Remove server-side transcript validation in `main.py`**

In `main.py`, find and remove this guard (it's no longer needed):
```python
if not transcript:
    return "Please paste the meeting transcript.", 400
```

- [ ] **Step 6: Verify** — load `/`, submit form with no transcript, confirm report page loads and shows all deals with blank update fields.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html main.py
git commit -m "feat: make transcript optional — no-transcript path shows blank update fields"
```

---

## Final Verification

- [ ] **End-to-end with transcript:** Load `/`, paste a transcript snippet, click Generate → report loads with AI-generated updates → click Finalise → PDF downloads, history.json updated.

- [ ] **End-to-end without transcript:** Load `/`, leave transcript blank, click Generate → report loads with existing summaries and blank update fields → fill in one update manually → click Finalise → PDF downloads, that deal's history summary is updated, others unchanged.

- [ ] **PDF quality check:** Open the downloaded PDF → Page 1 has dashboard + quadrant on one page → Page 2 has High-Level Summary table → Pages 3+ have deal blocks with correct stage colours, no editing controls, clean typography.

- [ ] **History editor:** Load `/history-editor` → confirm the manually updated deal's summary shows the AI-merged content.
