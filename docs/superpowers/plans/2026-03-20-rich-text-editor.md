# Rich Text Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace plain `<textarea>` elements in the report UI with Quill.js rich text editors so that bold, italic, bullets, and highlight formatting carry through to the exported PDF.

**Architecture:** Add HTML conversion helpers to `ai_writer.py`, update `history.py` to store HTML instead of plain-text arrays, update `main.py` routes to consume/produce HTML, update `pdf.html` to render HTML directly, and mount Quill editors in `report.html` as the final step. Each task is independently committable; tasks 1 and 2 must land before 3, and task 3 before tasks 4 and 5.

**Tech Stack:** Python 3, Flask/Jinja2, Quill.js 2.0.3 (CDN), Playwright (PDF), pytest

**Spec:** `docs/superpowers/specs/2026-03-20-rich-text-editor-design.md`

---

### Task 1: `ai_writer.py` — HTML helpers and update internal history reads

**Files:**
- Modify: `ai_writer.py`
- Create: `tests/test_ai_writer_helpers.py`

#### Background

`ai_writer.py` currently reads `entry.get("summary_lines")` from history in three internal functions. After Task 2 migrates history to `summary_html`, those reads will silently return `[]`. This task adds the conversion helpers and fixes the three affected functions. The AI prompt signatures and outputs are **unchanged** — only the history-reading side changes.

`re` is already imported at line 9 of `ai_writer.py`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_ai_writer_helpers.py`:

```python
# tests/test_ai_writer_helpers.py
from ai_writer import _html_to_text, _lines_to_html


def test_html_to_text_strips_tags():
    assert _html_to_text("<p>Hello</p>") == "Hello"


def test_html_to_text_preserves_block_boundaries():
    result = _html_to_text("<p>Line 1</p><p>Line 2</p>")
    assert "Line 1" in result and "Line 2" in result
    assert result.index("Line 1") < result.index("Line 2")


def test_html_to_text_handles_none():
    assert _html_to_text(None) == ""


def test_html_to_text_handles_empty():
    assert _html_to_text("") == ""


def test_html_to_text_handles_quill_empty_paragraph():
    # Quill emits <p><br></p> for empty paragraphs
    result = _html_to_text("<p><br></p>")
    assert result.strip() == ""


def test_html_to_text_handles_list():
    result = _html_to_text("<ul><li>Item A</li><li>Item B</li></ul>")
    assert "Item A" in result and "Item B" in result


def test_lines_to_html_wraps_in_paragraphs():
    assert _lines_to_html(["Hello", "World"]) == "<p>Hello</p><p>World</p>"


def test_lines_to_html_skips_blank_lines():
    assert _lines_to_html(["", "Hello", ""]) == "<p>Hello</p>"


