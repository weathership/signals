# Peer unit acceptance spec (shared handoff)

Template for completing **local-to-peer-repo** work (Gaius, Ægir, Atelier,
Metabase, …) while preserving that project’s context. Signals owns the contract
and lattice CI; peers own engine process + gRPC face + systemd wrappers.

**Contract pin:** `config/platform/peer-contract.json` (`schema_version`, commit).  
**Ops narrative (all peers):** [Peer integration](./peer-integration.md).  
**Group control:** `infra/systemd/`.  
**Lattice CI:** `just lattice-ci` / `scripts/lattice_ci.sh`.

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
  [ ] Status advertises capability
  [ ] No bind on signals :5455 or RustFS :9010
  [ ] If external/AGPL: no source/jar vendored into weathership/signals

Accept:
  [ ] systemctl start <id>.service → active (RemainAfterExit oneshot OK)
  [ ] grpcurl -plaintext 127.0.0.1:<port> list   # includes zndx.engine.v1.Engine
  [ ] grpcurl -plaintext 127.0.0.1:<port> zndx.engine.v1.Engine/Status
  [ ] just lattice-ci --require <id>   # codegen Status + reflection check
  [ ] (optional) product HTTP health

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
  [x] systemd_stop / just down = devenv processes down only
      (never just teardown / gpu-deep-cleanup — those kill sibling GPU leases)

Accept:
  [x] Recycle via `systemctl restart signals.target` (lab 2026-08-13) + orphan :50051 cleanup
  [x] systemctl start/restart gaius.service → active (oneshot; Status body project=gaius)
  [x] grpcurl -plaintext 127.0.0.1:50051 list / Engine/Status (reflection)
  [x] just lattice-ci --require gaius     # elevated CI; reflection required

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
- Two devenv process-compose daemons can both hold `:50051` — `devenv
  processes restart` may no-op. Accept needs *this* checkout's engine process
  recycled, not a second stack.
- Gaius-local Metabase `:3100` is not capability `dashboard` (AGPL peer
  `:3200` / `:50451`).
- Unit enabled; **accept closed** after full `signals.target` restart validation
  (2026-08-13): dual :50051 orphans fixed; reflection + lattice-ci green.

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
> Engine faces already exist on `:50151` — add reflection, unit wrappers that wait  
> on codegen Status (not gateway stack-health), soft stop, product  
> `docs/current/src/operations/peer-unit.md`. Do not re-architect the multi-face engine.

```text
Title: peer-unit@aegir lattice join
Contract: signals peer-contract.json schema_version=1.0.0
Peer id: aegir
Repo path: ~/local/src/zndx/aegir
Unit: aegir.service  (sample: signals infra/systemd/aegir.service)
gRPC port: 50151
Postgres lattice: 5555
Capability (Status): instruct  (project=aegir)
License: project-specific · external=false · architecture_class=core_federated_engine

Already present (do not rebuild engine architecture):
  [x] Multi-face on :50151 — native AegirEngine + zndx.engine.v1 + OIP
  [x] ZndxEngineServicer Status / Complete / Remediate
  [x] grpcio-reflection in lockfile (Linux) — must still ENABLE in serve()

Must (this session):
  [x] Enable gRPC server reflection on engine port (advertise zndx.engine.v1.Engine)
  [x] scripts/systemd_start.sh + systemd_stop.sh in aegir tree
  [x] Start brings capability engine on :50151 via `python -m aegir.engine.server`
      (NOT just up stack-health; NOT engine-supervise / SERVING wait)
  [x] Start waits on codegen Status project=aegir (scripts/zndx_status_ok.py)
  [x] Soft stop — TERM engine only; no teardown / GPU wipe of siblings
  [x] Unit Exec* → wrappers; After=signals-ready · WantedBy=signals.target
  [x] docs/current/src/operations/peer-unit.md (product SoR for the unit)
  [x] PG only on :5555; never :5455 / :9010

Accept:
  [x] systemctl start/enable aegir.service → active under signals.target
  [x] grpcurl -plaintext 127.0.0.1:50151 list / Engine/Status
  [x] just lattice-ci --require aegir   # codegen + reflection (live w/ gaius+metabase)
  [ ] (optional) gateway http://127.0.0.1:8091/api/health — product UX only

Out of scope:
  - signals critical plane
  - redesigning multi-face engine (already correct)
  - requiring full vLLM cold-load for unit active (Status at gRPC bind is enough)
```

**Implementation notes (2026-08-13):**

- **Cleaner than Gaius process model for lattice:** unit starts only the capability
  engine (`setsid` + pid/log under `/tmp/aegir-engine/`), not the whole devenv
  graph. Accept is pure lattice face.
