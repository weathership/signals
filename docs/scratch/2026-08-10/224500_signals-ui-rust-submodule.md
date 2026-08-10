# signals-ui: Rust submodule, yk-web strict superset

## Decisions

| Decision | Choice |
|----------|--------|
| Isolation | `git@github.com:weathership/signals-ui.git` → `components/signals-ui` |
| Service language | Idiomatic Rust (Axum/Tokio) — **no Node.js service** |
| Capability bar | **Strict superset** of yunikorn-web (all routes + all `/ws/v1` usages) |
| Theme | Keiretsu + Kumo dark/light (CSS tokens, not AntD/Node) |
| Value-add | Sentinels, OTel, Atlas OL, engines — after/with YK parity |

## Doc

`docs/current/src/architecture/signals-control-plane-ui.md` rewritten accordingly.
