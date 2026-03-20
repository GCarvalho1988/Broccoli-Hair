# tests/test_main_helpers.py
# Tests for module-level helpers that will be added to main.py.
# Import them from main to confirm they exist and work.

def test_html_is_empty_with_quill_empty_paragraph():
    from main import _html_is_empty
    assert _html_is_empty("<p><br></p>") is True


def test_html_is_empty_with_real_content():
    from main import _html_is_empty
    assert _html_is_empty("<p>Hello</p>") is False


def test_html_is_empty_with_none():
    from main import _html_is_empty
    assert _html_is_empty(None) is True


def test_html_is_empty_with_empty_string():
    from main import _html_is_empty
    assert _html_is_empty("") is True


def test_html_is_empty_with_whitespace_only():
    from main import _html_is_empty
    assert _html_is_empty("<p>   </p>") is True
