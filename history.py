"""
Manages reports/history.json.

Per-deal structure:
{
  "display_name": "North Central London (Radiology)",
  "summary_lines": ["line1", ...],
  "last_update_lines": ["line1", ...],
  "last_discussed_date": "2026-03-13",
  "last_included_date": "2026-03-13"
}

Top-level _meta.last_run_date = date of the previous report run.
"""
import json, os, re
from datetime import date

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "reports", "history.json")


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"_meta": {"last_run_date": None}}


def save_history(history: dict) -> None:
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def get_deal(name: str, history: dict) -> dict | None:
    """Return the history entry for a deal, or None. Uses fuzzy match."""
    k = _key(name)
    if k in history:
        return history[k]
    return _fuzzy_get(k, history)


def _fuzzy_get(k: str, history: dict) -> dict | None:
    if len(k) >= 4:
        for key in history:
            if key == "_meta":
                continue
            if re.search(r"\b" + re.escape(k) + r"\b", key):
                return history[key]
    words = [w for w in re.split(r"\W+", k) if len(w) > 3]
    best_key, best_score = None, 0
    for key in history:
        if key == "_meta":
            continue
        score = sum(1 for w in words if w in key)
        if score > best_score:
            best_key, best_score = key, score
    if best_score >= 2:
        return history[best_key]
    return None


def should_include(name: str, history: dict, discussed: bool) -> bool:
    """
    Return True if this deal should appear in the Detailed Updates section.
    Rules:
      - Discussed this week → always include
      - Not discussed, but last_included_date == last_run_date → include ("No update.")
      - Otherwise → exclude
    """
    if discussed:
        return True
    last_run = history.get("_meta", {}).get("last_run_date")
    if not last_run:
        return False
    entry = get_deal(name, history)
    if not entry:
        return False
    return entry.get("last_included_date") == last_run


def update_deal(history: dict, name: str, *,
                summary_lines=None, update_lines=None,
                discussed: bool = False,
                report_date: str = None) -> None:
    """Write back a deal's data after a report run."""
    k = _key(name)
    today = report_date or date.today().isoformat()
    if k not in history:
        history[k] = {"display_name": name.strip()}
    entry = history[k]
    entry["display_name"] = name.strip()
    if summary_lines is not None:
        entry["summary_lines"] = summary_lines
    if update_lines is not None:
        entry["last_update_lines"] = update_lines
    entry["last_included_date"] = today
    if discussed:
        entry["last_discussed_date"] = today


def set_last_run_date(history: dict, d: str) -> None:
    history.setdefault("_meta", {})["last_run_date"] = d
