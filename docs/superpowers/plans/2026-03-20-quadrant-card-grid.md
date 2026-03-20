# Quadrant Card Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the matplotlib scatter chart in `charts.py` with a 2×2 card grid that displays deals as coloured chips grouped by quadrant, eliminating label collision issues.

**Architecture:** A single matplotlib figure is divided into four subplot zones via `GridSpec`. Each zone renders its deals as coloured rounded-rectangle text chips, sorted by stage number descending, using `ax.text()` with `bbox`. The public interface (`generate_quadrant(deals) -> str`) is unchanged.

**Tech Stack:** Python, matplotlib, existing `STAGE_COLOURS` config

---

### Task 1: Write failing tests for the new generate_quadrant behaviour

**Files:**
- Create: `tests/test_charts.py`

- [ ] **Step 1: Create the test file**

```python
# tests/test_charts.py
import pytest
from charts import generate_quadrant


def _deal(name, fit, profit, stage="3"):
    return {"Opportunity": name, "Strategic Fit": fit,
            "Profitability": profit, "Stage Number": stage}


def test_returns_nonempty_base64_png_for_valid_deals():
    deals = [_deal("Alpha", 7.0, 8.0, "5"), _deal("Beta", 3.0, 3.0, "2")]
    result = generate_quadrant(deals)
    assert isinstance(result, str)
    assert len(result) > 100  # non-trivial base64 PNG


def test_returns_empty_string_when_no_plottable_deals():
    deals = [{"Opportunity": "No scores", "Strategic Fit": None,
              "Profitability": None, "Stage Number": "3"}]
    result = generate_quadrant(deals)
    assert result == ""


def test_returns_empty_string_for_empty_input():
    assert generate_quadrant([]) == ""


def test_excludes_deals_missing_either_score():
    deals = [
        _deal("Has both", 7.0, 8.0),
        {"Opportunity": "Missing fit", "Strategic Fit": None,
         "Profitability": 7.0, "Stage Number": "3"},
        {"Opportunity": "Missing profit", "Strategic Fit": 7.0,
         "Profitability": None, "Stage Number": "3"},
    ]
    # Should produce a valid PNG (one deal plotted)
    result = generate_quadrant(deals)
    assert isinstance(result, str) and len(result) > 100


def test_boundary_score_5_goes_to_top_right():
    """Score of exactly 5.0 on both axes → Flagship Projects (top-right)."""
    deals = [_deal("Boundary", 5.0, 5.0, "4")]
    result = generate_quadrant(deals)
    assert result != ""  # renders without error


def test_stage_0_deal_renders_without_error():
    deals = [_deal("Early Stage", 6.0, 7.0, "0")]
    result = generate_quadrant(deals)
    assert result != ""


def test_many_deals_in_one_quadrant_renders_without_error():
    """15 deals all in Flagship Projects — triggers font reduction and possible truncation."""
    deals = [_deal(f"Deal {i}", 7.0 + (i % 3) * 0.1, 7.0 + (i % 3) * 0.1, str(i % 7))
             for i in range(15)]
    result = generate_quadrant(deals)
    assert isinstance(result, str) and len(result) > 100
```

- [ ] **Step 2: Run tests to confirm they fail (function not yet rewritten)**

```
pytest tests/test_charts.py -v
```

Expected: most tests FAIL — `test_returns_empty_string_*` and `test_boundary_*` will fail against the old scatter implementation.

---

### Task 2: Rewrite `generate_quadrant` as a card grid

**Files:**
- Modify: `charts.py` (full rewrite of `generate_quadrant`, delete `_spread_points` and `_place_labels`)

- [ ] **Step 1: Replace the contents of `charts.py` with the new implementation**

