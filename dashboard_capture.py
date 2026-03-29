"""
Captures the Smartsheet Sales Pipeline Overview dashboard as PNG bytes
using a headless Chromium browser via Playwright.
"""
from playwright.sync_api import sync_playwright
from config import DASHBOARD_URL


def capture_dashboard(timeout_ms: int = 60000) -> bytes:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 800})
        # "load" fires once the page and its assets are loaded.
        # "networkidle" is avoided because Smartsheet keeps persistent WebSocket/
        # polling connections open and never reaches true network idle.
        page.goto(DASHBOARD_URL, wait_until="load", timeout=timeout_ms)
        # Give dashboard widgets time to render after the page has loaded.
        page.wait_for_timeout(15000)
        screenshot = page.screenshot(
            full_page=False,
            clip={"x": 0, "y": 50, "width": 1400, "height": 660}
        )
        browser.close()
    return screenshot