def test_lines_to_html_empty_list():
    assert _lines_to_html([]) == ""
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_ai_writer_helpers.py -v
```

Expected: `ImportError` or `AttributeError` — `_html_to_text` not yet defined.

- [ ] **Step 3: Add helpers to `ai_writer.py`**

Add the two functions after the `client = ...` line (line 14), before the first section comment:

```python
def _html_to_text(html: str) -> str:
    """Strip HTML, preserving block boundaries as newlines.

    Quill emits empty paragraphs as <p><br></p>, which produces two newlines
    (one from <br>, one from </p>). The \\n{3,} collapse fires for 3+, so
    empty paragraphs appear as blank lines. This is intentional.
    """
    text = re.sub(r'</p>|</li>|<br\s*/?>', '\n', html or '', flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


def _lines_to_html(lines: list[str]) -> str:
    """Wrap plain text lines in <p> tags."""
    return ''.join(f'<p>{line}</p>' for line in lines if line.strip())
```

- [ ] **Step 4: Run tests — expect pass**

```
pytest tests/test_ai_writer_helpers.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Update `_format_summaries` to read `summary_html`**

Replace the existing `_format_summaries` function (lines 309–319) with:

```python
def _format_summaries(deals: list[dict], history: dict) -> str:
    lines = []
    for d in deals:
        entry = get_deal(d["Opportunity"], history)
        summary_text = _html_to_text(entry.get("summary_html", "")) if entry else ""
        if summary_text.strip():
            lines.append(f"\n{d['Opportunity']}:")
            for s in summary_text.split('\n'):
                if s.strip():
                    lines.append(f"  - {s.strip()}")
        else:
            lines.append(f"\n{d['Opportunity']}: (no summary on record)")
    return "\n".join(lines)
```

- [ ] **Step 6: Update `_parse_response` fallback to read `summary_html`**

In `_parse_response` (around line 336–344), find the block that adds fallback entries for deals not in the AI response:

```python
# FIND this block:
entry = get_deal(d["Opportunity"], history)
data.setdefault("deal_updates", []).append({
    "deal": d["Opportunity"],
    "mentioned": False,
    "update_lines": ["No update."],
    "summary_action": "unchanged",
    "summary_lines": entry.get("summary_lines", []) if entry else [],
})

# REPLACE with:
entry = get_deal(d["Opportunity"], history)
summary_lines = (
    [l for l in _html_to_text(entry.get("summary_html", "")).splitlines() if l.strip()]
    if entry else []
)
data.setdefault("deal_updates", []).append({
    "deal": d["Opportunity"],
    "mentioned": False,
    "update_lines": ["No update."],
    "summary_action": "unchanged",
    "summary_lines": summary_lines,
})
```

- [ ] **Step 7: Replace `_empty_result` to read `summary_html`**

Replace the entire `_empty_result` function (lines 349–360):

```python
def _empty_result(deals: list[dict], history: dict) -> dict:
    updates = []
    for d in deals:
        entry = get_deal(d["Opportunity"], history)
        summary_lines = (
            [l for l in _html_to_text(entry.get("summary_html", "")).splitlines() if l.strip()]
            if entry else []
        )
        updates.append({
            "deal": d["Opportunity"],
            "mentioned": False,
            "update_lines": ["No update."],
            "summary_action": "unchanged",
            "summary_lines": summary_lines,
        })
    return {"deal_updates": updates}
```

- [ ] **Step 8: Run all tests**

```
pytest tests/ -v
```

Expected: all tests PASS (test_charts.py + test_ai_writer_helpers.py).

- [ ] **Step 9: Commit**

```bash
git add ai_writer.py tests/test_ai_writer_helpers.py
git commit -m "feat: add html/text conversion helpers and update history reads in ai_writer"
```

---

### Task 2: `history.py` — New `update_deal()` signature + migration on read

**Files:**
- Modify: `history.py`
- Create: `tests/test_history_html.py`

#### Background

`history.py` stores `summary_lines` and `last_update_lines` as plain `string[]` in `history.json`. We change the storage fields to `summary_html` / `last_update_html` (HTML strings). `load_history()` migrates old entries on read and removes the old keys. `update_deal()` gets new parameter names.

- [ ] **Step 1: Write failing tests**

Create `tests/test_history_html.py`:

```python
# tests/test_history_html.py
from history import load_history, update_deal, save_history
import json, os, tempfile


def _make_old_history():
    """Simulates a history.json written by the old code."""
    return {
        "_meta": {"last_run_date": "2026-03-13"},
        "alpha deal": {
            "display_name": "Alpha Deal",
            "summary_lines": ["Pilot agreed", "Meeting next week"],
            "last_update_lines": ["Discussed pricing"],
            "last_discussed_date": "2026-03-13",
            "last_included_date": "2026-03-13",
        }
    }


def test_load_history_migrates_summary_lines(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_make_old_history()), encoding="utf-8")
    monkeypatch.setattr("history.HISTORY_FILE", str(path))

    h = load_history()
    entry = h["alpha deal"]

    assert "summary_html" in entry
    assert "<p>Pilot agreed</p>" in entry["summary_html"]
    assert "<p>Meeting next week</p>" in entry["summary_html"]
    assert "summary_lines" not in entry


def test_load_history_migrates_last_update_lines(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_make_old_history()), encoding="utf-8")
    monkeypatch.setattr("history.HISTORY_FILE", str(path))

    h = load_history()
    entry = h["alpha deal"]

    assert "last_update_html" in entry
    assert "<p>Discussed pricing</p>" in entry["last_update_html"]
    assert "last_update_lines" not in entry


def test_update_deal_stores_summary_html():
    h = {"_meta": {}}
    update_deal(h, "Beta Deal", summary_html="<p>New summary</p>", report_date="2026-03-20")
    assert h["beta deal"]["summary_html"] == "<p>New summary</p>"
    assert "summary_lines" not in h["beta deal"]


def test_update_deal_stores_update_html():
    h = {"_meta": {}}
    update_deal(h, "Beta Deal", update_html="<ul><li>Item</li></ul>", report_date="2026-03-20")
    assert h["beta deal"]["last_update_html"] == "<ul><li>Item</li></ul>"
    assert "last_update_lines" not in h["beta deal"]


def test_update_deal_does_not_overwrite_when_none():
    h = {"_meta": {}, "gamma deal": {"display_name": "Gamma", "summary_html": "<p>Old</p>"}}
    update_deal(h, "Gamma Deal", summary_html=None, report_date="2026-03-20")
    assert h["gamma deal"]["summary_html"] == "<p>Old</p>"
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_history_html.py -v
```

Expected: several FAILs — `update_deal` still takes old param names, migration not yet implemented.

- [ ] **Step 3: Update `load_history()` to migrate old entries**

In `history.py`, update `load_history()` to add migration after loading the JSON. The current function (lines 25–29) is:

```python
def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"_meta": {"last_run_date": None}}
```

Replace with:

```python
def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {"_meta": {"last_run_date": None}}
    # Migrate old plain-text arrays to HTML strings
    for key, entry in history.items():
        if key == "_meta":
            continue
        if "summary_lines" in entry and "summary_html" not in entry:
            entry["summary_html"] = "".join(
                f"<p>{l}</p>" for l in entry["summary_lines"] if l.strip()
            )
            entry.pop("summary_lines")
        if "last_update_lines" in entry and "last_update_html" not in entry:
            entry["last_update_html"] = "".join(
                f"<p>{l}</p>" for l in entry["last_update_lines"] if l.strip()
            )
            entry.pop("last_update_lines")
    return history
```

- [ ] **Step 4: Update `update_deal()` signature**

Replace the existing `update_deal()` function (lines 87–104) with:

```python
def update_deal(history: dict, name: str, *,
                summary_html=None, update_html=None,
                discussed: bool = False,
                report_date: str = None) -> None:
    """Write back a deal's data after a report run."""
    k = _key(name)
    today = report_date or date.today().isoformat()
    if k not in history:
        history[k] = {"display_name": name.strip()}
    entry = history[k]
    entry["display_name"] = name.strip()
    if summary_html is not None:
        entry["summary_html"] = summary_html
    if update_html is not None:
        entry["last_update_html"] = update_html
    entry["last_included_date"] = today
    if discussed:
        entry["last_discussed_date"] = today
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_history_html.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Run full test suite**

```
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add history.py tests/test_history_html.py
git commit -m "feat: migrate history storage to summary_html/last_update_html"
```

---

### Task 3: `main.py` — Route updates

**Files:**
- Modify: `main.py`
- Create: `tests/test_main_helpers.py`

#### Background

`main.py` needs: (a) module-level imports of the new helpers; (b) a module-level `_html_is_empty()` function; (c) `/pdf` route updated to consume `summary_html`/`update_html` and call `update_deal()` with the new signature; (d) `/generate` no-transcript path updated to read `summary_html` from history; (e) `/history-editor` routes updated to strip/restore HTML.

Note: `re` is **not** currently imported in `main.py` — it must be added.

- [ ] **Step 1: Write failing tests**

Create `tests/test_main_helpers.py`:

```python
# tests/test_main_helpers.py
# Tests for module-level helpers that will be added to main.py.
# Import them from main to confirm they exist and work.

import pytest


def test_html_is_empty_with_quill_empty_paragraph():
    from main import _html_is_empty
    assert _html_is_empty("<p><br></p>") is True


def test_html_is_empty_with_real_content():
    from main import _html_is_empty
    assert _html_is_empty("<p>Hello</p>") is False


def test_html_is_empty_with_none():
    from main import _html_is_empty
    assert _html_is_empty(None) is True


def test_html_is_empty_with_empty_string():
    from main import _html_is_empty
    assert _html_is_empty("") is True


def test_html_is_empty_with_whitespace_only():
    from main import _html_is_empty
    assert _html_is_empty("<p>   </p>") is True
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_main_helpers.py -v
```

Expected: `ImportError` — `_html_is_empty` not yet defined in `main.py`.

- [ ] **Step 3: Add module-level imports and `_html_is_empty` to `main.py`**

At the top of `main.py`, line 1 currently reads `import os, base64, io`. Make these changes:

**Add `import re`** — change line 1 to:
```python
import os, re, base64, io
```

**Add import after the existing `from ai_writer import ...` line** (currently line 12–13):
```python
from ai_writer import (draft_updates_from_transcript, extract_upsell_items,
                        update_summaries_from_updates, generate_high_level_summary,
                        _html_to_text, _lines_to_html)
```

**Add `_html_is_empty` after `_fy_week` (after line 46), before `_enrich_stage`:**
```python
def _html_is_empty(html: str) -> bool:
    """Return True if the HTML contains no meaningful text content."""
    text = re.sub(r'<[^>]+>', '', html or '').replace('\xa0', ' ').strip()
    return not text
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_main_helpers.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Update the `/pdf` route — auto-exclude + `deals_needing_update` + HTML normalise**

In the `/pdf` route (lines 136–275), make these changes:

**Replace the auto-exclude block** (currently lines 152–156):
```python
# FIND:
    for item in client_deals:
        if not item.get("excluded", False):
            lines = item.get("update_lines", [])
            if not any(l.strip() and l.strip() != "No update." for l in lines):
                item["excluded"] = True

# REPLACE WITH:
    for item in client_deals:
        if not item.get("excluded", False):
            if _html_is_empty(item.get("update_html", "")):
                item["excluded"] = True
```

**Replace `deals_needing_update` construction** (currently lines 168–177):
```python
# FIND:
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

# REPLACE WITH:
    deals_needing_update = [
        {
            "deal":                   item["deal"],
            "existing_summary_lines": [_html_to_text(item.get("summary_html", ""))],
            "update_lines":           [_html_to_text(item.get("update_html", ""))],
        }
        for item in client_deals
        if item.get("update_html") and not item.get("excluded", False)
        and not _html_is_empty(item.get("update_html", ""))
    ]
```

**Replace the `updated_summaries` application** (currently lines 181–183):
```python
# FIND:
        for item in client_deals:
            if item["deal"] in updated_summaries:
                item["summary_lines"] = updated_summaries[item["deal"]]

# REPLACE WITH:
        for item in client_deals:
            if item["deal"] in updated_summaries:
                item["summary_html"] = _lines_to_html(updated_summaries[item["deal"]])
```

**Replace the history save loop** (currently lines 191–201):
```python
# FIND:
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

# REPLACE WITH:
    for item in client_deals:
        if item.get("excluded", False):
            continue
        mentioned = item.get("mentioned", False)
        update_deal(
            history, item["deal"],
            summary_html=item.get("summary_html"),
            update_html=item.get("update_html"),
            discussed=mentioned,
            report_date=today,
        )
```

**Replace `non_excluded` construction** (currently lines 232–243):
```python
# FIND:
    non_excluded = [
        {
            "deal":          item["deal"],
            "stage":         item.get("stage", ""),
            "stage_num":     item.get("stage_num", "0"),
            "summary_lines": item.get("summary_lines", []),
            "update_lines":  item.get("update_lines", []),
            "forecast":      item.get("forecast", ""),
        }
        for item in client_deals
        if not item.get("excluded", False)
    ]

# REPLACE WITH:
    non_excluded = [
        {
            "deal":          item["deal"],
            "stage":         item.get("stage", ""),
            "stage_num":     item.get("stage_num", "0"),
            "summary_lines": [_html_to_text(item.get("summary_html", ""))],
            "update_lines":  [_html_to_text(item.get("update_html", ""))],
            "forecast":      item.get("forecast", ""),
        }
        for item in client_deals
        if not item.get("excluded", False)
    ]
```

**Add normalisation pass** immediately before the `render_template("pdf.html", ...)` call (before line 251):
```python
    # Normalise empty Quill output so Jinja {% if %} guards work cleanly
    for item in client_deals:
        if _html_is_empty(item.get("summary_html", "")):
            item["summary_html"] = ""
        if _html_is_empty(item.get("update_html", "")):
            item["update_html"] = ""
```

- [ ] **Step 6: Update `/generate` no-transcript path**

In `main.py` lines 108–120, find the no-transcript `else` block. Change line 117 from:
```python
                "summary_lines":  entry.get("summary_lines", []) if entry else [],
```
to:
```python
                "summary_lines":  (
                    [l for l in _html_to_text(entry.get("summary_html", "")).splitlines() if l.strip()]
                    if entry else []
                ),
```

- [ ] **Step 7: Update `/history-editor` GET route**

In the `/history-editor` route (lines 278–295), replace the `deals.append(...)` block (lines 285–292):
```python
# FIND:
        deals.append({
            "key":                key,
            "display_name":       val.get("display_name", key),
            "summary_lines":      val.get("summary_lines") or [],
            "last_update_lines":  val.get("last_update_lines") or [],
            "last_discussed_date": val.get("last_discussed_date", ""),
            "last_included_date":  val.get("last_included_date", ""),
        })

# REPLACE WITH:
        deals.append({
            "key":                key,
            "display_name":       val.get("display_name", key),
            "summary_lines":      [l for l in _html_to_text(val.get("summary_html", "")).splitlines() if l.strip()],
            "last_update_lines":  [l for l in _html_to_text(val.get("last_update_html", "")).splitlines() if l.strip()],
            "last_discussed_date": val.get("last_discussed_date", ""),
            "last_included_date":  val.get("last_included_date", ""),
        })
```

- [ ] **Step 8: Update `/history-editor/save` POST route**

In the `/history-editor/save` route (lines 298–316), replace lines 313–314:
```python
# FIND:
        entry["summary_lines"]     = [l for l in item.get("summary_lines", []) if l.strip()]
        entry["last_update_lines"] = [l for l in item.get("last_update_lines", []) if l.strip()]

# REPLACE WITH:
        entry["summary_html"]      = _lines_to_html(item.get("summary_lines", []))
        entry["last_update_html"]  = _lines_to_html(item.get("last_update_lines", []))
        entry.pop("summary_lines", None)
        entry.pop("last_update_lines", None)
```

- [ ] **Step 9: Run all tests**

```
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add main.py tests/test_main_helpers.py
git commit -m "feat: update main.py routes to use summary_html/update_html"
```

---

### Task 4: `templates/pdf.html` — Replace line loops with HTML rendering

**Files:**
- Modify: `templates/pdf.html`

No tests — this is a template change verified visually in Task 5's end-to-end smoke test.

- [ ] **Step 1: Add scoped CSS for Quill HTML output**

In `pdf.html`, find the `</style>` closing tag (line 238) and insert the following CSS immediately before it:

```css
    /* ── Rich text HTML from Quill ────────────────────────────────────── */
    .deal-summary p, .deal-update p { margin: 0 0 4px 0; }
    .deal-summary ul, .deal-update ul,
    .deal-summary ol, .deal-update ol  { margin: 2px 0 4px 0; padding-left: 1.2em; }
    .deal-summary li, .deal-update li  { margin-bottom: 2px; }
    /* Highlight: Quill emits inline style="background-color:..." — no rule needed */
```

- [ ] **Step 2: Replace Summary loop**

In the detailed-updates section (around lines 334–343), find:

```html
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
```

Replace with:

```html
          {% if item.summary_html %}
          <div class="deal-section">
            <div class="deal-section-label">Summary</div>
            <div class="deal-summary deal-section-lines">{{ item.summary_html | safe }}</div>
          </div>
          {% endif %}
```

- [ ] **Step 3: Replace Update loop**

Find the update section (around lines 345–357):

```html
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
```

Replace with:

```html
          {% if item.update_html %}
          <div class="deal-section">
            <div class="deal-section-label">Update</div>
            <div class="deal-update deal-section-lines">{{ item.update_html | safe }}</div>
          </div>
          {% endif %}
```

- [ ] **Step 4: Commit**

```bash
git add templates/pdf.html
git commit -m "feat: render summary_html/update_html directly in pdf.html"
```

---

### Task 5: `templates/report.html` — Quill.js editors

**Files:**
- Modify: `templates/report.html`

This is the most visible change. Work section by section.

- [ ] **Step 1: Add Quill CDN tags**

In `report.html`, find the closing `</head>` tag (line 532). Insert immediately before it:

```html
  <link href="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.snow.css" rel="stylesheet" />
```

Find the first `<script>` tag that starts the inline JS (line ~667). Insert immediately before it:

```html
  <script src="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.js"></script>
```

- [ ] **Step 2: Add auto-height CSS for Quill**

In the `<style>` block, find the line `.summary-textarea { min-height: 3rem; }` (line 437). Add immediately after it:

```css
    .ql-editor {
      min-height: 60px;
      height: auto;
    }
    .ql-container { font-family: var(--font-body); font-size: 0.875rem; }
```

- [ ] **Step 3: Update CSS rules that target `.field-textarea`**

Find and replace these two rules:

```css
/* FIND (line 305): */
    .deal-block--excluded .field-textarea { pointer-events: none; }

/* REPLACE WITH: */
    .deal-block--excluded .ql-editor { pointer-events: none; }
```

```css
/* FIND (line 438): */
    .ai-draft .field-textarea { border-color: var(--s-orange); background: var(--ai-bg); }

/* REPLACE WITH: */
    .ai-draft .ql-container { border-color: var(--s-orange); background: var(--ai-bg); }
```

- [ ] **Step 4: Update print media query**

In the `@media print` block, find (lines 528–529):

```css
      .ai-draft .field-textarea,
      .ai-draft { border-color: var(--border) !important; background: transparent !important; }
```

Replace with:

```css
      .ai-draft .ql-container,
      .ai-draft { border-color: var(--border) !important; background: transparent !important; }
```

- [ ] **Step 5: Replace summary textarea + print-only div with Quill mount**

Each deal block currently has (lines 626–632):

```html
            <div>
              <textarea class="field-textarea summary-textarea"
                        data-field="summary">{{ item.summary_lines | join('\n') }}</textarea>
              <div class="print-content print-only" data-print-for="summary">
                {% for line in item.summary_lines %}<p>{{ line }}</p>{% endfor %}
              </div>
            </div>
```

Replace with:

```html
            <div>
              <div class="quill-editor" data-field="summary"
                   data-seed="{{ item.summary_lines | tojson | e }}"></div>
            </div>
```

(The seed data is stored in a `data-seed` attribute to avoid Jinja/JS interpolation issues with the `tojson` filter.)

- [ ] **Step 6: Replace update textarea + print-only div with Quill mount**

Each deal block also has (lines 639–645):

```html
            <div>
              <textarea class="field-textarea update-textarea"
                        data-field="update">{{ item.update_lines | join('\n') }}</textarea>
              <div class="print-content print-only" data-print-for="update">
                {% for line in item.update_lines %}<p>{{ line }}</p>{% endfor %}
              </div>
            </div>
```

Replace with:

```html
            <div>
              <div class="quill-editor" data-field="update"></div>
            </div>
```

- [ ] **Step 7: Add Quill initialisation script**

In the `<script>` block (around line 667), add after `const stageColours = ...;`:

```javascript
    /* ── Quill toolbar config ───────────────────────────────────────── */
    const QUILL_TOOLBAR = [
      ['bold', 'italic'],
      [{ 'background': ['#FFFF00', '#00FF00', false] }],
      [{ 'list': 'bullet' }, { 'list': 'ordered' }],
      [{ 'indent': '-1' }, { 'indent': '+1' }],
    ];

    /* ── Initialise all Quill editors ──────────────────────────────── */
    document.querySelectorAll('.quill-editor').forEach(container => {
      const quill = new Quill(container, {
        theme: 'snow',
        modules: { toolbar: QUILL_TOOLBAR },
      });
      container._quill = quill;

      // Seed summary editors from server-passed lines
      if (container.dataset.field === 'summary') {
        const seed = container.dataset.seed;
        if (seed) {
          try {
            const lines = JSON.parse(seed);
            if (lines && lines.length) {
              const html = '<p>' + lines.join('</p><p>') + '</p>';
              quill.clipboard.dangerouslyPasteHTML(html);
            }
          } catch (e) { /* ignore parse errors */ }
        }
      }
    });
```

- [ ] **Step 8: Replace `collectDeals()` and add `_htmlIsEmpty`**

Find the `collectDeals` function (around lines 707–725) and the `esc` function after it. Replace `collectDeals` and add `_htmlIsEmpty` before it:

```javascript
    /* ── HTML empty check (must be before collectDeals) ────────────── */
    function _htmlIsEmpty(html) {
      return !(html || '').replace(/<[^>]+>/g, '').replace(/\u00a0/g, ' ').trim();
    }

    /* ── Collect current deal state from DOM ───────────────────────── */
    function collectDeals() {
      const deals = [];
      document.querySelectorAll('.deal-block').forEach(block => {
        const summaryEl  = block.querySelector('.quill-editor[data-field="summary"]');
        const updateEl   = block.querySelector('.quill-editor[data-field="update"]');
        const excludeCB  = block.querySelector('.exclude-checkbox');
        const summaryHtml = summaryEl ? summaryEl._quill.root.innerHTML : '';
        const updateHtml  = updateEl  ? updateEl._quill.root.innerHTML  : '';
        const hasUpdate   = !_htmlIsEmpty(updateHtml);
        deals.push({
          deal:         block.dataset.deal,
          mentioned:    hasUpdate || block.dataset.mentioned === 'true',
          excluded:     excludeCB ? excludeCB.checked : false,
          summary_html: summaryHtml,
          update_html:  updateHtml,
        });
      });
      return deals;
    }
```

- [ ] **Step 9: Smoke test — start Flask and verify Quill editors load**

Start the app:
```
python main.py
```

Open `http://localhost:5000`, paste any text as a transcript, click **Generate**.

Verify:
- Each deal card shows a Quill toolbar (bold B, italic I, highlight, bullets) above the editor area
- Summary editors are pre-populated with existing content
- Update editors start empty
- Excluded deals (greyed out) have non-editable Quill editors
- AI-draft deals have an orange border around the Quill container
- Typing in an editor and adding a bullet works

- [ ] **Step 10: End-to-end PDF smoke test**

With the app running, add some formatting to a few deal updates (bold text, a bullet list, highlight). Click **Export PDF**.

Verify in the downloaded PDF:
- Bold text appears bold
- Bullet lists render with visible bullet markers
- Highlighted text has a yellow background
- No `[object Object]` or raw HTML tags visible

- [ ] **Step 11: Commit**

```bash
git add templates/report.html
git commit -m "feat: replace textareas with Quill.js rich text editors"
```

---

### Task 6: Push to GitHub

- [ ] **Step 1: Push all commits**

```bash
git push origin master
```

Expected: all 5 feature commits pushed successfully.
