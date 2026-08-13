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
  [ ] Status.project matches contract (or project_status)
  [ ] Status advertises capability
  [ ] No bind on signals :5455 or RustFS :9010
  [ ] If external/AGPL: no source/jar vendored into weathership/signals

Accept:
  [ ] systemctl start <id>.service → active (RemainAfterExit oneshot OK)
  [ ] grpcurl -plaintext 127.0.0.1:<port> zndx.engine.v1.Engine/Status
  [ ] just lattice-ci --require <id>
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
  [x] grpcurl -plaintext 127.0.0.1:50051 zndx.engine.v1.Engine/Status
      (reflection after grpcio-reflection; proto fallback remains ops path)
  [x] just lattice-ci --require gaius     # elevated CI gate, not a smoke

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
- Unit already `install-systemd --peers gaius --enable`; **Accept still open**
  until the live engine recycle above (lattice-ci currently FAILs Status RPC
  on the pre-change process).

---

## Filled: aegir

**Ops:** [Peer integration — Aegir](./peer-integration.md#aegir)

```text
Title: peer-unit@aegir lattice join
Contract: signals peer-contract.json schema_version=1.0.0
Peer id: aegir
Repo path: ~/local/src/zndx/aegir
Unit: aegir.service  (sample: signals infra/systemd/aegir.service)
gRPC port: 50151
Postgres lattice: 5555
Capability (Status): instruct  (capability_hint)
License: project-specific · external=false

Must:
  [ ] scripts/systemd_start.sh + systemd_stop.sh
  [ ] Start ensures capability engine Status on :50151
      (just up stack-health alone is NOT sufficient if engine is separate)
  [ ] After=signals-ready.service · WantedBy=signals.target
  [ ] PG only on :5555
  [ ] GPU co-tenancy / leases respected on stop

Accept:
  [ ] systemctl start aegir.service → active
  [ ] grpcurl -plaintext 127.0.0.1:50151 zndx.engine.v1.Engine/Status
  [ ] just lattice-ci --require aegir
  [ ] (optional) gateway http://127.0.0.1:8091/api/health

Out of scope:
  - signals critical plane; other peers' GPU engines
```

**Peer session focus:** unit start must bring **:50151**, not only gateway/vite
from `just up` / `stack-health`. Recipes: `engine-serve`, `engine-ready`,
`engine-supervise` as needed inside the wrapper.

---

## Filled: atelier

**Ops:** [Peer integration — Atelier](./peer-integration.md#atelier)

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

Must:
  [ ] scripts/systemd_start.sh + systemd_stop.sh
  [ ] Wait on Engine/Status at :50251 (not only :50071 servicer ready)
  [ ] After=signals-ready.service · WantedBy=signals.target
  [ ] Document dual-port layout for operators
  [ ] PG only on :5533

Accept:
  [ ] systemctl start atelier.service → active
  [ ] grpcurl -plaintext 127.0.0.1:50251 zndx.engine.v1.Engine/Status
  [ ] just lattice-ci --require atelier

Out of scope:
  - CAI single-tenant :50051 defaults on co-tenant hosts
  - signals critical plane
```

**Peer session focus:** lattice port **50251** is the accept gate; native
servicer **50071** is product API on multi-engine labs.

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