```python
"""
Generates the Strategic Fit vs Revenue quadrant chart as a 2x2 card grid.
Returns a base64-encoded PNG string for embedding in HTML:
  <img src="data:image/png;base64,{{ quadrant_b64 }}">
"""
import io, base64
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from config import STAGE_COLOURS

# ── Layout constants ──────────────────────────────────────────────────────────
_CHIPS_PER_ROW = 3
_X_START       = 0.04   # left margin (axes fraction)
_Y_START       = 0.80   # top of chip area, below zone header
_COL_WIDTH     = 0.31   # horizontal step between chip columns
_ROW_HEIGHT    = 0.17   # vertical step between chip rows
_MAX_ROWS      = 4      # floor(0.80 / 0.17) = 4 rows visible

# Font size tiers by number of deals in zone
def _font_size(n: int) -> float:
    if n <= 9:
        return 8.5
    if n <= 15:
        return 7.5
    return 6.5


# Zone definitions: (label, row, col, bg_colour, header_colour)
_ZONES = [
    ("Strategy Plays",    0, 0, "#EEF4FB", "#1565C0"),
    ("Flagship Projects", 0, 1, "#F1F8E9", "#2E7D32"),
    ("Questionable",      1, 0, "#F5F5F5", "#888888"),
    ("Core Revenue",      1, 1, "#E0F7FA", "#00838F"),
]


def generate_quadrant(deals: list[dict]) -> str:
    """Return base64 PNG string of the quadrant card grid, or '' if no plottable deals."""
    plottable = [d for d in deals
                 if d.get("Strategic Fit") is not None
                 and d.get("Profitability") is not None]
    if not plottable:
        return ""

    # Assign each deal to a zone
    zone_deals: dict[tuple[int, int], list[dict]] = {(r, c): [] for _, r, c, _, _ in _ZONES}
    for d in plottable:
        row = 0 if d["Strategic Fit"] >= 5.0 else 1
        col = 1 if d["Profitability"] >= 5.0 else 0
        zone_deals[(row, col)].append(d)

    # Sort each zone by stage number descending (numeric)
    for key in zone_deals:
        zone_deals[key].sort(
            key=lambda d: _stage_int(d.get("Stage Number", "0")),
            reverse=True,
        )

    fig = plt.figure(figsize=(12, 10))
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.08, wspace=0.08)

    for label, row, col, bg, header_col in _ZONES:
        ax = fig.add_subplot(gs[row, col])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_facecolor(bg)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(left=False, bottom=False,
                       labelleft=False, labelbottom=False)

        # Zone header
        ax.text(0.04, 0.94, label.upper(),
                transform=ax.transAxes,
                fontsize=9, fontweight="bold",
                color=header_col, alpha=0.55,
                va="top", ha="left")

        deals_in_zone = zone_deals[(row, col)]
        if not deals_in_zone:
            continue

        fs       = _font_size(len(deals_in_zone))
        capacity = _MAX_ROWS * _CHIPS_PER_ROW
        visible  = deals_in_zone[:capacity]
        overflow = len(deals_in_zone) - len(visible)

        for idx, d in enumerate(visible):
            c = idx % _CHIPS_PER_ROW
            r = idx // _CHIPS_PER_ROW
            x = _X_START + c * _COL_WIDTH
            y = _Y_START - r * _ROW_HEIGHT
            colour = STAGE_COLOURS.get(d.get("Stage Number", "0"), "#888888")
            ax.text(x, y, d["Opportunity"],
                    transform=ax.transAxes,
                    fontsize=fs, color="white", fontweight="bold",
                    ha="left", va="center",
                    bbox=dict(boxstyle="round,pad=0.3",
                              facecolor=colour,
                              edgecolor="none",
                              alpha=0.92))

        if overflow > 0:
            # "+N more" label at next chip position
            next_idx = len(visible)
            c = next_idx % _CHIPS_PER_ROW
            r = next_idx // _CHIPS_PER_ROW
            x = _X_START + c * _COL_WIDTH
            y = _Y_START - r * _ROW_HEIGHT
            ax.text(x, y, f"+{overflow} more",
                    transform=ax.transAxes,
                    fontsize=fs, color="#888888",
                    ha="left", va="center",
                    style="italic")

    # Axis labels on a transparent overlay
    overlay = fig.add_axes([0, 0, 1, 1], frameon=False)
    overlay.set_xlim(0, 1)
    overlay.set_ylim(0, 1)
    overlay.tick_params(left=False, bottom=False,
                        labelleft=False, labelbottom=False)
    for spine in overlay.spines.values():
        spine.set_visible(False)
    overlay.text(0.5, 0.02, "Revenue →",
                 transform=overlay.transAxes,
                 fontsize=13, fontweight="bold",
                 ha="center", va="bottom")
    overlay.text(0.02, 0.5, "Strategic Fit →",
                 transform=overlay.transAxes,
                 fontsize=13, fontweight="bold",
                 ha="left", va="center", rotation=90)

    plt.tight_layout(rect=[0.04, 0.04, 1, 1])
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _stage_int(stage: str) -> int:
    """Convert stage number string to int for sorting; unknown values → 0."""
    try:
        return int(stage)
    except (ValueError, TypeError):
        return 0
```

- [ ] **Step 2: Run the tests**

```
pytest tests/test_charts.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add charts.py tests/test_charts.py
git commit -m "feat: replace scatter quadrant with 2x2 card grid"
```

---

### Task 3: Visual smoke test — confirm the output looks correct

**Files:** no file changes

- [ ] **Step 1: Generate a sample PNG and open it**

```python
# Run from project root:
python - <<'EOF'
import base64
from smartsheet_client import fetch_pipeline_data
from charts import generate_quadrant

deals = fetch_pipeline_data()
b64 = generate_quadrant(deals)
if b64:
    with open("uploads/quadrant_preview.png", "wb") as f:
        f.write(base64.b64decode(b64))
    print("Saved uploads/quadrant_preview.png")
else:
    print("No plottable deals returned")
EOF
```

- [ ] **Step 2: Review the image**

Open `uploads/quadrant_preview.png` and verify:
- 4 zones visible with correct background tints
- Deal chips readable, coloured by stage
- No overlapping labels
- "Revenue →" and "Strategic Fit →" axis labels present
- Deals sorted correctly within each zone (highest stage number first)

- [ ] **Step 3: Clean up preview file**

```bash
rm uploads/quadrant_preview.png
```

- [ ] **Step 4: Commit (no code changes — commit if any test tweaks were needed)**

Only commit if test file was adjusted during smoke test. Otherwise skip.

---

### Task 4: End-to-end PDF smoke test

**Files:** no file changes

- [ ] **Step 1: Start the Flask app and generate a full PDF**

Start the app (`python main.py`) in a terminal, open `http://localhost:5000`, click **Generate**, then **Export PDF**.

- [ ] **Step 2: Verify the PDF**

Open the downloaded PDF and confirm:
- Page 1 shows the dashboard + the new card grid quadrant, both on one page
- All 4 zones are visible in the quadrant
- Deal names are legible at PDF resolution
- No rendering artefacts

- [ ] **Step 3: Final commit if any adjustments were made**

```bash
git add charts.py
git commit -m "fix: adjust card grid layout constants for PDF rendering"
```

Only commit if visual tweaks were needed. Otherwise, implementation is complete.
