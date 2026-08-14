"""Playwright fixtures for signals-ui browser tests."""

from __future__ import annotations

import os

import pytest
import requests

from signals.browser import default_ui_base, launch_chromium, sync_playwright


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "browser: headless Playwright tests against a live signals-ui",
    )


def _ui_reachable(base: str) -> bool:
    try:
        r = requests.get(f"{base}/healthz", timeout=2)
        return r.status_code == 200
    except requests.RequestException:
        return False


@pytest.fixture(scope="session")
def ui_base() -> str:
    return default_ui_base()


@pytest.fixture(scope="session")
def require_ui(ui_base: str):
    if os.environ.get("SIGNALS_UI_BROWSER_SKIP") == "1":
        pytest.skip("SIGNALS_UI_BROWSER_SKIP=1")
    if not _ui_reachable(ui_base):
        pytest.skip(
            f"signals-ui not reachable at {ui_base} "
            "(start engine + UI, or set SIGNALS_UI_BASE)"
        )


@pytest.fixture(scope="session")
def browser(require_ui):
    with sync_playwright() as p:
        b = launch_chromium(p)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(
        viewport={"width": 1400, "height": 900},
        ignore_https_errors=True,
    )
    p = ctx.new_page()
    yield p
    ctx.close()
