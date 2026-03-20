import os, base64, io
from datetime import date
from flask import Flask, render_template, request, jsonify, session
from PIL import Image

from config import STAGE_COLOURS
from smartsheet_client import fetch_pipeline_data
from dashboard_capture import capture_dashboard
from charts import generate_quadrant
from pdf_renderer import render_pdf
from pdf_reader import extract_portfolio_text
from ai_writer import (draft_updates_from_transcript, extract_upsell_items,
                        update_summaries_from_updates, generate_high_level_summary)
from history import (load_history, save_history, update_deal,
                     set_last_run_date, should_include, get_deal)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "broccoli-hair-dev")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _resize_b64_image(b64: str, max_width: int, max_height: int) -> str:
    """Resize a base64 PNG so it fits within max_width x max_height, preserving aspect ratio."""
    data = base64.b64decode(b64)
    img = Image.open(io.BytesIO(data))
    img.thumbnail((max_width, max_height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _report_date_str() -> str:
    if os.name != "nt":
        return date.today().strftime("%-d %B %Y")
    return date.today().strftime("%d %B %Y").lstrip("0")


def _fy_week(d: date = None) -> int:
    """Financial year week number (FY starts 1 May)."""
    if d is None:
        d = date.today()
    fy_start_year = d.year if d.month >= 5 else d.year - 1
    return (d - date(fy_start_year, 5, 1)).days // 7 + 1


def _enrich_stage(items: list[dict], deal_stage_map: dict) -> None:
    """Add stage, stage_num, forecast, and rep to each item in-place."""
    for item in items:
        d = deal_stage_map.get(item["deal"].lower(), {})
        item["stage"]     = d.get("Sales Stage", "")
        item["stage_num"] = d.get("Stage Number", "0")
        item["forecast"]  = d.get("Forecast Amount", "")
        item["rep"]       = d.get("Sales Rep", "")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    transcript = request.form.get("transcript", "").strip()

    # Store transcript for reference (kept for session but no longer drives regenerate)
    session["transcript"] = transcript

    # ── Portfolio PDF → upsell items ─────────────────────────────────────────
    portfolio_text = ""
    upsell_items   = []
    pdf_file = request.files.get("portfolio_pdf")
    if pdf_file and pdf_file.filename:
        path = os.path.join(UPLOAD_FOLDER, "portfolio.pdf")
        pdf_file.save(path)
        portfolio_text = extract_portfolio_text(path)
    if portfolio_text:
        upsell_items = extract_upsell_items(portfolio_text)

    # ── Dashboard screenshot ──────────────────────────────────────────────────
    dashboard_b64 = None
    try:
        png = capture_dashboard()
        dashboard_b64 = base64.b64encode(png).decode("utf-8")
        # Persist for /pdf route (single-user app — last generate wins)
        with open(os.path.join(UPLOAD_FOLDER, "last_dashboard.b64"), "w") as fh:
            fh.write(dashboard_b64)
    except Exception as e:
        print(f"Dashboard capture failed: {e}")

    # ── Pipeline data + chart ─────────────────────────────────────────────────
    deals = fetch_pipeline_data()
    quadrant_b64 = generate_quadrant(deals)

    # ── Deal updates: transcript path vs. no-transcript path ─────────────────
    history        = load_history()
    deal_stage_map = {d["Opportunity"].lower(): d for d in deals}

    if transcript:
        ai          = draft_updates_from_transcript(deals, transcript, history)
        all_updates = ai.get("deal_updates", [])
        _enrich_stage(all_updates, deal_stage_map)
        for item in all_updates:
            mentioned       = item.get("mentioned", False)
            item["excluded"] = not should_include(item["deal"], history, discussed=mentioned)
    else:
        all_updates = []
        for d in deals:
            entry = get_deal(d["Opportunity"], history)
            all_updates.append({
                "deal":           d["Opportunity"],
                "mentioned":      False,
                "update_lines":   [],
                "summary_action": "unchanged",
                "summary_lines":  entry.get("summary_lines", []) if entry else [],
                "excluded":       False,
            })
        _enrich_stage(all_updates, deal_stage_map)

    # Excluded deals sink to bottom; within each group preserve Smartsheet order
    all_updates.sort(key=lambda x: 1 if x.get("excluded") else 0)

    return render_template("report.html",
        report_date=_report_date_str(),
        fy_week=_fy_week(),
        dashboard_b64=dashboard_b64,
        quadrant_b64=quadrant_b64,
        deal_updates=all_updates,
        upsell_items=upsell_items,
        stage_colours=STAGE_COLOURS,
    )


@app.route("/pdf", methods=["POST"])
def generate_pdf():
    """
    Finalise: AI-update summaries → save history → render PDF → download.
    Accepts JSON: { deals, upsell_items, report_date, fy_week }
    """
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400

    client_deals = data.get("deals", [])
    upsell_items = data.get("upsell_items", [])
    report_date  = data.get("report_date", _report_date_str())
    fy_week      = data.get("fy_week", _fy_week())

    # Auto-exclude deals with no real update (blank = omission, not intentional include)
    for item in client_deals:
        if not item.get("excluded", False):
            lines = item.get("update_lines", [])
            if not any(l.strip() and l.strip() != "No update." for l in lines):
                item["excluded"] = True

    # ── 1. Enrich with stage data from Smartsheet ─────────────────────────────
    try:
        deals_from_sheet = fetch_pipeline_data()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Smartsheet fetch failed: {e}"}), 500

    deal_stage_map = {d["Opportunity"].lower(): d for d in deals_from_sheet}
    _enrich_stage(client_deals, deal_stage_map)

    # ── 2. AI: merge update text into summaries (only edited, non-excluded deals) ──
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
    if deals_needing_update:
        try:
            updated_summaries = update_summaries_from_updates(deals_needing_update)
            for item in client_deals:
                if item["deal"] in updated_summaries:
                    item["summary_lines"] = updated_summaries[item["deal"]]
        except Exception as e:
            print(f"Summary update AI call failed: {e}")
            return jsonify({"ok": False, "error": f"Summary update failed: {e}"}), 500

    # ── 3. Save history ───────────────────────────────────────────────────────
    history = load_history()
    today   = data.get("run_date", date.today().isoformat())
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
    set_last_run_date(history, today)
    save_history(history)

    # ── 4. Charts and images ──────────────────────────────────────────────────
    dashboard_b64 = None
    b64_path = os.path.join(UPLOAD_FOLDER, "last_dashboard.b64")
    if os.path.exists(b64_path):
        with open(b64_path) as fh:
            dashboard_b64 = fh.read().strip() or None

    try:
        quadrant_b64 = generate_quadrant(deals_from_sheet)
    except Exception as e:
        print(f"Quadrant generation failed: {e}")
        quadrant_b64 = None

    # Resize images to fixed pixel dimensions so Playwright renders them correctly
    # Dashboard: 1400px wide max (full width); Quadrant: 900x750px max (70% width slot)
    if dashboard_b64:
        try:
            dashboard_b64 = _resize_b64_image(dashboard_b64, 1400, 600)
        except Exception as e:
            print(f"Dashboard resize failed: {e}")
    if quadrant_b64:
        try:
            quadrant_b64 = _resize_b64_image(quadrant_b64, 900, 900)
        except Exception as e:
            print(f"Quadrant resize failed: {e}")

    # ── 5. High-level summary ─────────────────────────────────────────────────
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
    try:
        high_level_summary = generate_high_level_summary(non_excluded)
    except Exception as e:
        print(f"High-level summary failed: {e}")
        high_level_summary = []

    # ── 6. Render PDF ─────────────────────────────────────────────────────────
    html = render_template(
        "pdf.html",
        deal_updates=client_deals,
        upsell_items=upsell_items,
        high_level_summary=high_level_summary,
        dashboard_b64=dashboard_b64,
        quadrant_b64=quadrant_b64,
        report_date=report_date,
        fy_week=fy_week,
        stage_colours=STAGE_COLOURS,
    )

    try:
        pdf_bytes = render_pdf(html)
    except Exception as e:
        print(f"PDF render failed: {e}")
        return jsonify({"ok": False, "error": f"PDF generation failed: {e}"}), 500

    filename = f"SM_Weekly_Report_Week_{fy_week}.pdf"
    from flask import Response as FlaskResponse
    return FlaskResponse(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/history-editor")
def history_editor():
    history = load_history()
    deals = []
    for key, val in history.items():
        if key == "_meta":
            continue
        deals.append({
            "key":                key,
            "display_name":       val.get("display_name", key),
            "summary_lines":      val.get("summary_lines") or [],
            "last_update_lines":  val.get("last_update_lines") or [],
            "last_discussed_date": val.get("last_discussed_date", ""),
            "last_included_date":  val.get("last_included_date", ""),
        })
    deals.sort(key=lambda d: d["display_name"].lower())
    return render_template("history.html", deals=deals,
                           last_run=history.get("_meta", {}).get("last_run_date", ""))


@app.route("/history-editor/save", methods=["POST"])
def history_editor_save():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400
    history = load_history()
    for item in data.get("deals", []):
        key = item.get("key")
        if not key or key not in history:
            continue
        if item.get("deleted"):
            del history[key]
            continue
        entry = history[key]
        entry["display_name"]      = item.get("display_name", entry.get("display_name", ""))
        entry["summary_lines"]     = [l for l in item.get("summary_lines", []) if l.strip()]
        entry["last_update_lines"] = [l for l in item.get("last_update_lines", []) if l.strip()]
    save_history(history)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=5000)
