# Rich Text Editor — Design Spec

**Date:** 2026-03-20
**Status:** Approved

## Problem

Deal update and summary text boxes in `report.html` are plain `<textarea>` elements. Long entries require scrolling, and there is no way to apply formatting (bold, italic, bullets, highlight). The exported PDF lacks formatting control, which makes complex multi-point deal summaries hard to read.

## Solution

Replace the two `<textarea>` elements per deal card with Quill.js rich text editors. Formatting (bold, italic, bullets, numbered lists, highlight, indent) is preserved through the data pipeline and rendered in the PDF.

## Data format conventions

- **`summary_lines`** (plain `string[]`) — the AI-internal format. Used inside `ai_writer.py`, returned by `draft_updates_from_transcript`, and emitted by the `/generate` route to `report.html` for editor seeding.
- **`summary_html`** / `update_html` (HTML `str`) — the storage and PDF format. Used in history, sent by the browser to `/pdf`, and rendered in `pdf.html`.
- Conversion functions `_html_to_text()` / `_lines_to_html()` (defined in `ai_writer.py`) bridge the two formats wherever needed.

## Interface Changes

The browser sends to `/pdf`:

**Before:**
```json
{ "summary_lines": ["line 1", "line 2"], "update_lines": ["..."] }
```

**After:**
```json
{ "summary_html": "<p>Line 1</p><ul><li>Bullet</li></ul>", "update_html": "<p><strong>Bold</strong></p>" }
```

The `/generate` route continues to emit `summary_lines` (plain string arrays) to `report.html` — no change.

## Components

### 1. `templates/report.html` — Quill.js Integration

**Quill CDN tags** — add to `<head>`:
```html
<link href="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.snow.css" rel="stylesheet" />
<script src="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.js"></script>
```

**Editor mount:** Replace each deal card's `<textarea class="field-textarea summary-textarea">` (and its sibling `.print-content.print-only` div) with:
```html
<div class="quill-editor" data-field="summary"></div>
```
Similarly for the update textarea/print-only pair. The `print-only` mirror divs are removed — Quill's `.ql-editor` area renders natively in the browser print path.

**Toolbar config** (identical for all editors):
```javascript
const toolbarOptions = [
  ['bold', 'italic'],
  [{ 'background': ['#FFFF00', '#00FF00', false] }],
  [{ 'list': 'bullet' }, { 'list': 'ordered' }],
  [{ 'indent': '-1' }, { 'indent': '+1' }],
];
```

