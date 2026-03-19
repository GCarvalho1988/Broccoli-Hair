import os, io, base64, json
from datetime import date
from flask import Flask, render_template, request, jsonify

from config import STAGE_COLOURS
from smartsheet_client import fetch_pipeline_data
from dashboard_capture import capture_dashboard
from charts import generate_quadrant
from pdf_reader import extract_portfolio_text
from ai_writer import draft_report_content
from history import (load_history, save_history, update_deal,
                     set_last_run_date, should_include)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    transcript = request.form.get("transcript", "").strip()
    if not transcript:
        return "Please paste the meeting transcript.", 400

    portfolio_text = ""
    pdf_file = request.files.get("portfolio_pdf")
    if pdf_file and pdf_file.filename:
        path = os.path.join(UPLOAD_FOLDER, "portfolio.pdf")
        pdf_file.save(path)
        portfolio_text = extract_portfolio_text(path)

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

    # Apply inclusion logic — filter deal_updates to only those that should appear
    today = date.today().isoformat()
    filtered_updates = []
    for item in ai["deal_updates"]:
        mentioned = item.get("mentioned", False)
        if should_include(item["deal"], history, discussed=mentioned):
            filtered_updates.append(item)

    # Enrich with stage info for template
    deal_stage_map = {d["Opportunity"].lower(): d for d in deals}
    for item in filtered_updates:
        d = deal_stage_map.get(item["deal"].lower(), {})
        item["stage"]     = d.get("Sales Stage", "")
        item["stage_num"] = d.get("Stage Number", "0")

    for item in ai.get("high_level_summary", []):
        d = deal_stage_map.get(item["deal"].lower(), {})
        item["stage"]     = d.get("Sales Stage", "")
        item["stage_num"] = d.get("Stage Number", "0")

    report_date = date.today().strftime("%-d %B %Y") if os.name != "nt" else date.today().strftime("%d %B %Y").lstrip("0")

    return render_template("report.html",
        report_date=report_date,
        dashboard_b64=dashboard_b64,
        quadrant_b64=quadrant_b64,
        high_level_summary=ai.get("high_level_summary", []),
        deal_updates=filtered_updates,
        upsell_items=ai.get("upsell_items", []),
        stage_colours=STAGE_COLOURS,
    )


@app.route("/save", methods=["POST"])
def save():
    """
    Receives JSON: { deals: [{deal, summary_lines, update_lines}], run_date }
    Saves to history.json.
    """
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400

    history = load_history()
    today = data.get("run_date", date.today().isoformat())

    for item in data.get("deals", []):
        update_deal(history, item["deal"],
                    summary_lines=item.get("summary_lines"),
                    update_lines=item.get("update_lines"),
                    discussed=item.get("mentioned", False),
                    report_date=today)

    set_last_run_date(history, today)
    save_history(history)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
