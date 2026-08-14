"""Headless browser launcher for signals-ui verification.

Uses Playwright. Prefers a system / devenv Chromium on PATH
(``chromium``, ``chromium-browser``, or ``SIGNALS_CHROMIUM_PATH``) so nix/devenv
does not need a second browser download. Falls back to Playwright's bundled
Chromium when no system binary is found (after ``just browser-install``).

Under devenv/nix, Playwright's shipped Node often fails with GLIBC/libstdc++
mismatches when ``LD_LIBRARY_PATH`` points at a newer nix ``libstdc++``. This
module:

1. Prefers ``PLAYWRIGHT_NODEJS_PATH`` or a Node on PATH (devenv ``nodejs_22``)
2. Clears ``LD_LIBRARY_PATH`` / ``LD_PRELOAD`` for the Playwright driver child
   unless ``SIGNALS_BROWSER_KEEP_LD_PATH=1``

Example::

    from signals.browser import launch_chromium, sync_playwright

    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page()
        page.goto("http://127.0.0.1:9889/queues")
        ...
        browser.close()
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

__all__ = [
    "chromium_executable",
    "launch_chromium",
    "sync_playwright",
    "default_ui_base",
    "prepare_playwright_env",
]


def default_ui_base() -> str:
    """Base URL for signals-ui (no trailing slash)."""
    return os.environ.get("SIGNALS_UI_BASE", "http://127.0.0.1:9889").rstrip("/")


def prepare_playwright_env() -> None:
    """Mutate process env so Playwright's driver Node starts under devenv/nix.

    Safe to call multiple times. Idempotent for common lab shells.
    """
    # Prefer host/devenv Node over Playwright's bundled one (GLIBC skew).
    if not os.environ.get("PLAYWRIGHT_NODEJS_PATH"):
        node = shutil.which("node")
        if node:
            os.environ["PLAYWRIGHT_NODEJS_PATH"] = node

    # nix/devenv often injects a libstdc++ that breaks the driver Node.
    if os.environ.get("SIGNALS_BROWSER_KEEP_LD_PATH", "").strip() not in (
        "1",
        "true",
        "yes",
    ):
        for key in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
            if key in os.environ:
                # Stash for debugging; child inherits cleared env after we del.
                os.environ.setdefault(f"SIGNALS_BROWSER_SAVED_{key}", os.environ[key])
                del os.environ[key]


def chromium_executable() -> str | None:
    """Resolve a Chromium binary, or None to use Playwright's bundled browser."""
    env = os.environ.get("SIGNALS_CHROMIUM_PATH") or os.environ.get(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
    )
    if env and Path(env).is_file():
        return env
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    return None


def sync_playwright():
    """``playwright.sync_api.sync_playwright`` after env prep."""
    prepare_playwright_env()
    try:
        from playwright.sync_api import sync_playwright as _sp
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "playwright is required for headless UI checks. "
            "Install with: uv sync --group dev  (or uv sync --extra browser) "
            "then: just browser-install"
        ) from e
    return _sp()


def launch_chromium(
    playwright: Any,
    *,
    headless: bool | None = None,
    **kwargs: Any,
) -> Any:
    """Launch Chromium for UI verification.

    Env:
      SIGNALS_CHROMIUM_PATH — force executable
      SIGNALS_BROWSER_HEADED=1 — headed mode (debug)
      SIGNALS_BROWSER_SLOW_MO_MS — Playwright slow_mo
      SIGNALS_BROWSER_KEEP_LD_PATH=1 — do not clear LD_LIBRARY_PATH
    """
    prepare_playwright_env()
    if headless is None:
        headless = os.environ.get("SIGNALS_BROWSER_HEADED", "").strip() not in (
            "1",
            "true",
            "yes",
        )
    exe = chromium_executable()
    args = list(kwargs.pop("args", None) or [])
    # Container / CI-friendly defaults
    for a in (
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--font-render-hinting=none",
    ):
        if a not in args:
            args.append(a)

    launch_kwargs: dict[str, Any] = {
        "headless": headless,
        "args": args,
        **kwargs,
    }
    slow = os.environ.get("SIGNALS_BROWSER_SLOW_MO_MS", "").strip()
    if slow.isdigit():
        launch_kwargs["slow_mo"] = int(slow)
    if exe:
        launch_kwargs["executable_path"] = exe

    return playwright.chromium.launch(**launch_kwargs)
