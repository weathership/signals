# Peer integration (federation engines + external services)

How sibling engines and **license-external** services attach to the Signals
foundation without re-hosting the critical plane.

**End state (lab):** after each peer finishes its local unit work and is
**enabled** under the group:

```bash
sudo systemctl start signals.target
# → foundation (signals.service) + signals-ready + every enabled peer
```

Bare `systemctl start signals` starts **only** the foundation unit — not peers.

---

## Two layers

| Layer | What | How peers use it |
|-------|------|------------------|
| **Process / group** | `signals.target` + foundation ready gate | systemd `After=signals-ready.service` |
| **Wire / product** | signals-protocol + platform endpoints | gRPC `zndx.engine.v1.Engine`, Metaflow/Airflow/CE, Atlas |

| Artifact | Path |
|----------|------|
| Machine-readable contract | [`config/platform/peer-contract.json`](../../../config/platform/peer-contract.json) |
| Unit samples | [`infra/systemd/`](../../../infra/systemd/) |
| Peer-repo acceptance templates | [Peer unit acceptance spec](./peer-unit-spec.md) |
| Group control README | [`infra/systemd/README.md`](../../../infra/systemd/README.md) |

```text
                    ┌─────────────────────────────┐
                    │     signals.target          │
                    │  (group controller)         │
                    └─────────────┬───────────────┘
                                  │
           ┌──────────────────────┼──────────────────────┐
           ▼                      ▼                      ▼
   signals.service      signals-ready.service     (enabled peers)
   just up / down       just signals-ready        After=ready
           │                      │                      │
           ▼                      ▼                      ▼
   critical plane          PASS ⇒ exit 0           gaius · aegir
   PG Kudu Impala          Kudu+Metaflow           atelier · synth
   YK Metaflow AF          critical included       metabase (AGPL opt.)
   Eventing Broker
```

Peers are **peer-to-peer** with each other (no ordering edges among engines).
All order after **`signals-ready.service`**.

---

## Foundation lifecycle

```bash
# Manual / CI
just up
just signals-ready          # check-only; exit 0 when critical plane is ready
just down                   # lattice-safe stop

# Group control
sudo systemctl start signals.target
systemctl list-dependencies signals.target
sudo systemctl stop signals.target
```

**Do not** treat `devenv up -d` returning as “ready.” Peers wait on
`signals-ready` (or the oneshot that polls it). Prefer `just down` over bare
`devenv processes down` so Postgres `:5455` is released.

### Host tools (system-wide)

Service units do **not** inherit devenv/nix PATH. Install under `/usr/local/bin`
(or equivalent on systemd `PATH`):

| Tool | Used by |
|------|---------|
| **`just`** | Foundation + peer wrappers |
| **`kubectl`** | `signals-ready` (Eventing Broker) |
| **`grpcurl`** | `lattice-ci` + peer accept probes |

See [infra/systemd/README.md](../../../infra/systemd/README.md).

---

## What peers consume (not re-host)

| Concern | Use platform | Avoid |
|---------|--------------|--------|
| Workflow metadata | Metaflow `:30180` + `config/metaflow/platform.json` | Engine-local Tilt Metaflow as SoR when in platform mode |
| DAG production | Airflow `:30800` | Argo Workflows for Metaflow prod |
| Events | Knative Broker `signals-events/default` | Argo Events |
| Schedule / STZ | YuniKorn + Knative Serving | Unscheduled free-for-all pods |
| Lineage / governance | Atlas OL + tags (`:21010`) | Peer Marquez DB |
| Analytic tables | Impala HS2 + Kudu (Kerberos) | Parallel warehouses on `:5455` |
| Object store | RustFS `:9010` | Competing S3 on same ports |

**Postgres port lattice** (do not collide):

| Port | Owner |
|------|--------|
| 5432 | system/apt (Metabase app DB may use) |
| 5438 | cybersec / cyberphy |
| **5444** | **Gaius** |
| **5455** | **Signals foundation** |
| **5533** | **Atelier** |
| **5555** | **Ægir** |
| 5566 | Synth |
| 5577 | Metabase engine DB (AGPL product) |

---

## signals-protocol engines (gRPC lattice)

