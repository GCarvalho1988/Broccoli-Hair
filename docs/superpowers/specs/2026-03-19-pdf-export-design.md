# PDF Export Design

## Goal

Replace `window.print()` with a server-side Playwright-rendered PDF download, triggered by the Finalise button. Produces a clean, brand-consistent A4 report with no editing UI.

**Read alongside:** `2026-03-19-workflow-simplification-design.md` — the `/pdf` route incorporates the AI summary-update step from that spec.

## Architecture

Three new pieces:

1. **`pdf_renderer.py`** — wraps Playwright sync API. Accepts HTML string, returns PDF bytes atomically (either complete bytes or raises — no partial streaming).
2. **`templates/pdf.html`** — Jinja2 template for A4 print only. No textboxes, no JS, no interactive elements.
3. **`/pdf` route in `main.py`** — accepts JSON from Finalise, runs AI summary updates, saves history, generates chart, renders `pdf.html`, runs Playwright, returns download.

Supporting change: `/generate` saves `dashboard_b64` to `uploads/last_dashboard.b64` (raw base64 string) so `/pdf` can retrieve it without re-running Playwright.

**Playwright:** Chromium already required by `dashboard_capture.py` — no new installation needed.

**Single-user assumption:** `last_dashboard.b64` is a global file, overwritten each `/generate` call. Acceptable for a single-user local app.

## POST JSON Schema (`/pdf`)

```json
{
  "deals": [
    {
      "deal": "string",
      "mentioned": true,
      "excluded": false,
      "summary_lines": ["string"],
      "update_lines": ["string"]
    }
  ],
  "upsell_items": ["string"],
  "report_date": "19 March 2026",
  "fy_week": 47
}
```

`high_level_summary` is **not** sent by the client — always generated server-side at step 10. `summary_lines` and `update_lines` come from edited textareas via `collectDeals()`.

## `/pdf` Route — Step-by-Step

Order: enrich → AI summary update → save → chart/dashboard → HLS → render.

1. Parse JSON body; return 400 if missing
2. Extract: `deals = data.get("deals", [])`, `upsell_items`, `report_date`, `fy_week`
3. Call `fetch_pipeline_data()` → `deals_from_sheet`
4. Build `deal_stage_map = {d["Opportunity"].lower(): d for d in deals_from_sheet}`
5. Call `_enrich_stage(deals, deal_stage_map)` — adds `stage`, `stage_num`, `forecast`, `rep` in-place. When no match found, defaults: `stage=""`, `stage_num="0"`, `forecast=""`, `rep=""`
6. Call `update_summaries_from_updates()` (see workflow simplification spec) for non-excluded deals with non-empty `update_lines`; merge returned summaries back into `deals` items in-place. Step 5 must complete before this step so `stage`/`forecast` are available on each item
7. Load history; for each non-excluded deal call `update_deal()` using the now AI-merged `summary_lines`; call `set_last_run_date(history, today)`; call `save_history()` once. History is saved at this point — if PDF generation later fails, history is preserved
8. Read `uploads/last_dashboard.b64`; set `dashboard_b64 = None` if file missing
9. Call `generate_quadrant(deals_from_sheet)` → `quadrant_b64` (raw base64 string)
10. Build `summary_inputs = [{deal, stage, stage_num, summary_lines, forecast} for non-excluded d in deals]`; call `generate_high_level_summary(summary_inputs)` → `high_level_summary`
11. Render `pdf.html` with: `deal_updates=deals`, `upsell_items`, `high_level_summary`, `dashboard_b64`, `quadrant_b64`, `report_date`, `fy_week`, `stage_colours`
12. Call `pdf_renderer.render_pdf(html)` → `pdf_bytes`; on exception return `jsonify({"ok": False, "error": "PDF generation failed"})`, status 500
13. Return `Response(pdf_bytes, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="SM_Weekly_Report_Week_{fy_week}.pdf"'})`

## PDF Template Layout (`pdf.html`)

