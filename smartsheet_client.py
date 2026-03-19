import re

import smartsheet
from config import SMARTSHEET_API_KEY, PIPELINE_SHEET_ID, NON_DEALS

_client = smartsheet.Smartsheet(SMARTSHEET_API_KEY)
_client.errors_as_exceptions(True)


def fetch_pipeline_data() -> list[dict]:
    """
    Returns a list of dicts, one per active deal row.
    Filters out header rows, non-deal rows, and closed deals.
    """
    sheet = _client.Sheets.get_sheet(PIPELINE_SHEET_ID)
    headers = {col.id: col.title for col in sheet.columns}

    deals = []
    seen_names = set()
    for row in sheet.rows:
        row_data = {headers[c.column_id]: c.display_value or c.value
                    for c in row.cells if c.column_id in headers}

        name  = str(row_data.get("Opportunity") or "").strip()
        stage = str(row_data.get("Sales Stage") or "").strip()

        if not name or not stage:
            continue
        if name.lower() in NON_DEALS:
            continue
        if any(skip in name.lower() for skip in NON_DEALS):
            continue
        if "closed" in stage.lower():
            continue
        # Only include active pipeline stages 1–6
        stage_num = _stage_number(stage)
        if stage_num not in {"1", "2", "3", "4", "5", "6"}:
            continue
        # Deduplicate: keep first *valid* (stage 1–6) occurrence
        if name.lower() in seen_names:
            continue
        seen_names.add(name.lower())

        deals.append({
            "Opportunity":      name,
            "Sales Stage":      stage,
            "Forecast Amount":  row_data.get("Forecast Amount", ""),
            "Sales Rep":        row_data.get("Sales Rep", ""),
            "Next Step":        row_data.get("Next Step", ""),
            "Expected Close":   row_data.get("Expected Close Date", ""),
            "Strategic Fit":    _to_float(row_data.get("Strategic Fit")),
            "Profitability":    _to_float(row_data.get("Profitability")),
            "Stage Number":     stage_num,
        })
    return deals


def _to_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _stage_number(stage: str) -> str:
    """Extract the leading digit from a stage string like '6 - Preferred Supplier'."""
    m = re.match(r"(\d)", stage.strip())
    return m.group(1) if m else "0"
