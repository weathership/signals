# Full Aegir queues lineup (engine-first)

**Date:** 2026-08-13

## What landed

### signals-ui-engine (tonic)
- Crate: `components/signals-ui/crates/signals-ui-engine`
- Generated from `signals-protocol` protos (`zndx.yunikorn.v1` + `engine.v1`)
- Product path: `SIGNALS_ENGINE_TARGET` (default `127.0.0.1:50551`)

### JSON gateway (UI → engine gRPC)
| Route | Role |
|-------|------|
| `GET /api/engine/v1/info` | lattice health |
| `GET /api/engine/v1/health` | YK health via engine |
| `GET /api/engine/v1/partitions` | partitions |
| `GET /api/engine/v1/projection/index` | lineup index by root |
| `GET /api/engine/v1/projection/note` | note body + links |
| `POST /api/engine/v1/projection/sync` | rebuild current |
| `GET /api/engine/v1/archives` | freezes |
| `GET /api/engine/v1/diff` | scratch/current/live |
| `GET /api/engine/v1/nodes` | partition nodes |

Virtual note ids (gateway-synthesized, engine-backed):
`config/queues`, `ops/nodes`, `ops/diff`, `ops/health`.

### Aegir geometry (`/queues`)
- Side-nav **SECTION** = archive | current | scratch
- Groups: QUEUES · POLICY · OPS (sync)
- Full-height horizontal panels (~33rem), `openFrom(i)`, × close
- Trail in `sessionStorage`; URL `?root=&open=&partition=` focus only
- Client island: `assets/js/queues-lineup.js`
- CSS: full-height shell under chrome (`body:has(.queues-lineup-page)`)

### Verify (lab)
```
curl -s http://127.0.0.1:9889/api/engine/v1/info
curl -s 'http://127.0.0.1:9889/api/engine/v1/projection/index?root=current'
curl -s 'http://127.0.0.1:9889/queues' | rg lineup-shell
```

## Deferred (next phase)
- Live federation queue promote pass against cluster
- Optional HoloViews embeds (not required for chassis)