Both images are raw base64 strings. Template constructs full data-URIs:
```html
<img src="data:image/png;base64,{{ dashboard_b64 }}">
<img src="data:image/png;base64,{{ quadrant_b64 }}">
```

### Page 1 — Dashboard & Charts
- Sectra navy header strip: wordmark + "Sales & Marketing · UK&I" + "Week N · date"
- Dashboard screenshot: `max-height: 52vh`, `width: 100%`, `object-fit: contain`
- Quadrant chart: `max-height: 40vh`, `width: 100%`, `object-fit: contain`
- If `dashboard_b64` is None, quadrant expands to fill the page

### Page 2 — High-Level Summary
- Orange-topped section card
- Compact table: Deal | Stage badge | One-liner status | Forecast
- `font-size: 9pt`, tight row padding — designed to fit ≤20 deals on one page
- `page-break-after: always`

### Pages 3+ — Detailed Updates
- One block per non-excluded deal
- Stage-coloured left border (3px inline style)
- Deal name (Barlow Condensed bold) + stage badge + "Discussed / No update" pill + forecast + rep
- **Summary** sub-section: bullet lines at 9pt
- **Update** sub-section: bullet lines at 9pt (omit section if `update_lines` is empty)
- `break-inside: avoid` per block
- Excluded deals omitted entirely

### Page Footer
CSS `@page` margin boxes are not supported by Chromium. Use Playwright's `footer_template`:
```python
footer_template='<div style="font-size:8px;color:#999;width:100%;text-align:center;padding:0 14mm">'
                'Page <span class="pageNumber"></span> · Confidential — Sectra UK&I</div>'
```

## `pdf_renderer.py`

```python
from playwright.sync_api import sync_playwright

FOOTER = (
    '<div style="font-size:8px;color:#999;width:100%;text-align:center;padding:0 14mm">'
    'Page <span class="pageNumber"></span> · Confidential — Sectra UK&I</div>'
)

def render_pdf(html: str) -> bytes:
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
                footer_template=FOOTER,
                margin={"top": "12mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
            )
        finally:
            browser.close()
```

## Finalise JS (`report.html`)

Replace `finalise()`:

1. Call `collectDeals()` → `deals` (includes `summary_lines`, `update_lines`, `mentioned`, `excluded`)
2. Collect upsell: `document.getElementById('upsellTextarea').value.split('\n').filter(l => l.trim())`
3. `const fyWeek = parseInt(document.body.dataset.fyWeek, 10)` — parse to int, not string
4. Read `report_date` from `document.body.dataset.reportDate`
5. POST `{ deals, upsell_items, report_date, fy_week }` to `/pdf` (no `high_level_summary` field)
6. Check `response.ok`; if false: read JSON, show error status, re-enable button — do NOT call `.blob()`
7. On success: `blob()` → object URL → `<a download="SM_Weekly_Report_Week_${fyWeek}.pdf">` → click → `revokeObjectURL()`
8. Show "✓ Saved & downloaded"; re-enable button

## `report.html` Other Changes

**Body tag** — add `data-fy-week`:
```html
<body data-report-date="{{ report_date | e }}" data-fy-week="{{ fy_week }}">
```

**Remove** the `#highLevelSection` and `#summaryTbody` — HLS now exists only in the PDF, not on the editing page. The Regenerate button and its JS are removed per the workflow simplification spec.

## `/generate` Change

After generating `dashboard_b64`:
```python
with open(os.path.join(UPLOAD_FOLDER, "last_dashboard.b64"), "w") as f:
    f.write(dashboard_b64)
```

## Files Touched

| File | Change |
|---|---|
| `pdf_renderer.py` | New |
| `templates/pdf.html` | New |
| `main.py` | Add `/pdf` route; save `last_dashboard.b64` in `/generate` |
| `templates/report.html` | Replace Finalise JS; add `data-fy-week` to `<body>`; remove `#highLevelSection` |

## Out of Scope

- Portrait/landscape toggle
- Email delivery
- Archiving PDFs to disk
- Per-deal forced page breaks
