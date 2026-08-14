# Settings: loopback + YuniKorn `/` 404

**Date:** 2026-08-13 (morning UX)

## Issues

1. Settings showed `http://127.0.0.1:30080/` and `:21010/` as plain mono — not
   useful when the operator browses signals-ui via FQDN.
2. YuniKorn REST **`/` → 404** (API only; no SPA). yk-web UX is signals-ui.

## Fix

- `signals-ui-core::browser_url` — rewrite loopback for browser; YK browse path
  `/ws/v1/clusters`; Atlas `/login.jsp`.
- Settings template: real anchors + connect-vs-browse + link to `/queues`.
- Env: `SIGNALS_UI_PUBLIC_HOST` (optional) > Host header > `SIGNALS_KRB_HOST`.

## Verify

```bash
curl -s -H 'Host: tinybox.dev.vista.zndx.org:9889' http://127.0.0.1:9889/settings \
  | rg 'ws/v1/clusters|login.jsp|connect \(server\)'
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:30080/ws/v1/clusters  # 200
```