Each peer registers **`zndx.engine.v1.Engine`** (federation face) beside any
native service. That face is the **shared federation contract in progress** —
it evolves as real peer needs land in engines and get promoted into
`signals-protocol` (see [protocol core — evolution](../architecture/signals-protocol-core.md#how-the-federation-contract-evolves)).
Peer units and lattice-ci only attach process lifecycle to whatever Status the
contract currently requires; they do not define the full engine architecture.

Lab lattice:

| Peer | Port | Capability (Status) | Unit sample | Notes |
|------|------|---------------------|-------------|--------|
| **Gaius** | **50051** | `cognition` | `gaius.service` | Product engine / federation mesh |
| **Ægir** | **50151** | `instruct` | `aegir.service` | Capability engine (+ native face) |
| **Atelier** | **50251** | `referee` | `atelier.service` | Capability engine; native servicer may be `:50071` on co-tenant hosts |
| Synth | 50351 | `synthesis` | `synth.service` | Optional peer |
| Metabase | 50451 | `dashboard` | `metabase.service` | **License-external** (AGPL); isolated engine, not core family |

```bash
# Reflection required on the lattice port (signals-protocol install requirement)
grpcurl -plaintext 127.0.0.1:<port> list   # must include zndx.engine.v1.Engine
grpcurl -plaintext 127.0.0.1:<port> zndx.engine.v1.Engine/Status
just lattice-ci                      # SKIP absent; PASS listening (uses reflection)
just lattice-ci --require gaius,aegir,atelier
```

Python engines: depend on `grpcio-reflection` and enable reflection at server
start. Spec: [engine_grpc.md — Server reflection](../../../components/signals-protocol/specification/protocol/engine_grpc.md#server-reflection-required) ·
[signals-protocol](../components/signals-protocol.md).

OIP (KServe Open Inference Protocol) is the long-term portable inference face;
`Complete` remains a transitional convenience on many engines.

---

## Common peer unit pattern (process attachment)

Reference implementations: **Metabase** (unit shape, license-external) and
**Gaius** (core peer, first full lattice accept under `signals.target`). The
**process** pattern is shared; **engine lineage** for core peers is
Gaius/Ægir/Atelier — Metabase is
[license-external and isolated](../architecture/signals-protocol-core.md#core-vs-license-external-engines).

### Must

1. **`After=signals-ready.service`** + `Wants=signals-ready.service`  
   Soft dependency: foundation failure does not hard-fail the peer (`Requires=`
   only if you want a hard gate).

2. **`PartOf=` / `WantedBy=signals.target`**  
   Group stop/restart and opt-in membership via `systemctl enable/disable`.

3. **Wrappers in the peer tree** (not signals, not multiline shell in the unit):
   - `scripts/systemd_start.sh` — idempotent up; **block until accept probes pass**
   - `scripts/systemd_stop.sh` — lattice-safe / product-safe down  
   Unit `ExecStart=` / `ExecStop=` point at those absolute paths under the peer
   checkout. systemd rejects fragile multiline shell; Metabase hit this first.

4. **Accept = federation face ready**, not “product stack healthy alone”:
   - **Codegen Status** (preferred in-peer): generated `zndx.engine.v1` stubs,
     `project` matches contract (see Signals `scripts/zndx_engine_status.py` /
     Gaius `scripts/zndx_status_ok.py`)
   - **Reflection** on the lattice port so external bare `grpcurl` works
     (install `grpcio-reflection` / enable ServerReflection — **required**)
   - **TCP listen alone is not enough** (Gaius lesson)
   - Optional product health (gateway, dashboard HTTP, …)

5. **Idempotent start**  
   If accept probes already pass, exit 0 without tearing down a live stack.

6. **Single owner of the lattice port**  
   Avoid dual listeners (orphan devenv + unit). Reclaim or refuse multi-bind
   (Gaius lesson on `:50051`).

7. **PATH**  
   System-wide `just` / `grpcurl` / `kubectl` on systemd `PATH`; `bash -lc`
   inside wrappers when devenv/direnv is required.

8. **Never bind** Signals `:5455` or RustFS `:9010`.

9. **Product doc** in the peer tree (Gaius pattern):
   `docs/current/src/operations/peer-unit.md` — unit SoR for that project;
   not mesh/`FEDERATION.md` history.

### Operator flow (any peer)

```bash
# In peer repo: implement wrappers + federation Status; standalone accept
# In signals:
just install-systemd --enable --start                    # foundation once
just install-systemd --peers <id> --enable               # opt-in peer sample
# Edit /etc/systemd/system/<id>.service paths if checkout ≠ lab default
sudo systemctl daemon-reload
sudo systemctl start signals.target                      # one-command group
just lattice-ci --require <id>
```

| Command | Starts |
|---------|--------|
| `systemctl start signals` | **Foundation only** |
| **`systemctl start signals.target`** | Foundation + ready + **all enabled peers** |
| `systemctl start <peer>` | That peer alone (still `After=signals-ready`) |

Acceptance templates: [peer-unit-spec](./peer-unit-spec.md).

---

## Federated in-org peers

These sections are the **operations reference** for peer-repo integration
sessions and for Signals operators who enable the peer after that work lands.

| Peer | Status |
|------|--------|
| **Metabase** | Complete (license-external AGPL; isolated engine) |
| **Gaius** | Complete under `signals.target` (codegen Status + reflection + lattice-ci) |
| **Ægir** | Complete under `signals.target` (codegen Status + reflection + lattice-ci) |
| **Atelier** | Complete under `signals.target` (engine-only `:50251`, product `:50071` separate) |

Tick accept in [peer-unit-spec](./peer-unit-spec.md).

### Gaius

| Fact | Value |
|------|--------|
| Role | Cognition / product engine; federation mesh participant |
| Checkout (lab) | `~/local/src/zndx/gaius` |
| Unit sample | [`infra/systemd/gaius.service`](../../../infra/systemd/gaius.service) → Gaius `scripts/systemd_{start,stop}.sh` |
| gRPC lattice | **`:50051`** — `zndx.engine.v1.Engine` **beside** native `GaiusService` + OIP |
| Postgres lattice | **`:5444`** (`zndx_gaius`) — never `:5455` |
| Capability | `cognition` (`Status.project=gaius`) |
| Product lifecycle | `just up` / `just down` (wrappers); process `gaius-engine` |
| Platform Metaflow | `METAFLOW_SERVICE_URL=http://127.0.0.1:30180` + platform profile when federated |
| Events | e.g. `dev.gaius.article.curate.requested` → platform Broker |
| Signals checklist | [peer-unit-spec — gaius](./peer-unit-spec.md#filled-gaius) |
| Product ops (SoR for unit) | Gaius tree `docs/current/src/operations/peer-unit.md` |
| Not the accept gate | `src/gaius/engine/FEDERATION.md` (older KServe/GPU mesh) |

**Landed in Gaius tree (peer session):**

1. `scripts/systemd_start.sh` / `systemd_stop.sh` — wait for **Status** (not only TCP).
2. `GaiusZndxEngineServicer` on the existing gRPC server (`project=gaius`, capability `cognition`).
3. Product doc `docs/current/src/operations/peer-unit.md`.
4. Unit installed: `just install-systemd --peers gaius --enable` (lab host).

**Lessons for other peers (from Gaius):**

| Lesson | Detail |
|--------|--------|
| **TCP ≠ Status** | Native service already on `:50051` did not imply `zndx.engine.v1.Engine/Status` |
| **Third servicer** | Register lattice face **beside** native (+ OIP); do not replace product gRPC |
| **Status early** | Status is live at gRPC bind (~phase GRPC); do **not** wait for vLLM/endpoint load |
| **Stop is soft** | `just down` / processes down only — never teardown / GPU-deep-cleanup in the unit stop path |
| **One engine process** | Two devenv daemons can both claim `:50051`; recycle *this* checkout’s engine for accept |
| **FEDERATION.md vs peer-unit.md** | Mesh write-up ≠ lattice accept gate |
| **lattice-ci** | Elevated CI gate; **reflection required** on lattice port |

**Operator — finish accept (after engine recycle):**

```bash
# In Gaius: restart gaius-engine so the lattice servicer is bound
# e.g. devenv processes restart gaius-engine   (from this checkout only)

cd ~/local/src/wxs/signals
sudo systemctl start signals.target    # or: sudo systemctl start gaius
grpcurl -plaintext 127.0.0.1:50051 zndx.engine.v1.Engine/Status
just lattice-ci --require gaius
```

**Caution:** Gaius-local Metabase on `:3100` is **not** federation `dashboard`.
That is the optional AGPL Metabase peer (`:3200` / `:50451`).

---

### Aegir

Ægir instruct / inference peer (product name often styled “Ægir”). **Next peer
session** after Gaius.

**Agent one-liner (full paths for the Aegir session):**

> Implement `peer-unit@aegir` per  
> `/home/rch/local/src/wxs/signals/docs/current/src/operations/peer-unit-spec.md`  
> (**Filled: aegir**) and  
> `/home/rch/local/src/wxs/signals/docs/current/src/operations/peer-integration.md`  
> (**Aegir** / `#aegir`). Contract:  
> `/home/rch/local/src/wxs/signals/config/platform/peer-contract.json`.  
> Mirror:  
> `/home/rch/local/src/zndx/gaius/docs/current/src/operations/peer-unit.md`,  
> `/home/rch/local/src/zndx/gaius/scripts/systemd_start.sh`,  
> `/home/rch/local/src/zndx/gaius/scripts/systemd_stop.sh`,  
> `/home/rch/local/src/zndx/gaius/scripts/zndx_status_ok.py`.  
> Engine faces already exist on `:50151` — add reflection, unit wrappers that wait  
> on codegen Status (not gateway stack-health), soft stop, product peer-unit.md.  
> Do not re-architect the multi-face engine.

| Fact | Value |
|------|--------|
| Role | Instruct / inference peer; capability→model owned by engine |
| Architecture class | **core_federated_engine** (Gaius-lineage capability engine) |
| Checkout (lab) | `~/local/src/zndx/aegir` |
| Unit sample | [`infra/systemd/aegir.service`](../../../infra/systemd/aegir.service) → Ægir `scripts/systemd_{start,stop}.sh` |
| gRPC lattice | **`:50151`** — native `AegirEngine` + **`zndx.engine.v1.Engine`** + OIP (already co-registered in `aegir.engine.server`) |
| Postgres lattice | **`:5555`** |
| Capability / Status | `Status.project=aegir`, default capability **`instruct`** (Remediate is rich here) |
| Product stack | `just up` = devenv + **stack-health** (gateway `:8091`, vite, …) — **not** lattice accept |
| Engine process (unit) | **`python -m aegir.engine.server` only** — not `just up`, not `engine-supervise` |
| Reflection | Enabled at `serve()` (`enable_reflection`; advertises `zndx.engine.v1.Engine`) |
| Platform Metaflow | Platform URL when federated; local mode OK for isolated eval |
| YK | RKE2 → queue `root.aegir` (or contract name) |
| Session checklist | [peer-unit-spec — aegir](./peer-unit-spec.md#filled-aegir) |
| Product SoR | Ægir tree `docs/current/src/operations/peer-unit.md` |

**Already in good shape (do not re-architect):**

- Multi-face engine on `:50151` (native + zndx + OIP)
- `ZndxEngineServicer` with Status / Complete / **Remediate**
- `grpcio-reflection` present in lockfile (Linux) — **enabled at server start**
- GPU guard / `/tmp/zndx-gpu-leases` co-tenancy

**Landed in Ægir tree (peer session):**

1. gRPC server reflection on `:50151`.
2. Unit wrappers start **only** `python -m aegir.engine.server` (setsid +
   `/tmp/aegir-engine/unit_server.{pid,log}`); codegen Status wait; soft stop;
   dual-bind guard. **Not** `just up` / **not** `engine-supervise`.
3. Product `docs/current/src/operations/peer-unit.md`.
4. Signals `aegir.service` Exec* → wrappers; enabled under `signals.target`.
5. Live: `lattice-ci --require gaius,aegir,metabase` → OK.

**Operator:**

```bash
just install-systemd --peers aegir --enable
sudo systemctl start signals.target   # or: sudo systemctl start aegir
grpcurl -plaintext 127.0.0.1:50151 list
grpcurl -plaintext 127.0.0.1:50151 zndx.engine.v1.Engine/Status
just lattice-ci --require gaius,aegir,metabase
```

**Lesson for Atelier:** product servicer (`:50071`) and lattice engine (`:50251`)
stay separate start paths; unit accept is engine Status only (mirror this unit).

---

### Atelier

**Agent one-liner (full paths) — lock-in session (lattice already green):**

> Lock in `peer-unit@atelier` under `signals.target`. Read:  
> `/home/rch/local/src/wxs/signals/docs/current/src/operations/peer-unit-spec.md`  
> (**Filled: atelier**),  
> `/home/rch/local/src/wxs/signals/docs/current/src/operations/peer-integration.md`  
> (**Atelier** / `#atelier`),  
> `/home/rch/local/src/wxs/signals/config/platform/peer-contract.json`,  
> `/home/rch/local/src/wxs/signals/docs/scratch/2026-08-13/025900_atelier-peer-unit.md`.  
> Mirror:  
> `/home/rch/local/src/zndx/aegir/docs/current/src/operations/peer-unit.md` and  
> `/home/rch/local/src/zndx/aegir/scripts/systemd_start.sh`,  
> `/home/rch/local/src/zndx/aegir/scripts/systemd_stop.sh`,  
> `/home/rch/local/src/zndx/aegir/scripts/zndx_status_ok.py`.  
> Already live: engine-only `:50251`, reflection, codegen Status,  
> `atelier.service` active, lattice-ci with gaius+aegir+metabase green.  
> Commit untracked Atelier peer files, wire SUMMARY, verify dual-port docs  
> (`:50251` lattice vs `:50071` product), re-run  
> `/home/rch/local/src/wxs/signals` `just lattice-ci --require atelier` and bare  
> `grpcurl` list/Status. Do not use product `just up` as lattice accept.

| Fact | Value |
|------|--------|
| Role | Referee / CAI; capability engine on lattice |
| Architecture class | **core_federated_engine** |
| Checkout (lab) | `~/local/src/zndx/atelier` |
| Unit sample | [`infra/systemd/atelier.service`](../../../infra/systemd/atelier.service) → wrappers |
| gRPC lattice | **`:50251`** — native `AtelierEngine` + **`zndx.engine.v1.Engine`** + reflection |
| Product servicer | **`:50071`** (devenv) — **not** lattice accept |
| Postgres lattice | **`:5533`** |
| Capability / Status | `project=atelier`; advertises **referee** (+ configured instruct/referee models) |
| Engine process (unit) | **`python -m atelier.engine.server` only** — not `just up` |
| Product SoR | Atelier `docs/current/src/operations/peer-unit.md` |
| Session checklist | [peer-unit-spec — atelier](./peer-unit-spec.md#filled-atelier) (**accept closed**) |

**Landed (2026-08-13):**

- Reflection + Status placeholders at gRPC bind (Status early, models later).
- Engine-only unit (Ægir pattern): setsid + `/tmp/atelier-engine/unit_server.{pid,log}`.
- Codegen Status wait; soft stop; dual-bind guard on `:50251`.
- Live: `lattice-ci --require gaius,aegir,atelier,metabase` → OK.

**Operator:**

```bash
just install-systemd --peers atelier --enable
sudo systemctl start signals.target
grpcurl -plaintext 127.0.0.1:50251 list
grpcurl -plaintext 127.0.0.1:50251 zndx.engine.v1.Engine/Status
just lattice-ci --require gaius,aegir,atelier,metabase
```

---

## External engines: Metabase (AGPL)

Metabase is **external by license requirement** (AGPL vs ASL2), not merely
“optional product preference.” The Metabase engine (mbengine) is therefore
**inherently isolated**: separate checkout, no vendoring into Signals or core
peer trees, process + wire only. Architecturally it is **distinct** from the
core federated engine family (Gaius, Ægir, Atelier, and future core projects
such as synth or vigil). See
[Core vs license-external engines](../architecture/signals-protocol-core.md#core-vs-license-external-engines).

The core Signals stack does **not** require Metabase. Install only when you
want federated **`dashboard`** capability.

| Fact | Value |
|------|--------|
| License | **AGPL-3.0** (Signals is **Apache-2.0**) — isolation is required |
| Architecture | Isolated product engine; **not** Gaius-lineage / core peer family |
| Role | License-external `dashboard` engine (`Status.project=metabase`) |
| gRPC | `:50451` — `zndx.engine.v1.Engine` |
| Product HTTP | `:3200` (health: `GET /api/health`) |
| Engine Postgres | `:5577` (product-local; not signals `:5455`) |
| Sample unit | [`infra/systemd/metabase.service`](../../../infra/systemd/metabase.service) |
| Wrappers | AGPL tree `scripts/systemd_start.sh` / `systemd_stop.sh` |
| Peer contract | `peers[]` id `metabase` |
| Product docs | AGPL tree `README.engine.md` |
| Accept template | [peer-unit-spec — metabase](./peer-unit-spec.md#filled-metabase-agpl-external) (**landed**) |

### License boundary

| Do | Don't |
|----|--------|
| Separate checkout (e.g. `~/local/src/agpl/metabase`) | Submodule / jar-vendor into signals |
| Unit `WorkingDirectory` / Exec* → AGPL tree only | Ship AGPL inside ASL2 images without a legal plan |
| Vendor only `signals-protocol` in Metabase | Copy FE/BE into `weathership/signals` |
| Process + network integration | Secrets on the federation wire |

### Optional install (operators)

```bash
# 1. Standalone product (AGPL tree)
cd ~/local/src/agpl/metabase
just up   # or just rebuild
curl -sf http://127.0.0.1:3200/api/health
grpcurl -plaintext 127.0.0.1:50451 zndx.engine.v1.Engine/Status

# 2. From signals — opt in
cd ~/local/src/wxs/signals
just install-systemd --enable --start
just install-systemd --peers metabase --enable
# Edit unit paths if needed
sudo systemctl start signals.target   # not bare "signals"

# 3. Accept
systemctl is-active metabase.service
just lattice-ci --require metabase
```

### Federation leverage (Metabase)

1. Foundation ready before start.  
2. Optional platform Metaflow profile for flows that feed dashboards.  
3. CloudEvents via platform Broker when DAGs exist.  
4. YK queues for any RKE2 work.  
5. No second critical plane (engine/app DBs stay product-local).

---

## Synth (stub)

| Fact | Value |
|------|--------|
| gRPC | `:50351` |
| Postgres | `:5566` |
| Unit | `synth.service` |
| Status | Same pattern as Gaius/Ægir/Atelier when scheduled |

---

## Systemd membership (multi-peer)

```bash
# Foundation once
just install-systemd --enable --start

# Enable only peers whose local unit + Status work is done
just install-systemd --peers gaius,aegir,atelier,metabase --enable

sudo systemctl start signals.target
systemctl list-dependencies signals.target
just lattice-ci --require gaius,aegir,atelier,metabase   # whatever is enabled
```

- `PartOf=signals.target` — stop/restart of the group propagates.  
- `WantedBy=signals.target` — enable/disable controls membership.  
- Do **not** enable a peer until [peer-unit-spec](./peer-unit-spec.md) accept is green.

---

## Lattice CI

```bash
just lattice-ci
just lattice-ci --require gaius,aegir,atelier
just lattice-ci --all
just lattice-ci --json
```

Elevated **CI** gate — not part of `signals-ready` (critical plane only).

---

## Checklist for a new peer

1. Own lattice Postgres + gRPC ports (document in `peer-contract.json`).  
2. Vendor `signals-protocol`; implement `zndx.engine.v1.Engine/Status` (+ OIP path).  
3. Peer-tree `scripts/systemd_{start,stop}.sh`; unit points at them.  
4. `After=signals-ready.service`; never bind `:5455` / `:9010`.  
5. Start blocks until **lattice** Status (and product health if required).  
6. Platform Metaflow / CE / YK when joining production federation.  
7. If license ≠ ASL2 → external tree only (Metabase pattern).  
8. `just lattice-ci --require <id>` green; then `install-systemd --peers <id> --enable`.

---

## Related

- [Critical plane](../architecture/stack-critical-plane.md)
- [Platform Metaflow](../architecture/metaflow-platform.md)
- [signals-protocol](../components/signals-protocol.md)
- [Development environment](./devenv.md)
- [Peer unit acceptance spec](./peer-unit-spec.md)
