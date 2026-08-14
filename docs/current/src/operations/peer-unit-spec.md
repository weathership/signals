# Peer unit acceptance spec (shared handoff)

Template for completing **local-to-peer-repo** work (Gaius, Ægir, Atelier,
Metabase, …) while preserving that project’s context. Signals owns the contract
and lattice CI; peers own engine process + gRPC face + systemd wrappers.

**Contract pin:** `config/platform/peer-contract.json` (`schema_version`, commit).  
**Ops narrative (all peers):** [Peer integration](./peer-integration.md).  
**Group control:** `infra/systemd/`.  
**Lattice CI:** `just lattice-ci` / `scripts/lattice_ci.sh`.  
**Doctrine:** [Total commitment as a federation peer](../architecture/signals-protocol-core.md#doctrine-total-commitment-as-a-federation-peer)
— full engine capacity + honest start/stop/restart; lattice Status is not a
quasi-engine substitute. Signals is **early** on its own engine axis (not
“permanently thin”); peerhood still means total commitment to *that* project’s
real engine and ops transitions.

**Pattern source:** Metabase landed first — peer wrappers wait for product
health **and** `Engine/Status`; unit files call those scripts (no multiline
shell). See [common peer unit pattern](./peer-integration.md#common-peer-unit-pattern-learned-from-metabase).

---

## Blank template (copy into peer work order)

```text
Title: peer-unit@<id> lattice join
Contract: signals peer-contract.json schema_version=<X> @ <signals-git-sha>
Peer id: <id>
Repo path: <path_hint from contract>
Unit: <id>.service  (sample: signals infra/systemd/<id>.service)
gRPC port: <engine_grpc_lattice.<id>>
Postgres lattice: <pg_port or engine_pg_port>
Capability (Status): <capability or capability_hint>
License: <license>   external=<true|false>

Must:
  [ ] WorkingDirectory = path_hint (or documented override)
  [ ] scripts/systemd_start.sh + systemd_stop.sh in THIS tree
  [ ] Unit ExecStart/Stop → those scripts (absolute paths)
  [ ] After=signals-ready.service · WantedBy/PartOf=signals.target
  [ ] Start waits until Engine/Status on contract gRPC port
  [ ] gRPC **server reflection** enabled (`grpcio-reflection` or equivalent)
  [ ] Status.project matches contract (or project_status)
  [ ] Status advertises capability **honestly** (no synthetic always-healthy
      rows when backends are down — full-capacity doctrine)
  [ ] Unit starts the **full devenv stack** (`just up` / `devenv up`) for this
      project — capability engine **and** product UI/gateway/DB as applicable
      (not engine-only / lattice-only)
  [ ] Lattice engine is part of that stack (process-compose or equivalent)
  [ ] **Peer-scoped unit stop**: fully stop this project's stack; free lattice
      + product ports; do NOT host-wide teardown / gpu-deep-cleanup that kills
      siblings (not a weak stop)
  [ ] **Restart = full stop then full start** (orphans / multi-listener =
      error → remediate)
  [ ] No bind on signals :5455 or RustFS :9010
  [ ] If external/AGPL: no source/jar vendored into weathership/signals

Accept:
  [ ] systemctl start <id>.service → active (RemainAfterExit oneshot OK)
  [ ] systemctl stop <id>.service → lattice + product ports free; no leftovers
  [ ] systemctl restart <id>.service → single lattice listener; full stack; Status OK
  [ ] grpcurl -plaintext 127.0.0.1:<port> list   # includes zndx.engine.v1.Engine
  [ ] grpcurl -plaintext 127.0.0.1:<port> zndx.engine.v1.Engine/Status
  [ ] just lattice-ci --require <id>   # codegen Status + reflection check
  [ ] product UI/gateway health as documented for this peer
  [ ] peer remediation path on transition fail

Out of scope:
  - signals critical-plane changes
  - other peers' ports/units
  - Argo / Marquez DB / second Metaflow SoR
```

**After accept (Signals operator):**

```bash
just install-systemd --peers <id> --enable
sudo systemctl start signals.target   # not bare "signals"
```

---

## Filled: gaius

**Ops:** [Peer integration — Gaius](./peer-integration.md#gaius)  
**Product SoR (in Gaius tree):** `docs/current/src/operations/peer-unit.md`

```text
Title: peer-unit@gaius lattice join
Contract: signals peer-contract.json schema_version=1.0.0
Peer id: gaius
Repo path: ~/local/src/zndx/gaius
Unit: gaius.service  (sample: signals infra/systemd/gaius.service)
gRPC port: 50051
Postgres lattice: 5444   (db zndx_gaius)
Capability (Status): cognition  (capability_hint)
License: project-specific · external=false

Must:
  [x] WorkingDirectory = ~/local/src/zndx/gaius
  [x] scripts/systemd_start.sh + systemd_stop.sh (Metabase pattern)
  [x] Unit Exec* → those scripts; After=signals-ready.service
  [x] Wait until zndx.engine.v1.Engine/Status on :50051
      (native GaiusService + OIP already share this port — TCP listen ≠ Status)
  [x] Status.project ~ gaius; capability cognition advertised
  [x] PG only on :5444 — never :5455
  [x] Platform Metaflow URL when joining federation (not Tilt as SoR)
  [x] Peer-scoped unit stop = devenv processes down for this tree only
      (never host teardown / gpu-deep-cleanup that kill sibling GPU leases)

Accept:
  [x] Recycle via `systemctl restart signals.target` (lab 2026-08-13) + orphan :50051 cleanup
  [x] systemctl start/restart gaius.service → active (oneshot; Status body project=gaius)
  [x] grpcurl -plaintext 127.0.0.1:50051 list / Engine/Status (reflection)
  [x] just lattice-ci --require gaius     # elevated CI; reflection required
  [x] Group lifecycle (`systemctl` alone, 2026-08-13): stop reaps every
      Gaius-cwd devenv compose + frees :50051; start brings one listener in
      `system.slice/gaius.service` with reflection. `just lattice-ci --require
      gaius` PASS. Pin `XDG_RUNTIME_DIR` + reap-by-cwd (do not attach to a
      leftover login-shell compose).

Out of scope:
  - Metabase AGPL product, Ægir/Atelier internals
  - signals critical plane
  - Gaius-local Metabase :3100 as federation dashboard
  - Implementing Remediate on this face (Aegir :50151)
  - GPU-mesh write-up in src/gaius/engine/FEDERATION.md (not the accept gate)
```

**Peer session focus (done):** wrappers + **third servicer**
`zndx.engine.v1.Engine` on the existing `:50051` server (beside `GaiusService`
+ OIP). Health/FMEA stays Gaius-local (`/health fix engine`). Product notes:
Gaius `docs/current/src/operations/peer-unit.md` — **not** `FEDERATION.md`
(older KServe mesh).

**Gaius-specific (lab):**

- Status is live at gRPC bind (engine init phase GRPC, ~1s). Do not wait for
  vLLM/endpoint load (~240s) to declare lattice ready.
- `just up` / `just down` exist for the wrappers; `restart-clean` is a full
  product recycle, not the unit start path.
- Two devenv process-compose daemons can both hold `:50051` because gRPC
  defaults to **SO_REUSEPORT** (kernel load-balances Status). Engine now sets
  `grpc.so_reuseport=0` and `gaius-engine.sh` refuses start if the port is
  taken (`#EN.00000014.DUALBIND`). `devenv processes restart` may no-op or
  spawn a *second* daemon (`/tmp/devenv-<hash>` vs `$XDG_RUNTIME_DIR`).
- Gaius-local Metabase `:3100` is not capability `dashboard` (AGPL peer
  `:3200` / `:50451`).
- Live 2026-08-13: one listener on `:50051`. `grpcurl list` shows
  `zndx.engine.v1.Engine`. `just lattice-ci --require gaius` PASS (codegen +
  reflection). Pin `grpcio-reflection<1.82` — 1.83+ needs protobuf 7, which
  `xai-sdk` forbids.

---

## Filled: aegir

**Ops:** [Peer integration — Aegir](./peer-integration.md#aegir)  
**Copy into Aegir session as the work order.**

**Agent one-liner (full paths):**

> Implement `peer-unit@aegir` per  
> `/home/rch/local/src/wxs/signals/docs/current/src/operations/peer-unit-spec.md`  
> (section **Filled: aegir**) and  
> `/home/rch/local/src/wxs/signals/docs/current/src/operations/peer-integration.md`  
> (section **Aegir** / `#aegir`). Contract pin:  
> `/home/rch/local/src/wxs/signals/config/platform/peer-contract.json`.  
> Reference implementation:  
> `/home/rch/local/src/zndx/gaius/docs/current/src/operations/peer-unit.md` and  
> `/home/rch/local/src/zndx/gaius/scripts/systemd_start.sh`,  
> `/home/rch/local/src/zndx/gaius/scripts/systemd_stop.sh`,  
> `/home/rch/local/src/zndx/gaius/scripts/zndx_status_ok.py`.  
> Full-stack under `signals.target` (doctrine): unit = `just up` / devenv full
> graph including capability-engine + gateway + vite — not engine-only.

```text
Title: peer-unit@aegir lattice join
Contract: signals peer-contract.json schema_version=1.0.0
Peer id: aegir
Repo path: ~/local/src/zndx/aegir
Unit: aegir.service  (sample: signals infra/systemd/aegir.service)
gRPC port: 50151
Product UI: gateway :8091 · vite :5173
Postgres lattice: 5555
Capability (Status): instruct  (project=aegir)
License: project-specific · external=false · architecture_class=core_federated_engine

Already present:
  [x] Multi-service on :50151 — native AegirEngine + zndx.engine.v1 + OIP
  [x] ZndxEngineServicer Status / Complete / Remediate
  [x] gRPC server reflection enabled

Must (full-stack remediation 2026-08-13):
  [x] scripts/systemd_start.sh + systemd_stop.sh — **just up / devenv full stack**
  [x] devenv process `capability-engine` on :50151 (not unit-only setsid)
  [x] Start waits on Status + gateway :8091 + vite :5173
  [x] Peer-scoped **full-stack** stop; no GPU wipe of siblings
  [x] Unit Exec* → wrappers; After=signals-ready · WantedBy=signals.target
  [x] docs/current/src/operations/peer-unit.md
  [x] PG only on :5555; never :5455 / :9010

Accept:
  [x] systemctl start/enable aegir.service → active under signals.target
  [ ] systemctl restart → full stack (UI + lattice); re-validate after remediation
  [x] grpcurl / lattice-ci --require aegir
  [ ] gateway :8091 + vite :5173 after unit start

Out of scope:
  - signals critical plane
  - requiring full vLLM cold-load for unit active (Status at gRPC bind is enough)
```

**Implementation notes:**

- **2026-08-13 (earlier):** engine-only unit — **incorrect under total-commitment /
  full-stack doctrine**; product UI stayed dark under `signals.target`.
- **2026-08-13 (remediation):** wrappers = Gaius/Metabase pattern (`just up`);
  `capability-engine` in `devenv.nix`; accept = Status + gateway + vite.
- Dual-bind guard still required on `:50151`.

---

## Filled: atelier

**Ops:** [Peer integration — Atelier](./peer-integration.md#atelier)  
**Lattice green (engine-only) 2026-08-13; full-stack remediation required same day.**

```text
Title: peer-unit@atelier lattice join
Contract: signals peer-contract.json schema_version=1.0.0
Peer id: atelier
Repo path: ~/local/src/zndx/atelier
Unit: atelier.service  (sample: signals infra/systemd/atelier.service)
gRPC lattice: 50251
Product servicer: 50071 · gateway :8090 · vite :3000
Postgres lattice: 5533
Capability (Status): referee  (capability_hint)
License: project-specific · external=false

Must (full-stack remediation 2026-08-13):
  [x] scripts/systemd_start.sh + systemd_stop.sh — **just up / devenv full stack**
  [x] devenv process `capability-engine` on :50251 (+ existing grpc-server :50071)
  [x] Start waits on Status + :50071 + gateway :8090 + vite :3000
  [x] Peer-scoped **full-stack** stop; no GPU wipe of siblings
  [x] Unit Exec* → wrappers; After=signals-ready · WantedBy=signals.target
  [x] docs/current/src/operations/peer-unit.md
  [x] PG only on :5533; never :5455 / :9010

Accept:
  [x] systemctl start/enable atelier.service → active under signals.target
  [ ] systemctl restart → full stack; re-validate after remediation
  [x] grpcurl / lattice-ci --require atelier
  [ ] product :50071 + gateway :8090 + vite :3000 after unit start

Out of scope:
  - CAI single-tenant :50051 defaults on co-tenant hosts
  - signals critical plane
  - requiring vLLM cold-load for unit active
```

**Implementation notes:** engine-only unit was an oversight under full-stack
doctrine. Both lattice (`:50251`) and product (`:50071` + UI) belong under the
unit via devenv.

---

## Filled: metabase (AGPL external — isolated)

**License-external by requirement** (AGPL ↛ ASL2). mbengine is architecturally
**isolated** from the core engine family (Gaius / Ægir / Atelier / synth /
vigil). Process attachment may follow the same unit pattern; engine lineage
does not. Operators:
[Peer integration — Metabase](./peer-integration.md#external-engines-metabase-agpl) ·
[Core vs external](../architecture/signals-protocol-core.md#core-vs-license-external-engines).

```text
Title: peer-unit@metabase lattice join
Contract: signals peer-contract.json schema_version=1.0.0
Peer id: metabase
Repo path: ~/local/src/agpl/metabase   (or any path outside signals)
Unit: metabase.service  (sample: signals infra/systemd/metabase.service)
gRPC port: 50451
Engine PG: 5577 · dashboard HTTP: :3200
Capability (Status): dashboard  (required)
License: AGPL-3.0 · external=true

Must:
  [x] WorkingDirectory / ExecStart scripts = AGPL checkout only
  [x] scripts/systemd_start.sh + systemd_stop.sh (wait health+Status)
  [x] After=signals-ready.service · WantedBy/PartOf=signals.target
  [x] mbengine: zndx.engine.v1.Engine on :50451
  [x] Status.project=metabase · capability=dashboard · non-secret base_url
  [x] Never vendor Metabase into weathership/signals

Accept (lab host):
  [x] systemctl start metabase.service → active (or start signals.target)
  [x] grpcurl -plaintext 127.0.0.1:50451 zndx.engine.v1.Engine/Status
  [x] just lattice-ci --require metabase
  [x] GET http://127.0.0.1:3200/api/health

Out of scope:
  - ASL2 signals packaging of AGPL product
  - other engine ports
```

**Operator one-liner:** from signals tree,
`just install-systemd --peers metabase --enable` then
`sudo systemctl start signals.target` (not bare `systemctl start signals`).

---

## Synth (stub)

| id | port | path_hint | capability_hint |
|----|------|-----------|-----------------|
| synth | 50351 | ~/local/src/zndx/synth | synthesis |

Copy blank template when scheduled.

---

## Signals-side responsibilities (not in peer session)

| Task | Recipe / path |
|------|----------------|
| Foundation ready | `just signals-ready` · `signals-ready.service` |
| Group control samples | `infra/systemd/` |
| Contract | `config/platform/peer-contract.json` |
| Probe lattice | `just lattice-ci` |
| Ops for all peers | [peer-integration.md](./peer-integration.md) |

Peers implement engines; signals verifies the lattice after they claim ready.
