# Headless browser tooling for signals-ui

**Date:** 2026-08-13

## Why

UI work (queues Aegir lineup) requires real browser verification. curl alone
cannot exercise side-nav SECTION, `openFrom`, session trail, or panel geometry.

## Landed

| Piece | Path |
|-------|------|
| Launcher | `src/signals/browser.py` |
| Pytest | `tests/ui/test_queues_lineup.py` (+ conftest) |
| One-shot | `scripts/ui_browser_verify.py` |
| Just | `browser-install`, `ui-test`, `ui-verify` |
| devenv | `chromium` package |
| uv | `playwright` in dev group + optional `browser` extra |
| Docs | `docs/current/src/operations/ui-browser.md` |

## devenv/nix fix

Playwright bundled Node breaks when `LD_LIBRARY_PATH` injects nix `libstdc++`
(GLIBC symbol errors). Fix:

- `PLAYWRIGHT_NODEJS_PATH` → devenv Node
- clear `LD_LIBRARY_PATH` in `prepare_playwright_env()` and `just ui-*`

Prefer system Chromium: `SIGNALS_CHROMIUM_PATH` or devenv `chromium` on PATH.

## Verified (lab)

```
just ui-test   → 6 passed
just ui-verify → PASS; screenshots build/ui-verify/queues-*.png
```

Lineup: SECTION current/scratch/archive, root panel, child openFrom → 2 panels,
ops/health, settings engine lattice.
