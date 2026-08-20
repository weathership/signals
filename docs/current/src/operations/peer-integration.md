# Peer integration (federation engines + external services)

How sibling engines and **license-external** services attach to the Signals
foundation without re-hosting the critical plane.

**Hub model:** Signals is **early** on the gRPC engine axis (federation
architecture still settling; little engine surface *yet*), while Gaius / Ægir /
Atelier already hold substantial engines. This tree currently centralizes
**control** (critical plane, `signals.target`, peer-contract, lattice-ci,
platform Metaflow/CE/YK/Atlas) so iterative cycles can surface and converge
depth in peer repos — and grow Signals engine work when the architecture is
ready. See
[Signals as hub — early on the engine axis](../architecture/signals-protocol-core.md#signals-as-hub--early-on-the-engine-axis-not-thin-forever).

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
| Resource-class queues | [`config/scheduler/resource-classes.md`](../../../config/scheduler/resource-classes.md) |
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
   signals.service      signals-ready.service     signals-engine.service
   just up / down       just signals-ready        :50551 After=ready
           │                      │                      │
           ▼                      ▼                      ▼
   critical plane          PASS ⇒ exit 0           Engine + Scheduler
   PG Kudu Impala          Kudu+Metaflow           (enabled peers after ready)
   YK Metaflow AF          critical included       gaius · aegir · atelier
   Eventing Broker                                 synth · metabase (AGPL opt.)
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
| Data product inventory | Signals warehouse (`details` / `tx` / `hx`) + RustFS URIs | Peer pglite / JSON catalog as SoR |

A peer that **maintains its own product** (Gaius prospects, Ægir corpora, …)
follows [Peer data products](./peer-data-products.md). Contract:
[`data_products.md`](../../../components/signals-protocol/specification/protocol/data_products.md).

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

## How to organize work on queues

YuniKorn leaves are **resource classes**, not project names. There is no
`root.gaius` (or `root.aegir`) GPU slice. Stamp identity on the Application and
pick a leaf from
[`resource-classes.md`](../../../config/scheduler/resource-classes.md).

| Work | Queue |
|------|--------|
| Host GPU: reasoning / CoT chat | `root.internal.inference.reasoning` |
| Host GPU: code model | `root.internal.inference.coding` |
| Host GPU: planner / tool-router | `root.internal.inference.orchestration` |
| Host GPU: instruct / short chat | `root.internal.inference.instruct` |
| Host GPU: embeddings | `root.internal.inference.embedding` |
| Host GPU: OCR / docling / extract | `root.internal.inference.extract` |
| CPU-only burst / idle sentinel | `root.internal.compute` |
| Metaflow UI / Airflow / Eventing | `root.platform` |
| Pay-per-token API | `root.external.token-metered` |
| RPM/TPM-limited API | `root.external.rate-metered` |
| Grok ACP / xAI subscription | `root.external.subscription.rate-limited` |

Required stamps:

- `yunikorn.apache.org/queue` **annotation** (placement rule is `provided`)
- `yunikorn.apache.org/app-id` = `federation.workload_id`
- `federation.project` for C2 → Yield
- Host GPU: request `federation.zndx.org/gpu` only (never `nvidia.com/gpu` on
  a CPU-only sentinel). In-cluster CUDA: both keys.

YK counts cpu/memory/GPU-token/`maxapplications`. Token, RPM, and subscription
math stay in the peer engine.

Platform services we deploy (Metaflow, Airflow, Eventing sink): `just redeploy`.
That is the K8s refresh — not `systemctl restart signals.target`. Signals
`just rebuild` is the **host Polarisfork** loop (assemble `components/polaris`,
restart devenv `polaris`, wait `:8182`) — same shape as Metabase `just rebuild`,
different tree. Metabase stays a host peer under `signals.target`.

MCP catalog/suggest tools come after this tree is live. Assignment RPCs land in
`signals-protocol` only after peers use that catalog.

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

**Doctrine:** federation peerhood is
[total commitment](../architecture/signals-protocol-core.md#doctrine-total-commitment-as-a-federation-peer)
— full engine capacity for that project, honest start/stop/restart, remediation
on failure. Lattice Status is a **gate on the real engine**, not a substitute
for it. Signals being **early** on its engine axis does not license half-
committed peers or freeze future engine work here.

### Must

1. **`After=signals-ready.service`** + `Wants=signals-ready.service`  
   Soft dependency: foundation failure does not hard-fail the peer (`Requires=`
   only if you want a hard gate).

2. **`PartOf=` / `WantedBy=signals.target`**  
   Group stop/restart and opt-in membership via `systemctl enable/disable`.

3. **Wrappers in the peer tree** (not signals, not multiline shell in the unit):
   - `scripts/systemd_start.sh` — **`just up` / full `devenv up`** for this
     project (capability engine + product UI/gateway/DB); **block until**
     lattice Status **and** product surfaces answer
   - `scripts/systemd_stop.sh` — **peer-scoped full-stack stop** of *this*
     unit’s devenv graph (and vLLM children); lattice + product ports free  
   Unit `ExecStart=` / `ExecStop=` point at those absolute paths under the peer
   checkout. systemd rejects fragile multiline shell; Metabase hit this first.
   Reference shapes: **Gaius / Metabase** (already full-stack); **Ægir /
   Atelier** remediated 2026-08-13 (were engine-only — incorrect under doctrine).

4. **Accept = full stack ready**, not “Status alone” or “engine-only”:
   - **Codegen Status** (preferred in-peer): generated `zndx.engine.v1` stubs,
     `project` matches contract (see Signals `scripts/zndx_engine_status.py` /
     Gaius `scripts/zndx_status_ok.py`)
   - **Honest health** — no synthetic always-healthy capabilities when backends
     are down (total-commitment doctrine)
   - **Product UI/gateway** as that peer documents (e.g. Ægir `:8091`+`:5173`,
     Atelier `:8090`+`:3000`, Metabase `:3200`)
   - **Reflection** on the lattice port so external bare `grpcurl` works
     (install `grpcio-reflection` / enable ServerReflection — **required**)
   - **TCP listen alone is not enough** (Gaius lesson)
   - Transition failures → **remediation** (peer-local health/FMEA; e.g. Gaius
     `/health fix engine`)

5. **Idempotent start only when the unit already owns a healthy single listener**  
   If accept probes pass **and** this unit is the sole owner of the lattice
   port with real capacity, exit 0 without tearing down a live stack. Multi-
   listener, orphans outside the unit cgroup, or optimistic Status that hides
   missing capacity are **errors** — stop/remediate, do not skip-up.

6. **Single owner of the lattice port**  
   Avoid dual listeners (orphan devenv + unit). Reclaim or refuse multi-bind
   (Gaius lesson on `:50051`). Interactive `devenv up` must not fight the unit.

7. **PATH**  
   System-wide `just` / `grpcurl` / `kubectl` on systemd `PATH`; `bash -lc`
   inside wrappers when devenv/direnv is required.

8. **Never bind** Signals `:5455` or RustFS `:9010`.

9. **Product doc** in the peer tree (Gaius pattern):
   `docs/current/src/operations/peer-unit.md` — unit SoR for that project;
   not mesh/`FEDERATION.md` history.

### Unit stop: peer-scoped (not “soft”)

**Do not call this “soft stop.”** That sounds like incomplete shutdown. The
requirement is **full stop of this peer’s unit**, scoped so co-tenants survive.

| Must | Must not |
|------|----------|
| **Fully stop this peer’s lattice unit** — engine process, process group, and vLLM/worker children it owns | Leave the lattice port listening “for convenience” |
| TERM → grace → KILL if needed; call engine `mgr.shutdown()` / process-group teardown | Host-wide `just teardown`, `gpu-deep-cleanup`, or kill-by-pattern that matches **sibling** peers |
| Release **this** peer’s GPU leases / free **this** peer’s GPUs | Wipe `/tmp/zndx-gpu-leases` or nvidia processes owned by Gaius/Ægir/Atelier others |
| Stop the **full project stack** owned by the unit (devenv graph: UI + gateway + lattice engine) | Engine-only stop that leaves product UI running (or vice versa) while claiming unit stopped |
| **Restart** = full stop then full start (total commitment) | Treat orphan Status or multi-bind as success |

**Why the confusion:** early Gaius unit stop used `just down` / `devenv processes
down` and explicitly avoided teardown recipes that historically killed
co-tenant GPUs. That is **lease-safe / co-tenant-safe**, not “don’t really stop.”
Engine-only units (Ægir, Atelier) should stop the **engine hard**; they should
not run product teardown.

**Preferred names:** *peer-scoped stop*, *unit stop*, or *lease-safe stop*.

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
| **`systemctl start signals.target`** | Foundation + ready + **all enabled peers** (does not restart live members) |
| **`systemctl restart signals.target`** | **Complete refresh** — stop every `PartOf=` member, start all enabled members, `signals-refresh.service` verifies Status |
| `just signals-restart` | Same recycle + fail if any enabled member is not active |
| `systemctl start <peer>` | That peer alone (still `After=signals-ready`) |

Acceptance templates: [peer-unit-spec](./peer-unit-spec.md).

---

## Federated in-org peers

These sections are the **operations reference** for peer-repo integration
sessions and for Signals operators who enable the peer after that work lands.

| Peer | Status |
|------|--------|
| **Metabase** | Complete (license-external AGPL; isolated engine) |
| **Gaius** | Full-stack under `signals.target` (Status + lattice-ci) |
| **Ægir** | Full-stack remediation 2026-08-13 (`just up`; was engine-only) — re-validate UI ports |
| **Atelier** | Full-stack remediation 2026-08-13 (`just up`; was engine-only) — re-validate UI ports |

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
| **Stop is peer-scoped, not weak** | Fully stop *this* peer’s engine (+ children); **never** host-wide teardown / `gpu-deep-cleanup` that kills sibling leases (see [Unit stop](#unit-stop-peer-scoped-not-soft)) |
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
> Full-stack under `signals.target`: unit = `just up` (capability-engine +
> gateway + vite). Accept = Status + product UI health.

| Fact | Value |
|------|--------|
| Role | Instruct / inference peer; capability→model owned by engine |
| Architecture class | **core_federated_engine** (Gaius-lineage capability engine) |
| Checkout (lab) | `~/local/src/zndx/aegir` |
| Unit sample | [`infra/systemd/aegir.service`](../../../infra/systemd/aegir.service) → Ægir `scripts/systemd_{start,stop}.sh` |
| gRPC lattice | **`:50151`** — native + **`zndx.engine.v1.Engine`** + OIP |
| Gateway / Vite UI | **`:8091`** / **`:5173`** |
| Postgres lattice | **`:5555`** |
| Capability / Status | `Status.project=aegir`, capability **`instruct`** |
| Unit process model | **Full devenv** (`just up`) — process `capability-engine` + gateway + vite |
| Accept | Status `:50151` + gateway health + vite |
| Session checklist | [peer-unit-spec — aegir](./peer-unit-spec.md#filled-aegir) |
| Product SoR | Ægir tree `docs/current/src/operations/peer-unit.md` |

**Remediation (2026-08-13):** earlier engine-only unit left product UI dark under
`signals.target` — incorrect under full-stack doctrine. Wrappers now mirror
Gaius/Metabase (`just up` / full-stack stop).

**Operator:**

```bash
just install-systemd --peers aegir --enable
sudo systemctl restart aegir   # or signals.target
curl -sf http://127.0.0.1:8091/api/health
curl -sf -o /dev/null http://127.0.0.1:5173/
grpcurl -plaintext 127.0.0.1:50151 zndx.engine.v1.Engine/Status
just lattice-ci --require aegir
```

---

### Atelier

| Fact | Value |
|------|--------|
| Role | Referee / CAI; capability engine on lattice |
| Architecture class | **core_federated_engine** |
| Checkout (lab) | `~/local/src/zndx/atelier` |
| Unit sample | [`infra/systemd/atelier.service`](../../../infra/systemd/atelier.service) → wrappers |
| gRPC lattice | **`:50251`** — native + **`zndx.engine.v1.Engine`** + reflection |
| Product servicer | **`:50071`** (workbench; part of full stack) |
| Gateway / Vite UI | **`:8090`** / **`:3000`** |
| Postgres lattice | **`:5533`** |
| Capability / Status | `project=atelier`; **referee** (+ configured caps) |
| Unit process model | **Full devenv** — `capability-engine` + `grpc-server` + gateway + vite |
| Accept | Status `:50251` + `:50071` + gateway + vite |
| Product SoR | Atelier `docs/current/src/operations/peer-unit.md` |
| Session checklist | [peer-unit-spec — atelier](./peer-unit-spec.md#filled-atelier) |

**Remediation (2026-08-13):** engine-only unit was an oversight; both lattice
and product UI belong under the unit.

**Operator:**

```bash
just install-systemd --peers atelier --enable
sudo systemctl restart atelier
curl -sf -o /dev/null http://127.0.0.1:3000/
grpcurl -plaintext 127.0.0.1:50251 zndx.engine.v1.Engine/Status
just lattice-ci --require atelier
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
