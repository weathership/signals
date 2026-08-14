# Full `systemctl restart signals.target` (2026-08-13)

## Command

```bash
sudo systemctl restart signals.target   # ~87s, exit 0
```

## Result (after Gaius remediation)

| Check | Outcome |
|-------|---------|
| `signals.target` | active |
| foundation + `signals-ready` | READY (all critical PASS) |
| aegir / atelier / metabase / gaius units | active (exited oneshots) |
| Listeners | **1 each** on `:50051` `:50151` `:50251` `:50451` |
| Cgroup ownership | each engine under its `*.service` slice |
| `just lattice-ci --require gaius,aegir,atelier,metabase` | **OK** pass=4 skip=synth |

## Clean recycle by peer

| Peer | First full-target restart | After fix |
|------|---------------------------|-----------|
| **aegir** | Clean — stop freed `:50151`, new engine under unit | still single listener under `aegir.service` |
| **atelier** | Clean — same | still single under `atelier.service` |
| **metabase** | Clean — full product stack + Status | single under `metabase.service` |
| **gaius** | **Not clean** — see below | single under `gaius.service` after orphan purge |

## Gaius issues found

1. **Stop too weak** — `just down` alone left orphan `python -m gaius.engine` on `:50051` (started 00:47). Start then hit `already READY — skip up`.
2. **Dual/triple bind** — two **user-session** process-compose daemons (`session-1.scope`, `/run/user/1001/devenv-…`) kept respawning engines beside the unit’s process-compose (`system.slice/gaius.service`, `/tmp/devenv-…`). Lattice Status still PASSed with multiple listeners (flaky class).
3. **Foundation note** — `just up` failed with port 5455 already in use; script correctly treated live READY as success (`foundation READY despite up failure`).

## Remediation applied (gaius tree, uncommitted)

- `scripts/systemd_stop.sh` — after devenv down, TERM/KILL `gaius.engine` on lattice port (aegir/atelier pattern).
- `scripts/systemd_start.sh` — do not skip-up when `>1` listener; only skip when exactly one listener and Status OK.
- Manual: KILL orphan user-session process-compose PIDs that owned foreign engines.

## Follow-ups

- On gaius stop (or start guard): refuse multi-owner process-compose / kill foreign `gaius.engine` outside unit cgroup.
- Avoid interactive `devenv up` for gaius while unit owns the lattice port.
- Optional: full target restart again to prove gaius path without manual purge.
