# tests/test_history_html.py
from history import load_history, update_deal, save_history
import json, os, tempfile


def _make_old_history():
    """Simulates a history.json written by the old code."""
    return {
        "_meta": {"last_run_date": "2026-03-13"},
        "alpha deal": {
            "display_name": "Alpha Deal",
            "summary_lines": ["Pilot agreed", "Meeting next week"],
            "last_update_lines": ["Discussed pricing"],
            "last_discussed_date": "2026-03-13",
            "last_included_date": "2026-03-13",
        }
    }


def test_load_history_migrates_summary_lines(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_make_old_history()), encoding="utf-8")
    monkeypatch.setattr("history.HISTORY_FILE", str(path))

    h = load_history()
    entry = h["alpha deal"]

    assert "summary_html" in entry
    assert "<p>Pilot agreed</p>" in entry["summary_html"]
    assert "<p>Meeting next week</p>" in entry["summary_html"]
    assert "summary_lines" not in entry


def test_load_history_migrates_last_update_lines(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_make_old_history()), encoding="utf-8")
    monkeypatch.setattr("history.HISTORY_FILE", str(path))

    h = load_history()
    entry = h["alpha deal"]

    assert "last_update_html" in entry
    assert "<p>Discussed pricing</p>" in entry["last_update_html"]
    assert "last_update_lines" not in entry


def test_update_deal_stores_summary_html():
    h = {"_meta": {}}
    update_deal(h, "Beta Deal", summary_html="<p>New summary</p>", report_date="2026-03-20")
    assert h["beta deal"]["summary_html"] == "<p>New summary</p>"
    assert "summary_lines" not in h["beta deal"]


def test_update_deal_stores_update_html():
    h = {"_meta": {}}
    update_deal(h, "Beta Deal", update_html="<ul><li>Item</li></ul>", report_date="2026-03-20")
    assert h["beta deal"]["last_update_html"] == "<ul><li>Item</li></ul>"
    assert "last_update_lines" not in h["beta deal"]


def test_update_deal_does_not_overwrite_when_none():
    h = {"_meta": {}, "gamma deal": {"display_name": "Gamma", "summary_html": "<p>Old</p>"}}
    update_deal(h, "Gamma Deal", summary_html=None, report_date="2026-03-20")
    assert h["gamma deal"]["summary_html"] == "<p>Old</p>"
