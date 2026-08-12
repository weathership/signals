# Lattice CI + foundation systemd install

**Date:** 2026-08-12

## Landed

| Item | Path |
|------|------|
| Peer unit acceptance specs | `docs/current/src/operations/peer-unit-spec.md` |
| Lattice CI gate | `scripts/lattice_ci.sh` · `just lattice-ci` |
| Systemd installer | `scripts/install_signals_systemd.sh` · `just install-systemd` |

## Behavior

- `just lattice-ci` — SKIP absent peers; PASS Status RPC; FAIL if required/listening broken
- `just lattice-ci --require gaius,metabase` — hard-fail those ids
- Foundation units only via `just install-systemd --enable --start` (peers not enabled until peer-unit-spec accept)

## Host tools (system-wide)

- `/usr/local/bin/just` 1.40.0 — required for all units
- `/usr/local/bin/kubectl` — required for signals-ready Eventing probe under systemd
- `/usr/local/bin/grpcurl` 1.9.3 — required for lattice-ci Status probes
## Verified on this host

```text
systemctl is-active signals.service signals-ready.service signals.target
→ active / active / active
just lattice-ci → OK (all peers SKIP until peer sessions land)
```

## Next (peer sessions)

1. gaius: `peer-unit@gaius` from peer-unit-spec.md
2. metabase: `peer-unit@metabase` (AGPL external)
3. Then `just install-systemd --peers gaius,metabase --enable` + `just lattice-ci --require gaius,metabase`
