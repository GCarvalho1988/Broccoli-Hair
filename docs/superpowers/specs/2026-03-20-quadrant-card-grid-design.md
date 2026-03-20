# Quadrant Card Grid — Design Spec

**Date:** 2026-03-20
**Status:** Approved

## Problem

The current matplotlib scatter chart places ~15 deals in a 10×10 coordinate space. Deals cluster heavily in the top-right (Flagship Projects) quadrant, causing label collisions that the existing bounding-box repulsion algorithm cannot fully resolve. Labels overlap, connector lines cross, and the chart is hard to read at PDF resolution.

## Solution

Replace the scatter chart with a **2×2 card grid**. Each quadrant zone contains the deals that belong to it, displayed as coloured chip labels sorted by sales stage. No coordinates are plotted — only quadrant membership and stage are conveyed.

## Interface

No change to the public interface:

```python
generate_quadrant(deals: list[dict]) -> str  # base64 PNG, same as before
```

The same base64 PNG is embedded in both the HTML report and the PDF template without modification.

If the filtered deal list is empty (all deals lack Profitability/Strategic Fit scores, or the input is empty), the function returns an empty string `""`. The templates' existing `{% if quadrant_b64 %}` guards will suppress the section cleanly.

## Data Shape

Each deal dict is expected to have:

| Key | Type | Notes |
|-----|------|-------|
| `Opportunity` | str | Deal name displayed on the chip |
| `Strategic Fit` | float or None | 0–10; y-axis value |
| `Profitability` | float or None | 0–10; x-axis value (labelled "Revenue" in the chart) |
| `Stage Number` | str | `"0"`–`"6"`; used for chip colour and sort order |

Deals where `Strategic Fit` or `Profitability` is `None` are silently excluded.

**Axis label note:** The x-axis is labelled `"Revenue →"` in the chart but maps to the `Profitability` field in the data. This matches the existing implementation.

## Quadrant Boundary

- Strategic Fit `>= 5.0` → top row; `< 5.0` → bottom row
- Profitability `>= 5.0` → right column; `< 5.0` → left column
- Scores of exactly `5.0` on either axis are treated as `>= 5.0`

## Visual Design

### Overall layout

- Single matplotlib figure: `figsize=(12, 10)`, `dpi=120`
- Four zone subplots via `GridSpec(2, 2, hspace=0.08, wspace=0.08)` with a thin shared padding
- Outer axis frame (spanning the full figure) carries the axis labels; all spines hidden except bottom and left

### Zone mapping

| Zone | Row | Col | Background | Header colour |
|------|-----|-----|------------|---------------|
| Strategy Plays | 0 | 0 | `#EEF4FB` | `#1565C0` |
| Flagship Projects | 0 | 1 | `#F1F8E9` | `#2E7D32` |
| Questionable | 1 | 0 | `#F5F5F5` | `#888888` |
| Core Revenue | 1 | 1 | `#E0F7FA` | `#00838F` |

### Zone header

Each zone displays its name in the top-left using `ax.text()`:
- Position: axes coordinates `(0.04, 0.94)`, `va='top'`, `ha='left'`
- Style: `fontsize=9`, `fontweight='bold'`, uppercase via `.upper()`, `color=header_colour`, `alpha=0.55`

### Deal chips

**Coordinate space:** each zone axes uses the default `xlim=(0,1)`, `ylim=(0,1)` in axes fraction coordinates.

**Layout constants:**
- `x_start = 0.04` — left margin
- `y_start = 0.80` — top of chip area (below zone header)
- `col_width = 0.31` — horizontal step between chip columns
- `row_height = 0.17` — vertical step between chip rows
- `chips_per_row = 3`
- Font size tiers:
  - ≤ 9 deals in zone: `fontsize=8.5`
  - 10–15 deals: `fontsize=7.5`
  - > 15 deals: `fontsize=6.5`
- If after applying the smallest font size there are still more chips than fit in `floor((0.80 / row_height)) * chips_per_row` rows, excess chips are silently truncated and a grey `"+N more"` label is appended at the next chip position.

**Chip rendering:**
```
ax.text(x, y, deal_name,
        fontsize=fontsize, color='white', fontweight='bold',
        ha='left', va='center',
        transform=ax.transAxes,
        bbox=dict(boxstyle='round,pad=0.3',
                  facecolor=stage_colour,
                  edgecolor='none',
                  alpha=0.92))
```

**Position calculation** (row-major, left-to-right then top-to-bottom):
```python
col = index % chips_per_row
row = index // chips_per_row
x = x_start + col * col_width
y = y_start - row * row_height
```

### Sort order

Deals within each zone are sorted by **stage number descending** using `int(stage_num)` (numeric sort). Non-numeric or missing Stage Number values are treated as `0`. Stage 6 (Preferred Supplier) appears first; Stage 0 (One to Watch) appears last.

### Axis labels

Rendered on a transparent overlay axes (`fig.add_axes([0, 0, 1, 1])`) with all spines and ticks hidden:
- `"Revenue →"` — `ax.set_xlabel(...)`, centred, `fontsize=13`, `fontweight='bold'`
- `"Strategic Fit →"` — `ax.set_ylabel(...)`, centred, `fontsize=13`, `fontweight='bold'`

## Files Changed

| File | Change |
|------|--------|
| `charts.py` | Full rewrite of `generate_quadrant()`. Remove `_spread_points()` and `_place_labels()` helpers entirely. |

No other files change.

## Out of Scope

- Interactive hover/tooltip (chart is a static PNG)
- Showing forecast value on chips (stage colour is sufficient signal)
- Preserving exact x/y coordinate position within each quadrant
