# Workflow Simplification Design

## Goal

Make the transcript optional. When provided, AI generates deal updates as today. When absent, the user fills in updates manually. Either way, Finalise uses AI to merge written updates into history summaries, then generates the PDF download.

Remove the Regenerate button — it is no longer needed.

## New Workflow

```
WITH TRANSCRIPT                          WITHOUT TRANSCRIPT
──────────────────                       ──────────────────
Generate (transcript + optional PDF)     Generate (optional PDF only)
  → AI: draft_updates_from_transcript()    → No AI for deals
  → AI: extract_upsell_items()             → AI: extract_upsell_items() (if PDF)
  → Present deals with AI drafts           → Present deals: existing summaries,
                                             blank Update fields

          ↓ User edits deal Update fields, excludes deals ↓

Finalise (both paths identical)
  → AI: update_summaries_from_updates()  (batch, only deals with non-empty updates)
  → save_history() + set_last_run_date()
  → Generate HLS + PDF → download
```

## `ai_writer.py` Changes

### Remove
- `draft_report_content()` — replaced by the two functions below

### Rename / Simplify
- **`draft_updates_from_transcript(deals, transcript, history) → dict`**
  Equivalent to the existing `draft_report_content()` but without the `portfolio_text` argument (upsell is now separate). Returns `{"deal_updates": [...]}` — same shape as before, no `upsell_items` key.

### Add
- **`extract_upsell_items(portfolio_text: str) → list[str]`**
  Focused single-purpose call: reads the portfolio report text, returns a list of upsell opportunity strings. Called only when a PDF is uploaded.

- **`update_summaries_from_updates(deals: list[dict]) → dict[str, list[str]]`**
  Batch call for deals that have non-empty `update_lines`. Input: list of `{deal, existing_summary_lines, update_lines}`. Returns `{deal_name: [updated_summary_lines]}`. The AI must preserve all existing factual detail (trust names, sites, values, dates, incumbents) and incorporate the new update. Uses the same "PRESERVE DETAILS" rule as the existing prompt.

### Keep Unchanged
- `generate_high_level_summary(deals)` — still used at PDF generation time
- `_parse_response()`, `_empty_result()`, `_format_deals()`, `_format_summaries()`, `_hls_fallback()` — unchanged

## `main.py` Changes

### `/generate` route — split on transcript presence

```python
transcript = request.form.get("transcript", "").strip()

if transcript:
    # AI path (same as today, minus portfolio upsell)
    history = load_history()
    ai = draft_updates_from_transcript(deals, transcript, history)
    all_updates = ai.get("deal_updates", [])
    _enrich_stage(all_updates, deal_stage_map)
    for item in all_updates:
        item["excluded"] = not should_include(item["deal"], history, discussed=item.get("mentioned", False))
else:
    # No-transcript path: build updates from history only, blank update fields
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
```

Upsell (either path):
```python
portfolio_text = ""
pdf_file = request.files.get("portfolio_pdf")
if pdf_file and pdf_file.filename:
    path = os.path.join(UPLOAD_FOLDER, "portfolio.pdf")
    pdf_file.save(path)
    portfolio_text = extract_portfolio_text(path)

upsell_items = extract_upsell_items(portfolio_text) if portfolio_text else []
```

Store `dashboard_b64` to disk for PDF use (as per PDF export spec).

### `/regenerate` route — delete entirely

### `/pdf` route (from PDF export spec) — add summary-update step

Insert before saving history:

```python
# Update summaries for deals with non-empty updates
# Must run AFTER _enrich_stage (step 5 in PDF export spec) and BEFORE update_deal() (step 7)
deals_with_updates = [
    {
        "deal":                   item["deal"],
        "existing_summary_lines": item.get("summary_lines", []),
        "update_lines":           item["update_lines"],
    }
    for item in deals  # `deals` = data.get("deals", []) from POST body
    if item["update_lines"] and not item.get("excluded", False)
]
if deals_with_updates:
    updated = update_summaries_from_updates(deals_with_updates)
    for item in deals:
        if item["deal"] in updated:
            item["summary_lines"] = updated[item["deal"]]
```

Then proceed with save, HLS generation, and PDF rendering as per PDF export spec.

## `templates/report.html` Changes

### Remove
- Regenerate button (`#regenerateBtn`) and its `onclick="regenerate()"` handler
- `regenerate()` JS function
- `actionStatus` span (or repurpose for Finalise status only — keep as `#actionStatus`)

### `mentioned` flag (no-transcript path)
The server sets `mentioned: false` on all deals when no transcript is provided. In `collectDeals()`, override `mentioned` to `true` if `updateTA.value.trim()` is non-empty and not equal to `"No update."`. This ensures the "Discussed" pill and orange border appear as the user types, and `last_discussed_date` is set correctly in history.

Updated `collectDeals()`:
```javascript
const rawUpdate = updateTA ? updateTA.value.trim() : '';
const hasUpdate = rawUpdate !== '' && rawUpdate !== 'No update.';
deals.push({
  deal:          block.dataset.deal,
  mentioned:     hasUpdate || block.dataset.mentioned === 'true',
  excluded:      excludeCB ? excludeCB.checked : false,
  summary_lines: summaryTA ? summaryTA.value.split('\n').filter(l => l.trim()) : [],
  update_lines:  updateTA  ? updateTA.value.split('\n').filter(l => l.trim())  : [],
});
```

### `high_level_summary` collection
HLS is generated entirely server-side at `/pdf` time. The Finalise POST body does **not** include a `high_level_summary` field. Remove `#highLevelSection` and `#summaryTbody` from `report.html` — they were only populated by Regenerate, which is now removed. The HLS exists only in the downloaded PDF.

## `templates/index.html` Changes

- Transcript textarea: add `placeholder` text clarifying it is optional
- Remove `required` attribute if present
- Label changes from "Meeting Transcript" to "Meeting Transcript (optional)"

## Files Touched

| File | Change |
|---|---|
| `ai_writer.py` | Remove `draft_report_content()`; add `extract_upsell_items()`, `update_summaries_from_updates()`; rename remaining function |
| `main.py` | Split `/generate` on transcript; delete `/regenerate`; update `/pdf` to call `update_summaries_from_updates()` before save |
| `templates/report.html` | Remove Regenerate button + JS; update `collectDeals()`; remove HLS section |
| `templates/index.html` | Make transcript textarea optional |

## Out of Scope

- Per-deal "AI is updating…" progress indicator
- Undo/revert for AI-updated summaries (history editor already handles manual corrections)
- Selective transcript processing (always processes full transcript if provided)
