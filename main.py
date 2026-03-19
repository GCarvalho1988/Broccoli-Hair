import os, base64
from datetime import date
from flask import Flask, render_template, request, jsonify, session

from config import STAGE_COLOURS
from smartsheet_client import fetch_pipeline_data
from dashboard_capture import capture_dashboard
from charts import generate_quadrant
from pdf_reader import extract_portfolio_text
from ai_writer import draft_report_content, generate_high_level_summary
from history import (load_history, save_history, update_deal,
                     set_last_run_date, should_include)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "broccoli-hair-dev")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _report_date_str() -> str:
    if os.name != "nt":
        return date.today().strftime("%-d %B %Y")
    return date.today().strftime("%d %B %Y").lstrip("0")


def _enrich_stage(items: list[dict], deal_stage_map: dict) -> None:
    """Add stage and stage_num to each item in-place."""
    for item in items:
        d = deal_stage_map.get(item["deal"].lower(), {})
        item["stage"]     = d.get("Sales Stage", "")
        item["stage_num"] = d.get("Stage Number", "0")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    transcript = request.form.get("transcript", "").strip()
    if not transcript:
        return "Please paste the meeting transcript.", 400

    # Store for Regenerate
    session["transcript"]     = transcript
    session["portfolio_text"] = ""

    portfolio_text = ""
    pdf_file = request.files.get("portfolio_pdf")
    if pdf_file and pdf_file.filename:
        path = os.path.join(UPLOAD_FOLDER, "portfolio.pdf")
        pdf_file.save(path)
        portfolio_text = extract_portfolio_text(path)
        session["portfolio_text"] = portfolio_text

    # Dashboard screenshot
    dashboard_b64 = None
    try:
        png = capture_dashboard()
        dashboard_b64 = base64.b64encode(png).decode("utf-8")
    except Exception as e:
        print(f"Dashboard capture failed: {e}")

    # Pipeline data + chart
    deals = fetch_pipeline_data()
    quadrant_b64 = generate_quadrant(deals)

    # History + AI
    history = load_history()
    ai = draft_report_content(deals, transcript, portfolio_text, history)

    # Pass ALL active deals — use inclusion logic only to pre-set excluded flag.
    # User can override via checkbox in the report.
    deal_stage_map = {d["Opportunity"].lower(): d for d in deals}
    all_updates = ai.get("deal_updates", [])
    _enrich_stage(all_updates, deal_stage_map)
    for item in all_updates:
        mentioned = item.get("mentioned", False)
        item["excluded"] = not should_include(item["deal"], history, discussed=mentioned)

    return render_template("report.html",
        report_date=_report_date_str(),
        dashboard_b64=dashboard_b64,
        quadrant_b64=quadrant_b64,
        deal_updates=all_updates,
        upsell_items=ai.get("upsell_items", []),
        stage_colours=STAGE_COLOURS,
    )


@app.route("/regenerate", methods=["POST"])
def regenerate():
    """
    Re-run AI with corrected content from the client.
    Returns refreshed deal_updates, a freshly generated high_level_summary, and upsell_items.
    """
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400

    transcript     = session.get("transcript", "")
    portfolio_text = session.get("portfolio_text", "")

    # Seed a temporary history from the client's current corrections
    temp_history = {"_meta": {"last_run_date": None}}
    for item in data.get("deals", []):
        update_deal(temp_history, item["deal"],
                    summary_lines=item.get("summary_lines", []),
                    update_lines=item.get("update_lines", []),
                    discussed=item.get("mentioned", False))

    deals = fetch_pipeline_data()
    ai    = draft_report_content(deals, transcript, portfolio_text, temp_history)

    deal_stage_map = {d["Opportunity"].lower(): d for d in deals}
    all_updates = ai.get("deal_updates", [])
    _enrich_stage(all_updates, deal_stage_map)

    # Carry forward excluded flags from client
    client_excluded = {it["deal"].lower(): it.get("excluded", False)
                       for it in data.get("deals", [])}
    for item in all_updates:
        item["excluded"] = client_excluded.get(item["deal"].lower(), False)

    # Generate High Level Summary from non-excluded deals' summaries only
    non_excluded = {it["deal"].lower() for it in all_updates if not it.get("excluded", False)}
    summary_inputs = [
        {
            "deal":         item["deal"],
            "stage":        item.get("stage", ""),
            "stage_num":    item.get("stage_num", "0"),
            "summary_lines": item.get("summary_lines", []),
            "forecast":     deal_stage_map.get(item["deal"].lower(), {}).get("Forecast Amount", ""),
        }
        for item in all_updates
        if item["deal"].lower() in non_excluded
    ]
    high_level_summary = generate_high_level_summary(summary_inputs)
    _enrich_stage(high_level_summary, deal_stage_map)

    return jsonify({
        "ok":                True,
        "deal_updates":      all_updates,
        "high_level_summary": high_level_summary,
        "upsell_items":      ai.get("upsell_items", []),
    })


@app.route("/save", methods=["POST"])
def save():
    """
    Receives JSON: { deals: [{deal, summary_lines, update_lines, mentioned, excluded}], run_date }
    Saves non-excluded deals to history.json.
    """
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400

    history = load_history()
    today   = data.get("run_date", date.today().isoformat())

    for item in data.get("deals", []):
        if item.get("excluded", False):
            continue  # excluded deals are not persisted
        update_deal(history, item["deal"],
                    summary_lines=item.get("summary_lines"),
                    update_lines=item.get("update_lines"),
                    discussed=item.get("mentioned", False),
                    report_date=today)

    set_last_run_date(history, today)
    save_history(history)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=5000)
