"""
Generates the Strategic Fit vs Revenue quadrant chart as a 2x2 card grid.
Returns a base64-encoded PNG string for embedding in HTML:
  <img src="data:image/png;base64,{{ quadrant_b64 }}">
"""
import io, base64, textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from config import STAGE_COLOURS

# ── Layout constants ──────────────────────────────────────────────────────────
# Invariant: _MAX_ROWS * _ROW_HEIGHT <= _Y_START (overflow label stays in axes)
_CHIPS_PER_ROW = 2
_X_START       = 0.04   # left margin (axes fraction)
_Y_START       = 0.80   # top of chip area, below zone header
_COL_WIDTH     = 0.48   # horizontal step between chip columns
_ROW_HEIGHT    = 0.16   # vertical step between chip rows (tall enough for 2-line chips)
_MAX_ROWS      = 5      # floor(0.80 / 0.16) = 5 rows visible
_WRAP_CHARS    = 20     # wrap deal names at this many characters per line


def _font_size(n: int) -> float:
    """Return chip font size (pt) based on number of deals in zone."""
    if n <= 9:
        return 8.5
    if n <= 15:
        return 7.5
    return 6.5


def _stage_int(stage: str) -> int:
    """Convert stage number string to int for sorting; unknown values → 0."""
    try:
        return int(stage)
    except (ValueError, TypeError):
        return 0


def _wrap(name: str) -> str:
    """Wrap a deal name to at most 2 lines; collapse any embedded newlines first."""
    name = name.replace("\n", " ").replace("\r", "").strip()
    lines = textwrap.wrap(name, width=_WRAP_CHARS)
    return "\n".join(lines[:2])  # max 2 lines


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

    # Assign each deal to a zone.
    # Note: Profitability is the Smartsheet field name; it maps to the "Revenue" axis label.
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
            ax.text(x, y, _wrap(d["Opportunity"]),
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

    # Axis labels on a transparent overlay.
    # bbox_inches="tight" on savefig handles figure cropping — no tight_layout needed.
    overlay = fig.add_axes([0, 0, 1, 1], frameon=False)
    overlay.set_xlim(0, 1)
    overlay.set_ylim(0, 1)
    overlay.tick_params(left=False, bottom=False,
                        labelleft=False, labelbottom=False)
    for spine in overlay.spines.values():
        spine.set_visible(False)
    overlay.text(0.5, 0.02, "Revenue \u2192",
                 transform=overlay.transAxes,
                 fontsize=13, fontweight="bold",
                 ha="center", va="bottom")
    overlay.text(0.02, 0.5, "Strategic Fit \u2192",
                 transform=overlay.transAxes,
                 fontsize=13, fontweight="bold",
                 ha="left", va="center", rotation=90)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")
