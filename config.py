import os
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise SystemExit(f"ERROR: {key} is not set. Add it to your .env file.")
    return val

SMARTSHEET_API_KEY = _require("SMARTSHEET_API_KEY")
ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY")
PIPELINE_SHEET_ID = 5464922490097540
MODEL = "claude-sonnet-4-6"

DASHBOARD_URL = "https://app.smartsheet.com/b/publish?EQBCT=13232135d0854d86b63655eca3dce19f"

# Sales stage colours (hex, for quadrant dots and report badges)
STAGE_COLOURS = {
    "0": "#888888",  # One to Watch — grey
    "1": "#E87722",  # Pre-Tender — orange
    "2": "#F5C400",  # Early Engagement — yellow
    "3": "#2E7D32",  # OBS — green
    "4": "#00838F",  # Demo/Site Visits — teal
    "5": "#1565C0",  # BAFO — blue
    "6": "#6A1B9A",  # Preferred Supplier — purple
}

NON_DEALS = {"demo kit", "conference diary", "click here"}
