#!/usr/bin/env python3
"""One-shot headless verification of signals-ui (queues lineup).

Usage::

    just ui-verify
    # or
    uv run python scripts/ui_browser_verify.py
    SIGNALS_UI_BASE=http://127.0.0.1:9889 uv run python scripts/ui_browser_verify.py --headed

Exit 0 on pass; non-zero on failure. Screenshots land under build/ui-verify/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from signals.browser import default_ui_base, launch_chromium, sync_playwright


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Headless verify signals-ui queues lineup")
    p.add_argument("--base", default=default_ui_base(), help="signals-ui base URL")
    p.add_argument("--headed", action="store_true", help="show browser")
    p.add_argument(
        "--out",
        default="build/ui-verify",
        help="screenshot directory (default build/ui-verify)",
    )
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = args.base.rstrip("/")
    failures: list[str] = []

    with sync_playwright() as pw:
        browser = launch_chromium(pw, headless=not args.headed)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        try:
            resp = page.goto(f"{base}/healthz", wait_until="networkidle", timeout=15_000)
            if resp is not None and resp.status >= 400:
                failures.append(f"healthz HTTP {resp.status}")
            elif not page.content():
                failures.append("healthz empty body")

            page.goto(f"{base}/queues", wait_until="networkidle", timeout=45_000)
            page.locator("#queues-lineup-shell").wait_for(state="visible", timeout=20_000)
            page.locator("#lineup-root").wait_for(state="visible", timeout=20_000)
            page.locator(".lineup-panel-aegir").first.wait_for(
                state="visible", timeout=25_000
            )
            page.screenshot(path=str(out / "queues-lineup.png"), full_page=True)
            print(f"OK  /queues shell + panel  → {out / 'queues-lineup.png'}")

            # Drill a child if present
            child = page.locator(
                ".lineup-kumo-seed-list a.lineup-seed, a.lineup-wikilink"
            ).first
            if child.count():
                child.click()
                page.wait_for_timeout(500)
                page.screenshot(path=str(out / "queues-child.png"), full_page=True)
                n = page.locator(".lineup-panel-aegir").count()
                print(f"OK  openFrom child panels={n}  → {out / 'queues-child.png'}")
            else:
                print("WARN no child links to openFrom (projection may be shallow)")

            page.goto(
                f"{base}/queues?open=ops/health",
                wait_until="networkidle",
                timeout=30_000,
            )
            body = page.locator(".lineup-panel-aegir-body").inner_text(timeout=15_000)
            if "health" not in body.lower() and "schedul" not in body.lower():
                failures.append(f"ops/health body unexpected: {body[:120]!r}")
            else:
                print("OK  ops/health virtual note")

            page.goto(f"{base}/settings", wait_until="networkidle", timeout=20_000)
            content = page.content()
            if "engine" not in content.lower() and "50551" not in content:
                # soft — settings may still render without exact text
                print("WARN settings page missing engine lattice mention")
            else:
                print("OK  /settings engine lattice")
        except Exception as e:  # noqa: BLE001
            failures.append(str(e))
            try:
                page.screenshot(path=str(out / "failure.png"), full_page=True)
                print(f"screenshot → {out / 'failure.png'}", file=sys.stderr)
            except Exception:  # noqa: BLE001
                pass
        finally:
            browser.close()

    if failures:
        print("FAIL:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("PASS ui browser verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
