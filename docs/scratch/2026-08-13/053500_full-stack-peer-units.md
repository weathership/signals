# Full-stack peer units under signals.target

**Date:** 2026-08-13

## Doctrine addition

Total commitment includes **full project devenv stack** on unit start — not
engine-only lattice shells. `signals.target` start ⇒ each enabled peer’s
`just up` / `devenv up` graph (capability engine + product UI/gateway/DB).

## Gap

| Peer | Was | Should be |
|------|-----|-----------|
| Gaius | full `just up` | already correct shape |
| Metabase | full `just up` + dashboard health | already correct shape |
| Ægir | engine-only `:50151` | full stack + `:8091` + `:5173` |
| Atelier | engine-only `:50251` | full stack + `:50071` + `:8090` + `:3000` |

## Remediation landed (working trees)

### Ægir `~/local/src/zndx/aegir`
- `devenv.nix` — process `capability-engine` on `:50151`
- `scripts/systemd_{start,stop}.sh` — just up / devenv down; accept Status+gateway+vite
- `docs/current/src/operations/peer-unit.md` — full-stack SoR

### Atelier `~/local/src/zndx/atelier`
- `devenv.nix` — process `capability-engine` on `:50251`
- `scripts/systemd_{start,stop}.sh` — just up / devenv down; accept Status+product+UI
- `docs/current/src/operations/peer-unit.md` — full-stack SoR

### Signals hub
- doctrine + peer-unit-spec + peer-integration + peer-contract notes

## Validate (operator)

```bash
sudo systemctl restart aegir.service atelier.service   # or full signals.target
ss -lntp | rg ':(50151|50251|8091|5173|8090|3000|50071)\b'
cd ~/local/src/wxs/signals && just lattice-ci --require gaius,aegir,atelier,metabase
```

## Still open

- Peer commits / push
- Gaius dual-bind on `:50051` can still reappear
- Free host `:3000` (kubectl/tilt) so Atelier vite uses canonical port

## Restart that ran aground (2026-08-13 ~05:42–06:03)

`systemctl restart signals.target` stuck ~20m with `aegir`/`atelier` **activating**:

| Peer | Failure | Fix |
|------|---------|-----|
| **Ægir** | `devenv` eval refused insecure `minio-…`; `just up` failed; poll forever with no stack | `devenv.yaml` `permittedInsecurePackages` + `NIXPKGS_ALLOW_INSECURE=1` in unit start |
| **Atelier** | `just up` = **foreground** `devenv up` — never returns under oneshot | unit start uses **`devenv up -d` only** |
| **Atelier vite** | `:3000` held by kubectl/tilt → vite on **:3001**; naive curl `:3000` false-positive | accept probes node/vite on 3000 **or** 3001 |

Recovered by killing stuck jobs, restarting units with fixed scripts.

**Post-fix (06:05):** both active; lattice-ci pass=4; Ægir UI `:8091`/`:5173`; Atelier `:8090`/`:3001`/`:50071`/`:50251`.
