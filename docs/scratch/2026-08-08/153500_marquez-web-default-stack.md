# Marquez-web is default stack (not optional)

**Date:** 2026-08-08

## Decision

`processes.marquez-web` is a **core** process: every `devenv up` / `devenv up -d`
starts it. Not opt-in.

## Implementation notes

- **Turn-key (cybersec pattern):** users only need `devenv up [-d]`
- `languages.javascript` → `directory = components/marquez/web`,
  `npm.enable` + `npm.install.enable` (devenv first-party enterShell install)
- `tasks.marquez:build-web` with `before = [ "devenv:processes:marquez-web" ]`
  (submodule init + npm + webpack; idempotent)
- Process only runs `setupProxy.js` (static UI + `/api/v1` → Atlas `:21010`)
- Tier-1 `REQUIRED_PROCESSES` includes `marquez-web`
- No ad-hoc `packages.nodejs` — Node comes from `languages.javascript.package`
