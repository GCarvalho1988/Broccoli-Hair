# tests/test_ai_writer_helpers.py
from ai_writer import _html_to_text, _lines_to_html


def test_html_to_text_strips_tags():
    assert _html_to_text("<p>Hello</p>") == "Hello"


def test_html_to_text_preserves_block_boundaries():
    result = _html_to_text("<p>Line 1</p><p>Line 2</p>")
    assert "Line 1" in result and "Line 2" in result
    assert result.index("Line 1") < result.index("Line 2")


def test_html_to_text_handles_none():
    assert _html_to_text(None) == ""


def test_html_to_text_handles_empty():
    assert _html_to_text("") == ""


def test_html_to_text_handles_quill_empty_paragraph():
    # Quill emits <p><br></p> for empty paragraphs
    result = _html_to_text("<p><br></p>")
    assert result.strip() == ""


def test_html_to_text_handles_list():
    result = _html_to_text("<ul><li>Item A</li><li>Item B</li></ul>")
    assert "Item A" in result and "Item B" in result


def test_lines_to_html_wraps_in_paragraphs():
    assert _lines_to_html(["Hello", "World"]) == "<p>Hello</p><p>World</p>"


def test_lines_to_html_skips_blank_lines():
    assert _lines_to_html(["", "Hello", ""]) == "<p>Hello</p>"


def test_lines_to_html_empty_list():
    assert _lines_to_html([]) == ""
