# Inherited codebase audit (2026-08-14)

Scope: signals hub + dirty `signals-protocol` / `signals-ui` submodules
after the 2026-08-13 engine-first YuniKorn / lineup / landing pass.
Not a full sigint/ASF-stack review.

## Verdict

Doctrine is right and the new engine surface is real. The tree is an
**uncommitted lab spike**: protocol + Python engine + CLI/MCP + UI landing
and queues lineup work, none of it locked to `origin/trunk`. Product paths
for **landing + queues** are engine-first. **Applications** and UI readiness
still treat YK REST as required. Engine is not a devenv/systemd citizen yet.
Treat as shippable design, not a shippable commit set without a lock-in pass.

## What this repo is

Two layers in one tree:

1. **sigint** — classification pipeline (CLAUDE.md still describes this as
   the primary workflow). Mature, largely untouched by this spike.
2. **Federation hub** — peer contract, `signals.target`, signals-ui `:9889`,
   and now a Python **Signals engine** on `:50551` with
   `zndx.engine.v1.Engine` + `zndx.yunikorn.v1.YuniKorn`.

CLAUDE.md still says “Rust — planned gRPC engine (not yet implemented).”
That is stale.

## Architecture that landed (and holds)

```
signals-ui · signals-yk · signals-yk-mcp
        │  gRPC only (intended)
        ▼
:50551  Engine/Status(capability=yunikorn) + YuniKorn
        │ private REST / kubectl
        ▼
YK :30080  ·  ConfigMap yunikorn-configs/queues.yaml
```

- Multi-service gRPC + reflection on one lattice port.
- Promote: validate-conf → kubectl apply (prefer `yunikorn-configs`) →
  archive current → write scratch → current. Dry-run is live-tested.
- Projection roots: archive / current / scratch (Aegir-shaped).
- UI: Atelier landing + Scheduler band (`GetDashboard`); Queues lineup
  (info + Kumo Flow). `/status` redirects to `/#scheduler`.
- Tests: 16 hermetic `tests/signals/`; 6 Playwright `tests/ui/` (queues).

## Findings

### High

1. **Uncommitted three-repo spike.** Parent dirty +
   `components/signals-protocol` + `components/signals-ui` dirty. Submodule
   SHAs are not advanced. A checkout of `origin/trunk` does not have the
   engine, proto, or UI.

2. **Engine is not in the unit.** `peer-contract.json` names
   `signals-engine.service`; `infra/systemd/` has `signals.service` /
   `signals.target` but **no** `signals-engine.service`. No `devenv.nix`
   process. Current listeners are ad-hoc `setsid` from this session. Restart
   / `signals.target` will not bring `:50551` up.

3. **Doctrine leak: Applications + `/readyz` still REST-first.**
   `page_applications` and `/api/yk/ws/v1/*` use `YkClient`.
   `/readyz` is true iff `SIGNALS_YK_API_URL` is set — **not** iff engine
   `Status` is healthy. UI can be “ready” with a dead engine; landing/queues
   then fail in JS.

4. **API symmetry incomplete.** CLI/MCP cover ops + promote, not
   `GetDashboard`. Landing charts are UI-only. A second client cannot
   reproduce the Scheduler band.

### Medium

5. **Promote never live-applied.** Dry-run against lab CM succeeded.
   `applied=true` path unproven. Federation queue promote is still “next
   phase.”

6. **Insecure gRPC, no authz on promote.** `insecure_channel` /
   `add_insecure_port`. Anyone who can reach `:50551` can
   `PromoteScratch` and mutate the cluster ConfigMap. Lab-ok; not a unit
   story.

7. **`kubectl` apply is a process-boundary leak.** Works; couples engine
   to kubeconfig + PATH. Fine as adapter; document as private, not a
   second product API.

8. **Generated stubs duplicated.** `scripts/generated/` and
   `src/signals/engine/generated/`. Easy to drift. UI codegen is
   tonic-build at compile time (good).

9. **Dead UI Rust.** `QueueLineupPanel`, `QueueCard`, `StatusPage`,
   REST `build_lineup_trail` leftovers, `/api/yk/*` proxies.
   `require_yk` still means REST URL, not engine.

10. **No landing browser tests.** Queues lineup is covered; `/` Scheduler
    band is screenshot-only.

11. **Projection vs live tree.** Lineup live cards come from
    `GetQueueTree`; scratch/archive from notes. Current root overlays live
    well; scratch edit UX is POLICY yaml + notes, not the Flow cards.

### Low / hygiene

12. **Docs drift:** CLAUDE.md Rust-engine line; `grpc-engine.md` still
    talks k8s `:50051`; session memory still says “P2 MCP/UI open.”
13. **hs_err_pid*.log** in repo root (pre-existing JVM crashes).
14. **Asset cache-bust** is a version suffix string — works; easy to forget
    to bump.
15. **Playwright + nix `LD_LIBRARY_PATH`** is documented and wrapped; still
    a footgun if someone runs pytest without `just ui-test`.

## What I would not change

- Engine-first YuniKorn service (separate from `Engine` Complete/Remediate).
- ConfigMap promote adapter + dry-run before apply.
- Aegir lineup geometry (SECTION + trail + openFrom).
- Landing as Atelier orientation + below-fold Scheduler, not raw JSON.
- Hermetic unit tests for projection/promote/normalize.

## Suggested lock-in order (when you want commits)

1. Protocol submodule: `yunikorn.proto` + spec.
2. Signals: `src/signals/engine|cli|mcp`, tests, scripts, docs; systemd
   unit + devenv process + `signals.target` wants engine.
3. signals-ui: landing + lineup + `signals-ui-engine`; then Applications
   via engine `ListQueueApplications`.
4. Flip `/readyz` to engine Status (REST optional/private).
5. One elevated `*-ci` for engine reflection + GetDashboard + lineup
   browser; keep smoke one-off.

## Residual product work (not audit nits)

- Live federation-queue promote pass (user deferred).
- Applications engine-first.
- MCP/CLI `dashboard`.
- TLS / lattice auth when this leaves lab bind.
