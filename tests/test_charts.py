# tests/test_charts.py
import pytest
from charts import generate_quadrant


def _deal(name, fit, profit, stage="3"):
    return {"Opportunity": name, "Strategic Fit": fit,
            "Profitability": profit, "Stage Number": stage}


def test_returns_nonempty_base64_png_for_valid_deals():
    deals = [_deal("Alpha", 7.0, 8.0, "5"), _deal("Beta", 3.0, 3.0, "2")]
    result = generate_quadrant(deals)
    assert isinstance(result, str)
    assert len(result) > 100  # non-trivial base64 PNG


def test_returns_empty_string_when_no_plottable_deals():
    deals = [{"Opportunity": "No scores", "Strategic Fit": None,
              "Profitability": None, "Stage Number": "3"}]
    result = generate_quadrant(deals)
    assert result == ""


def test_returns_empty_string_for_empty_input():
    assert generate_quadrant([]) == ""


def test_excludes_deals_missing_either_score():
    deals = [
        _deal("Has both", 7.0, 8.0),
        {"Opportunity": "Missing fit", "Strategic Fit": None,
         "Profitability": 7.0, "Stage Number": "3"},
        {"Opportunity": "Missing profit", "Strategic Fit": 7.0,
         "Profitability": None, "Stage Number": "3"},
    ]
    # Should produce a valid PNG (one deal plotted)
    result = generate_quadrant(deals)
    assert isinstance(result, str) and len(result) > 100


def test_boundary_score_5_goes_to_top_right():
    """Score of exactly 5.0 on both axes → Flagship Projects (top-right)."""
    deals = [_deal("Boundary", 5.0, 5.0, "4")]
    result = generate_quadrant(deals)
    assert result != ""  # renders without error


def test_stage_0_deal_renders_without_error():
    deals = [_deal("Early Stage", 6.0, 7.0, "0")]
    result = generate_quadrant(deals)
    assert result != ""


def test_many_deals_in_one_quadrant_renders_without_error():
    """15 deals all in Flagship Projects — triggers font reduction and possible truncation."""
    deals = [_deal(f"Deal {i}", 7.0 + (i % 3) * 0.1, 7.0 + (i % 3) * 0.1, str(i % 7))
             for i in range(15)]
    result = generate_quadrant(deals)
    assert isinstance(result, str) and len(result) > 100
