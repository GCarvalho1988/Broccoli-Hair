"""
Captures the Smartsheet Sales Pipeline Overview dashboard as PNG bytes
using a headless Chromium browser via Playwright.
"""
from playwright.sync_api import sync_playwright
from config import DASHBOARD_URL


def capture_dashboard(timeout_ms: int = 30000) -> bytes:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 800})
        page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=timeout_ms)
        # Wait for dashboard widgets to fully render after network is idle
        page.wait_for_timeout(10000)
        screenshot = page.screenshot(
            full_page=False,
            clip={"x": 0, "y": 50, "width": 1400, "height": 660}
        )
        browser.close()
    return screenshot
