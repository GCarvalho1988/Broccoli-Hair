"""
Generates the Strategic Fit vs Profitability quadrant chart.
Returns a base64-encoded PNG string for embedding in HTML:
  <img src="data:image/png;base64,{{ quadrant_b64 }}">
"""
import io, base64, math, random
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from config import STAGE_COLOURS


def generate_quadrant(deals: list[dict]) -> str:
    """Return base64 PNG string of the quadrant chart."""
    plottable = [d for d in deals
                 if d.get("Strategic Fit") is not None
                 and d.get("Profitability") is not None]

    points = [{"x": d["Profitability"],
               "y": d["Strategic Fit"],
               "label": d["Opportunity"],
               "colour": STAGE_COLOURS.get(d.get("Stage Number", "0"), "#888888")}
              for d in plottable]

    points = _spread_points(points, min_dist=0.6, iterations=120)

    plt.rcParams.update(plt.rcParamsDefault)
    fig, ax = plt.subplots(figsize=(12, 10))

    # Quadrant background shading
    ax.axhspan(5, 10, xmin=0.5, xmax=1.0, alpha=0.06, color="green")
    ax.axhspan(0,  5, xmin=0.0, xmax=0.5, alpha=0.06, color="red")

    # Quadrant dividers
    ax.axhline(5, color="#cccccc", linewidth=1, linestyle="--")
    ax.axvline(5, color="#cccccc", linewidth=1, linestyle="--")

    label_positions = _place_labels(points)

    for pt in points:
        ax.scatter(pt["x"], pt["y"], s=1400, color=pt["colour"],
                   alpha=0.85, zorder=3, edgecolors="white", linewidths=2)

    for pt, (lx, ly) in zip(points, label_positions):
        ax.annotate(pt["label"], (pt["x"], pt["y"]),
                    xytext=(lx, ly),
                    textcoords="data",
                    arrowprops=dict(arrowstyle="-", color="#aaaaaa",
                                    lw=0.8, alpha=0.7),
                    fontsize=10, fontweight="bold",
                    ha="center", va="center",
                    bbox=dict(boxstyle="round,pad=0.35",
                              fc="white", ec=pt["colour"],
                              alpha=0.95, linewidth=1.4))

    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.set_xlabel("Revenue →", fontsize=13, fontweight="bold")
    ax.set_ylabel("Strategic Fit →", fontsize=13, fontweight="bold")
    ax.tick_params(labelbottom=False, labelleft=False, length=0)

    # Remove all border spines
    for spine in ax.spines.values():
        spine.set_visible(False)

    quadrant_labels = [
        ("Flagship\nProjects",  7.5, 7.5, "#2E7D32"),
        ("Strategy\nPlays",     2.5, 7.5, "#1565C0"),
        ("Core\nRevenue",       7.5, 2.5, "#00838F"),
        ("Questionable",        2.5, 2.5, "#888888"),
    ]
    for txt, x, y, col in quadrant_labels:
        ax.text(x, y, txt, fontsize=13, color=col, alpha=0.30,
                ha="center", va="center", fontweight="bold",
                linespacing=1.4)

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
        for pt in pts:
            pt["x"] = max(0.3, min(9.7, pt["x"]))
            pt["y"] = max(0.3, min(9.7, pt["y"]))
        if not moved:
            break
    return pts


def _place_labels(points: list[dict]) -> list[tuple[float, float]]:
    """
    Compute non-overlapping label positions in data coordinates.
    Uses bounding-box repulsion between labels AND between labels and dots.
    Returns list of (x, y) parallel to points.
    """
    # Start labels well clear of their dot — direction based on quadrant
    positions = [
        [pt["x"] + (1.8 if pt["x"] >= 5 else -1.8),
         pt["y"] + (1.2 if pt["y"] >= 5 else -1.2)]
        for pt in points
    ]

    # Half-sizes (data coords): label width ~1.2, height ~0.3; dot effective radius ~0.3
    lw, lh, dot_r = 1.2, 0.30, 0.30

    for _ in range(500):
        moved = False

        # ── Label–label repulsion ─────────────────────────────────────────────
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                dx = positions[i][0] - positions[j][0]
                dy = positions[i][1] - positions[j][1]
                ox = lw * 2 - abs(dx)
                oy = lh * 2 - abs(dy)
                if ox > 0 and oy > 0:
                    if ox < oy:
                        push = ox * 0.5 * (1 if dx >= 0 else -1)
                        positions[i][0] += push
                        positions[j][0] -= push
                    else:
                        push = oy * 0.5 * (1 if dy >= 0 else -1)
                        positions[i][1] += push
                        positions[j][1] -= push
                    moved = True

        # ── Label–dot repulsion (keep every label clear of every dot) ─────────
        for i, pos in enumerate(positions):
            for pt in points:
                dx = pos[0] - pt["x"]
                dy = pos[1] - pt["y"]
                ox = (lw + dot_r) - abs(dx)
                oy = (lh + dot_r) - abs(dy)
                if ox > 0 and oy > 0:
                    if ox < oy:
                        pos[0] += ox * (1 if dx >= 0 else -1)
                    else:
                        pos[1] += oy * (1 if dy >= 0 else -1)
                    moved = True

        for pos in positions:
            pos[0] = max(0.1, min(9.9, pos[0]))
            pos[1] = max(0.1, min(9.9, pos[1]))
        if not moved:
            break

    return [(pos[0], pos[1]) for pos in positions]
