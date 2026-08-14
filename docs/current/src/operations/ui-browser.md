# Headless browser (signals-ui verification)

UI changes **must** be exercised with a real browser, not only curl. Signals
ships Playwright + Chromium for that.

## What is installed

| Piece | Source |
|-------|--------|
| Python API | `playwright` (uv `dev` group + optional extra `browser`) |
| Launcher | `signals.browser` — resolves Chromium, fixes devenv/nix driver env |
| Chromium | devenv package `chromium` on PATH, or `SIGNALS_CHROMIUM_PATH`, or Playwright-bundled after `just browser-install` |
| Node for driver | devenv `nodejs_22` via `PLAYWRIGHT_NODEJS_PATH` (auto) |

## Recipes

```bash
just browser-install   # no-op when chromium already on PATH
just ui-verify         # queues lineup one-shot → build/ui-verify/*.png
just ui-test           # pytest tests/ui/ -m browser
```

`just test` **ignores** `tests/ui/` (needs live UI). Unit suite stays hermetic.

## Env

| Variable | Role |
|----------|------|
| `SIGNALS_UI_BASE` | default `http://127.0.0.1:9889` |
| `SIGNALS_CHROMIUM_PATH` | force Chromium binary |
| `SIGNALS_BROWSER_HEADED=1` | show window |
| `SIGNALS_BROWSER_SLOW_MO_MS` | Playwright slow_mo |
| `SIGNALS_UI_BROWSER_SKIP=1` | skip browser fixtures |
| `SIGNALS_BROWSER_KEEP_LD_PATH=1` | do not clear `LD_LIBRARY_PATH` |

## devenv / nix note

Playwright ships its own Node. Under devenv, a nix `LD_LIBRARY_PATH` with a
newer `libstdc++` can break that Node (`GLIBC_2.3x not found`). `signals.browser`
and `just ui-*` clear `LD_LIBRARY_PATH` and point the driver at system/devenv
Node. Prefer system Chromium from devenv (`packages = [ chromium … ]`).

## Code

```python
from signals.browser import launch_chromium, sync_playwright, default_ui_base

with sync_playwright() as p:
    browser = launch_chromium(p)
    page = browser.new_page()
    page.goto(f"{default_ui_base()}/queues")
    page.locator("#queues-lineup-shell").wait_for()
    browser.close()
```
