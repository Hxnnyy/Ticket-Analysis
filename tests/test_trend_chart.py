import os
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Browser, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = 8510
URL = f"http://localhost:{PORT}"


def wait_for_server(url: str, timeout: float = 60.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url):
                return
        except Exception:
            time.sleep(0.5)
    raise TimeoutError(f"Server at {url} not ready after {timeout} seconds.")


@pytest.fixture(scope="session")
def streamlit_server():
    env = os.environ.copy()
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["STREAMLIT_SERVER_PORT"] = str(PORT)
    env["SUPABASE_DISABLE"] = "1"

    process = subprocess.Popen(
        [
            "python",
            "-m",
            "streamlit",
            "run",
            "dashboard.py",
            f"--server.port={PORT}",
            "--server.headless=true",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    wait_for_server(URL)
    yield
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture(scope="session")
def browser(streamlit_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture()
def page(browser: Browser):
    page = browser.new_page()
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector("text=Trend chart")
    yield page
    page.close()


CHART_SELECTOR = '[data-testid="stVegaLiteChart"]'
EXPECTED_SELECTOR = {
    "Line": "svg .mark-line path",
    "Bar": "svg .mark-rect path",
    "Area": "svg .mark-area path",
}


def get_mark_counts(page) -> dict[str, int]:
    return page.locator(CHART_SELECTOR).last.evaluate(
        """(node) => ({
            line: node.querySelectorAll('svg .mark-line path').length,
            rect: node.querySelectorAll('svg .mark-rect path').length,
            area: node.querySelectorAll('svg .mark-area path').length
        })"""
    )


@pytest.mark.parametrize("choice", ["Line", "Bar", "Area"])
def test_trend_chart_mark_switch(page, choice):
    group = page.locator('div[role="radiogroup"][aria-label="Trend chart"]')
    group.locator("label").filter(has_text=choice).click()

    page.wait_for_function(
        """([selector, expected]) => {
            const charts = document.querySelectorAll(selector);
            if (!charts.length) return false;
            const node = charts[charts.length - 1];
            return node.querySelectorAll(expected).length > 0;
        }""",
        arg=[CHART_SELECTOR, EXPECTED_SELECTOR[choice]],
    )

    counts = get_mark_counts(page)
    assert counts["line"] >= 0
    assert counts["rect"] >= 0
    assert counts["area"] >= 0
    expected_key = {"Line": "line", "Bar": "rect", "Area": "area"}[choice]
    assert (
        counts[expected_key] > 0
    ), f"Expected {choice} chart to have marks, got counts {counts}"
