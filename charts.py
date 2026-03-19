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
    ax.set_xlabel("Profitability →", fontsize=13, fontweight="bold")
    ax.set_ylabel("Strategic Fit →", fontsize=13, fontweight="bold")
    ax.set_title("Deal Quadrant Analysis", fontsize=16, fontweight="bold", pad=15)
    ax.tick_params(labelsize=10)

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
    Compute non-overlapping label positions in data coordinates using
    bounding-box repulsion. Returns list of (x, y) parallel to points.
    """
    # Initial placement: offset from dot based on which quadrant the dot is in
    positions = [
        [pt["x"] + (0.8 if pt["x"] >= 5 else -0.8),
         pt["y"] + (0.55 if pt["y"] >= 5 else -0.55)]
        for pt in points
    ]

    # Approximate label half-sizes in data coordinates
    lw, lh = 1.4, 0.42

    for _ in range(400):
        moved = False
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                dx = positions[i][0] - positions[j][0]
                dy = positions[i][1] - positions[j][1]
                overlap_x = lw * 2 - abs(dx)
                overlap_y = lh * 2 - abs(dy)
                if overlap_x > 0 and overlap_y > 0:
                    # Push along the axis with the smaller overlap
                    if overlap_x < overlap_y:
                        push = overlap_x * 0.5 * (1 if dx >= 0 else -1)
                        positions[i][0] += push
                        positions[j][0] -= push
                    else:
                        push = overlap_y * 0.5 * (1 if dy >= 0 else -1)
                        positions[i][1] += push
                        positions[j][1] -= push
                    moved = True
        for pos in positions:
            pos[0] = max(0.1, min(9.9, pos[0]))
            pos[1] = max(0.1, min(9.9, pos[1]))
        if not moved:
            break

    return [(pos[0], pos[1]) for pos in positions]
