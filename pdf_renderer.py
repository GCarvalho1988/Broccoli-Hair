"""
Renders an HTML string to A4 PDF bytes using Playwright (Chromium).
Uses the sync API — same as dashboard_capture.py.
"""
from playwright.sync_api import sync_playwright

_FOOTER = (
    '<div style="font-size:8px;color:#aaa;width:100%;'
    'text-align:center;font-family:Arial,sans-serif;">'
    'Page <span class="pageNumber"></span>'
    ' &nbsp;·&nbsp; Confidential — Sectra UK&amp;I</div>'
)


def render_pdf(html: str) -> bytes:
    """
    Render HTML to A4 PDF and return raw bytes.
    Raises on Playwright error — caller must handle.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle", timeout=15000)  # Google Fonts; 15s cap
            return page.pdf(
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template="<div></div>",
                footer_template=_FOOTER,
                margin={
                    "top":    "12mm",
                    "bottom": "16mm",
                    "left":   "14mm",
                    "right":  "14mm",
                },
            )
        finally:
            browser.close()