**Auto-height CSS** — add to the `<style>` block:
```css
.ql-editor {
  min-height: 60px;
  height: auto;
}
```
Setting this on the outer mount container alone is insufficient — this must be on `.ql-editor` (Quill's inner editable div).

**Quill instance storage:** Store each Quill instance directly on the container element (`container._quill = quill`). This avoids deal-name string keying issues.

**Pre-population from `summary_lines`** — seed the summary editor after creation:
```javascript
const lines = {{ item.summary_lines | tojson }};
const seedHtml = lines.length ? '<p>' + lines.join('</p><p>') + '</p>' : '';
if (seedHtml) { container._quill.clipboard.dangerouslyPasteHTML(seedHtml); }
```
The update editor starts empty — `update_lines` is always `[]` from `/generate` for both transcript and no-transcript paths, and the user types fresh each session.

**CSS updates for excluded deals and AI-draft styling:**

Replace the two existing rules that target `.field-textarea`:
```css
/* OLD — remove: */
.deal-block--excluded .field-textarea { pointer-events: none; }
.ai-draft .field-textarea { border-color: var(--s-orange); background: var(--ai-bg); }

/* NEW — add: */
.deal-block--excluded .ql-editor { pointer-events: none; }
.ai-draft .ql-container { border-color: var(--s-orange); background: var(--ai-bg); }
```
Also update the print media query block (lines 527–530 of `report.html`). The existing rule is compound:
```css
.ai-draft .field-textarea,
.ai-draft { border-color: var(--border) !important; background: transparent !important; }
```
Replace the `.field-textarea` selector only; keep the bare `.ai-draft` selector intact:
```css
.ai-draft .ql-container,
.ai-draft { border-color: var(--border) !important; background: transparent !important; }
```

**Data collection (`collectDeals()`)** — add `_htmlIsEmpty` first (it must be declared before `collectDeals` in the same `<script>` block), then replace the existing `collectDeals` function body:
```javascript
// Define before collectDeals — called inside it
function _htmlIsEmpty(html) {
  return !(html || '').replace(/<[^>]+>/g, '').replace(/\u00a0/g, ' ').trim();
}

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

**Excluded deal toggle:** The existing toggle logic shows/hides the `.deal-field` containers — no change needed; the Quill container is inside `.deal-field` and inherits the visibility change.

---

### 2. `main.py` — Module-level imports and `/pdf` Route

Add at the top of `main.py` (module level, alongside the existing imports):
```python
import re  # add to the existing import line or as a new module-level import
from ai_writer import _html_to_text, _lines_to_html
```
These are module-level imports used across the `/pdf` route, the `/generate` route, and both `/history-editor` routes.

Also define `_html_is_empty` at module level (not inside any function), after the imports:
```python
def _html_is_empty(html: str) -> bool:
    """Return True if the HTML contains no meaningful text content."""
    text = re.sub(r'<[^>]+>', '', html or '').replace('\xa0', ' ').strip()
    return not text
```

**`/pdf` route — empty check:** Replace the existing `update_lines` auto-exclude loop:

# Auto-exclude deals with no real update
for item in client_deals:
    if not item.get("excluded", False):
        if _html_is_empty(item.get("update_html", "")):
            item["excluded"] = True
```

**`/pdf` route — `deals_needing_update`:**
```python
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

After `update_summaries_from_updates` returns `updated_summaries` (plain string arrays), convert to HTML:
```python
for item in client_deals:
    if item["deal"] in updated_summaries:
        item["summary_html"] = _lines_to_html(updated_summaries[item["deal"]])
```

**`/pdf` route — `non_excluded` for `generate_high_level_summary`:**
```python
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

**`/pdf` route — history save call:** Pass HTML strings to `update_deal()`:
```python
update_deal(
    history, item["deal"],
    summary_html=item.get("summary_html"),
    update_html=item.get("update_html"),
    discussed=mentioned,
    report_date=today,
)
```

**`/pdf` route — normalise before rendering:** Before passing items to the PDF template, normalise empty Quill output to `""` so the template guard `{% if item.summary_html %}` works cleanly:
```python
for item in client_deals:
    if _html_is_empty(item.get("summary_html", "")):
        item["summary_html"] = ""
    if _html_is_empty(item.get("update_html", "")):
        item["update_html"] = ""
```

**`/generate` route — no-transcript path** (lines 108–120): Change `entry.get("summary_lines", [])` to read from `summary_html`:
```python
"summary_lines": (
    [line for line in _html_to_text(entry.get("summary_html", "")).splitlines() if line.strip()]
    if entry else []
),
```
The `update_lines: []` entry in this path is intentional — the Quill update editor always starts empty, so no seed content is needed.

**`/history-editor` GET route** (lines 285–292): Strip HTML to plain text for the existing template:
```python
deals.append({
    "key":                key,
    "display_name":       val.get("display_name", key),
    "summary_lines":      [l for l in _html_to_text(val.get("summary_html", "")).splitlines() if l.strip()],
    "last_update_lines":  [l for l in _html_to_text(val.get("last_update_html", "")).splitlines() if l.strip()],
    "last_discussed_date": val.get("last_discussed_date", ""),
    "last_included_date":  val.get("last_included_date", ""),
})
```

**`/history-editor/save` POST route** (lines 313–314): Convert plain text to HTML before storing:
```python
entry["summary_html"]      = _lines_to_html(item.get("summary_lines", []))
entry["last_update_html"]  = _lines_to_html(item.get("last_update_lines", []))
entry.pop("summary_lines", None)
entry.pop("last_update_lines", None)
```

---

### 3. `ai_writer.py` — Plain Text Helpers and `_format_summaries`

Add at module level:
```python
import re  # re is already imported in ai_writer.py — no duplicate needed

def _html_to_text(html: str) -> str:
    """Strip HTML, preserving block boundaries as newlines.

    Note: Quill emits empty paragraphs as <p><br></p>, which produces two
    newlines (one from <br>, one from </p>). The \n{3,} collapse only fires
    for 3+, so empty paragraphs appear as blank lines in AI prompts. This is
    acceptable and intentional — blank lines improve AI readability.
    """
    text = re.sub(r'</p>|</li>|<br\s*/?>', '\n', html or '', flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text

def _lines_to_html(lines: list[str]) -> str:
    """Wrap plain text lines in <p> tags."""
    return ''.join(f'<p>{line}</p>' for line in lines if line.strip())
```

**Update `_format_summaries`** to read `summary_html` from history instead of `summary_lines`:
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

**Update `_parse_response`** — when adding fallback entries for deals not mentioned by the AI, read `summary_lines` from `summary_html`:
```python
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

**Update `_empty_result`** — replace the `entry.get("summary_lines", [])` line in both entries with the same pattern (full function body for clarity):
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

`draft_updates_from_transcript` and `update_summaries_from_updates` signatures and prompts are unchanged.

---

### 4. `history.py` — Storage Format

**Update `update_deal()` signature:**
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

**Migration on read (`load_history`):** After loading the JSON, migrate old entries:
```python
for key, entry in history.items():
    if key == "_meta":
        continue
    if "summary_lines" in entry and "summary_html" not in entry:
        entry["summary_html"] = "".join(f"<p>{l}</p>" for l in entry["summary_lines"] if l.strip())
        entry.pop("summary_lines")
    if "last_update_lines" in entry and "last_update_html" not in entry:
        entry["last_update_html"] = "".join(f"<p>{l}</p>" for l in entry["last_update_lines"] if l.strip())
        entry.pop("last_update_lines")
```
Old keys are removed in-memory immediately, so the next `save_history()` call writes only the new keys.

---

### 5. `templates/pdf.html` — HTML Rendering

Replace the current `{% for line in item.summary_lines %}` / `{% for line in item.update_lines %}` loops with guarded direct output:

```html
{% if item.summary_html %}
<div class="deal-summary">{{ item.summary_html | safe }}</div>
{% endif %}
{% if item.update_html %}
<div class="deal-update">{{ item.update_html | safe }}</div>
{% endif %}
```

(The `/pdf` route normalises empty Quill output to `""` before rendering, so these guards cleanly suppress blank divs.)

Add a `<style>` block for PDF-appropriate rendering:

```css
.deal-summary p, .deal-update p { margin: 0 0 4px 0; }
.deal-summary ul, .deal-update ul,
.deal-summary ol, .deal-update ol  { margin: 2px 0 4px 0; padding-left: 1.2em; }
.deal-summary li, .deal-update li  { margin-bottom: 2px; }
```

Note: `padding-left: 1.2em` (not `padding: 0`) is required to keep bullet and number markers visible in Playwright's PDF renderer.

**Highlight:** Quill emits highlight as inline `style="background-color: #ffff00;"` on a `<span>`. Playwright renders inline styles natively — no additional CSS rule is needed. Do not add `mark` or `.ql-bg-yellow` selectors (these do not match Quill's output).

---

## Files Changed

| File | Change |
|------|--------|
| `templates/report.html` | Replace textareas + `print-only` mirror divs with Quill editors; add `_htmlIsEmpty()` JS helper; update `collectDeals()` to read `._quill.root.innerHTML`; update CSS for `.deal-block--excluded` and `.ai-draft` to target Quill elements; add `.ql-editor` auto-height CSS; add Quill CDN tags; seed summary editors from `summary_lines` Jinja data |
| `main.py` | Module-level import of `_html_to_text`/`_lines_to_html` from `ai_writer`; `/pdf` route: new `_html_is_empty()` helper, update empty-check, `deals_needing_update`, `non_excluded`, history save call, normalise empty HTML; `/generate` no-transcript path: read `summary_html` from history; `/history-editor` GET: strip HTML to plain text; `/history-editor/save`: convert plain text to HTML |
| `ai_writer.py` | Add `_html_to_text()` and `_lines_to_html()` (exported); update `_format_summaries()`, `_parse_response()`, `_empty_result()` to use `summary_html` from history |
| `history.py` | Update `update_deal()` signature to `summary_html`/`update_html` params; add migration on read for both fields (remove old keys in-place) |
| `templates/pdf.html` | Replace line loops with guarded `{{ item.summary_html | safe }}`/`{{ item.update_html | safe }}`; add scoped CSS with `padding-left: 1.2em` for lists |

No new files. No changes to `charts.py`, `smartsheet_client.py`, `pdf_renderer.py`, `config.py`, `templates/history.html`.

## Out of Scope

- Font family / font size selectors in the toolbar
- Image embedding in deal text
- Collaborative/multi-user editing
- Undo/redo history persistence across page reloads
- Markdown input mode
- Quill editors in the history editor UI
