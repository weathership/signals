# Peer unit acceptance spec (shared handoff)

Template for completing **local-to-peer-repo** work (Gaius, Metabase, Ægir, …)
while preserving that project’s context. Signals owns the contract and lattice
CI; peers own engine process + gRPC face.

**Contract pin:** `config/platform/peer-contract.json` (`schema_version`, commit).  
**Group control:** `infra/systemd/` · [Peer integration](./peer-integration.md).  
**Lattice CI (foundation):** `just lattice-ci` / `scripts/lattice_ci.sh`.

---

## Blank template (copy into peer work order)

```text
Title: peer-unit@<id> lattice join
Contract: signals peer-contract.json schema_version=<X> @ <signals-git-sha>
Peer id: <id>
Repo path: <path_hint from contract>
Unit: <id>.service
gRPC port: <engine_grpc_lattice.<id>>
Postgres lattice: <pg_port or engine_pg_port>
Capability (Status): <capability or capability_hint>
License: <license>   external=<true|false>

Must:
  [ ] WorkingDirectory = path_hint (or documented override)
  [ ] ExecStart / ExecStop: just up + just down (or named recipes in peer Justfile)
  [ ] After=signals-ready.service (or poll foundation ready until exit 0)
  [ ] Listen zndx.engine.v1.Engine on contract gRPC port
  [ ] Status.project matches contract (or project_status)
  [ ] Status advertises capability (dashboard / cognition / …)
  [ ] No bind on signals :5455 or RustFS :9010
  [ ] If external/AGPL: no source/jar vendored into weathership/signals

Accept:
  [ ] systemctl start <id>.service → active (RemainAfterExit oneshot OK)
  [ ] grpcurl -plaintext 127.0.0.1:<port> zndx.engine.v1.Engine/Status
  [ ] just lattice-ci  (from signals tree) reports peer PASS or expected SKIP
  [ ] just lattice-ci --require <id>  passes when peer is required

Out of scope:
  - signals critical-plane changes
  - other peers' ports/units
  - Argo / Marquez DB / second Metaflow SoR
```

---

## Filled: gaius

```text
Title: peer-unit@gaius lattice join
Contract: signals peer-contract.json schema_version=1.0.0
Peer id: gaius
Repo path: ~/local/src/zndx/gaius
Unit: gaius.service  (sample: signals infra/systemd/gaius.service)
gRPC port: 50051
Postgres lattice: 5444
Capability (Status): cognition  (capability_hint)
License: project-specific · external=false

Must:
  [ ] just up / just down (or devenv up -d / processes down) match unit Exec*
  [ ] After=signals-ready.service
  [ ] zndx.engine.v1.Engine on :50051 (beside native Gaius service if any)
  [ ] Status.project ~ gaius; capability advertised
  [ ] PG only on :5444 lattice — never :5455

Accept:
  [ ] systemctl start gaius.service → active
  [ ] grpcurl -plaintext 127.0.0.1:50051 zndx.engine.v1.Engine/Status
  [ ] just lattice-ci --require gaius

Out of scope:
  - Metabase/AGPL, Ægir product internals
  - signals critical plane
```

**Peer session focus:** unit realism + federation Status on `:50051`; health/FMEA
stays Gaius-local.

---

## Filled: metabase (AGPL external)

```text
Title: peer-unit@metabase lattice join
Contract: signals peer-contract.json schema_version=1.0.0
Peer id: metabase
Repo path: ~/local/src/agpl/metabase
Unit: metabase.service  (sample: signals infra/systemd/metabase.service)
gRPC port: 50451
Engine PG: 5577 · dashboard HTTP: :3200
Capability (Status): dashboard  (required)
License: AGPL-3.0 · external=true

Must:
  [ ] WorkingDirectory = AGPL checkout only
  [ ] just up / just down per README.engine.md
  [ ] After=signals-ready.service
  [ ] mbengine: zndx.engine.v1.Engine on :50451
  [ ] Status.project=metabase · capability=dashboard · non-secret base_url
  [ ] Never vendor Metabase into weathership/signals

Accept:
  [ ] systemctl start metabase.service → active
  [ ] grpcurl -plaintext 127.0.0.1:50451 zndx.engine.v1.Engine/Status
  [ ] just lattice-ci --require metabase
  [ ] (optional product) GET http://127.0.0.1:3200/api/health

Out of scope:
  - ASL2 signals packaging of AGPL product
  - other engine ports
```

**Peer session focus:** process lifecycle + mbengine Status; product bootstrap
stays in metabase tree.

---

## Filled stubs (same pattern)

| id | port | path_hint | capability_hint |
|----|------|-----------|-----------------|
| aegir | 50151 | ~/local/src/zndx/aegir | instruct |
| atelier | 50251 | ~/local/src/zndx/atelier | referee |
| synth | 50351 | ~/local/src/zndx/synth | synthesis |

Copy the blank template; fill from `peer-contract.json` `peers[]` entry.

---

## Signals-side responsibilities (not in peer session)

| Task | Recipe / path |
|------|----------------|
| Foundation ready | `just signals-ready` · `signals-ready.service` |
| Group control samples | `infra/systemd/` |
| Contract | `config/platform/peer-contract.json` |
| Probe enabled lattice | `just lattice-ci` |

Peers implement engines; signals verifies the lattice after they claim ready.