- **Explicitly not `engine-supervise`:** supervise waits SERVING (vLLM load);
  lattice ready is Status at bind. Models load on first Complete/Remediate.
- Dual-bind guard on `:50151` (Gaius orphan lesson).
- Commit Ægir-tree peer files if still untracked (`scripts/systemd_*`,
  `zndx_status_ok.py`, `peer-unit.md`, reflection in `server.py`).

---

## Filled: atelier

**Ops:** [Peer integration — Atelier](./peer-integration.md#atelier)  
**Accept closed 2026-08-13** (engine-only unit, mirror Ægir). Lattice green live.

**Agent one-liner (full paths) — lock-in / converge session:**

> Lock in `peer-unit@atelier` under `signals.target`. Coordination (read fully):  
> `/home/rch/local/src/wxs/signals/docs/current/src/operations/peer-unit-spec.md`  
> (section **Filled: atelier**),  
> `/home/rch/local/src/wxs/signals/docs/current/src/operations/peer-integration.md`  
> (section **Atelier** / `#atelier`),  
> `/home/rch/local/src/wxs/signals/config/platform/peer-contract.json`,  
> `/home/rch/local/src/wxs/signals/docs/scratch/2026-08-13/025900_atelier-peer-unit.md`.  
> Reference units:  
> `/home/rch/local/src/zndx/aegir/docs/current/src/operations/peer-unit.md`,  
> `/home/rch/local/src/zndx/aegir/scripts/systemd_start.sh`,  
> `/home/rch/local/src/zndx/aegir/scripts/systemd_stop.sh`,  
> `/home/rch/local/src/zndx/aegir/scripts/zndx_status_ok.py`  
> (and Gaius  
> `/home/rch/local/src/zndx/gaius/docs/current/src/operations/peer-unit.md`  
> for co-tenancy/soft-stop).  
> **Already landed on this host (do not re-architect):** engine-only unit on  
> `:50251` (`python -m atelier.engine.server`), reflection, codegen Status  
> (`project=atelier`), product servicer `:50071` off the unit path;  
> `atelier.service` active;  
> `just lattice-ci --require gaius,aegir,atelier,metabase` green from  
> `/home/rch/local/src/wxs/signals`.  
> **This session:** commit untracked Atelier peer files  
> (`scripts/systemd_{start,stop}.sh`, `scripts/zndx_status_ok.py`,  
> `src/atelier/engine/server.py` reflection + Status placeholders,  
> `pyproject.toml` grpcio-reflection,  
> `docs/current/src/operations/peer-unit.md`); add SUMMARY link if missing;  
> add a small Status/reflection test if useful; verify dual-port docs  
> (lattice `:50251` vs product `:50071`); confirm soft stop does not touch  
> Gaius/Ægir leases; re-run  
> `cd /home/rch/local/src/wxs/signals && just lattice-ci --require atelier`  
> and bare  
> `grpcurl -plaintext 127.0.0.1:50251 list` / `Engine/Status`.  
> Do not start product `just up` as the lattice accept path; do not wait  
> vLLM SERVING for unit active.

```text
Title: peer-unit@atelier lattice join
Contract: signals peer-contract.json schema_version=1.0.0
Peer id: atelier
Repo path: ~/local/src/zndx/atelier
Unit: atelier.service  (sample: signals infra/systemd/atelier.service)
gRPC port: 50251          # lattice / capability engine
Native servicer (co-tenant): 50071   # not lattice accept port
Postgres lattice: 5533
Capability (Status): referee  (capability_hint)
License: project-specific · external=false

Must (landed 2026-08-13):
  [x] scripts/systemd_start.sh + systemd_stop.sh (engine-only, mirror Ægir)
  [x] Enable gRPC server reflection on :50251
  [x] Wait on codegen Status project=atelier (not product :50071)
  [x] Status advertises referee (+ configured caps) at gRPC bind
  [x] Soft stop — TERM engine only; no product stack / GPU wipe
  [x] Unit Exec* → wrappers; After=signals-ready · WantedBy=signals.target
  [x] docs/current/src/operations/peer-unit.md
  [x] PG only on :5533; never :5455 / :9010

Accept:
  [x] systemctl start/enable atelier.service → active under signals.target
  [x] grpcurl -plaintext 127.0.0.1:50251 list / Engine/Status
  [x] just lattice-ci --require atelier   # codegen + reflection
  [ ] (optional) product just up / servicer :50071 for workbench UX

Out of scope:
  - CAI single-tenant :50051 defaults on co-tenant hosts
  - signals critical plane
  - requiring vLLM cold-load for unit active
```

**Implementation notes:** same engine-only model as Ægir (`python -m
atelier.engine.server`, setsid + `/tmp/atelier-engine/`). Product servicer
`:50071` stays off the lattice unit path.

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
