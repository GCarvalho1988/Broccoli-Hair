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

    with plt.xkcd():
        fig, ax = plt.subplots(figsize=(12, 10))

        ax.axhspan(5, 10, xmin=0.5, xmax=1.0, alpha=0.06, color="green")
        ax.axhspan(0,  5, xmin=0.0, xmax=0.5, alpha=0.06, color="red")
        ax.axhline(5, color="#cccccc", linewidth=1, linestyle="--")
        ax.axvline(5, color="#cccccc", linewidth=1, linestyle="--")

        for pt in points:
            ax.scatter(pt["x"], pt["y"], s=900, color=pt["colour"],
                       alpha=0.85, zorder=3, edgecolors="white", linewidths=1.5)
            ax.annotate(pt["label"], (pt["x"], pt["y"]),
                        textcoords="offset points",
                        xytext=_label_offset(pt["x"], pt["y"]),
                        fontsize=9, fontweight="bold",
                        ha="center", va="center",
                        bbox=dict(boxstyle="round,pad=0.3",
                                  fc="white", ec=pt["colour"],
                                  alpha=0.9, linewidth=1.2))

        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.set_xlabel("Profitability →", fontsize=13, fontweight="bold")
        ax.set_ylabel("Strategic Fit →", fontsize=13, fontweight="bold")
        ax.set_title("Deal Quadrant Analysis", fontsize=16, fontweight="bold", pad=15)
        ax.tick_params(labelsize=10)

        for txt, x, y in [("High Fit\nHigh Profit", 7.5, 7.5),
                           ("High Fit\nLow Profit",  2.5, 7.5),
                           ("Low Fit\nHigh Profit",  7.5, 2.5),
                           ("Low Fit\nLow Profit",   2.5, 2.5)]:
            ax.text(x, y, txt, fontsize=9, color="#aaaaaa",
                    ha="center", va="center", style="italic")

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


def _label_offset(x: float, y: float) -> tuple[int, int]:
    """Offset label away from the centre of the chart."""
    ox = 18 if x >= 5 else -18
    oy = 18 if y >= 5 else -18
    return (ox, oy)
