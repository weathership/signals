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
native service. Lab lattice:

| Peer | Port | Capability (Status) | Unit sample | Notes |
|------|------|---------------------|-------------|--------|
| **Gaius** | **50051** | `cognition` | `gaius.service` | Product engine / federation mesh |
| **Ægir** | **50151** | `instruct` | `aegir.service` | Capability engine (+ native face) |
| **Atelier** | **50251** | `referee` | `atelier.service` | Capability engine; native servicer may be `:50071` on co-tenant hosts |
| Synth | 50351 | `synthesis` | `synth.service` | Optional peer |
| Metabase | 50451 | `dashboard` | `metabase.service` | **Optional AGPL** external |

```bash
grpcurl -plaintext 127.0.0.1:<port> zndx.engine.v1.Engine/Status
just lattice-ci                      # SKIP absent; PASS listening
just lattice-ci --require gaius,aegir,atelier
```

Spec: [signals-protocol](../components/signals-protocol.md) ·
`components/signals-protocol` submodule in each peer tree.

OIP (KServe Open Inference Protocol) is the long-term portable inference face;
`Complete` remains a transitional convenience on many engines.

---

## Common peer unit pattern (learned from Metabase)

Metabase was the first peer to land a **production-shaped** unit. In-org peers
(Gaius, Ægir, Atelier) should copy this pattern, not bare `just up` in the unit
file.

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

4. **Accept = federation face ready**, not “process-compose started”:
   - TCP listen on the **contract gRPC port**
   - `grpcurl … zndx.engine.v1.Engine/Status` succeeds  
   - Optional product health (HTTP `/api/health`, gateway, etc.)

5. **Idempotent start**  
   If accept probes already pass, exit 0 without tearing down a live stack
   (same idea as `scripts/systemd_foundation_start.sh`).

6. **PATH**  
   `Environment=PATH=/usr/local/bin:/usr/bin:/bin:…` so system-wide `just` /
   `grpcurl` work; use `bash -lc` inside wrappers when devenv/direnv is required.

7. **Never bind** Signals `:5455` or RustFS `:9010`.

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
| **Metabase** | Complete (AGPL optional) |
| **Gaius** | Wrappers + unit + `zndx.engine.v1.Engine` face **landed**; **accept open** until live engine recycle binds Status on `:50051` |
| **Ægir / Atelier** | Pattern ready — implement in peer tree |

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
| **lattice-ci** | Elevated CI gate; reflection optional (proto fallback OK) |

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

Ægir instruct / inference peer (product name often styled “Ægir”).

| Fact | Value |
|------|--------|
| Role | Instruct / inference peer; capability→model owned by engine |
| Checkout (lab) | `~/local/src/zndx/aegir` |
| Unit sample | [`infra/systemd/aegir.service`](../../../infra/systemd/aegir.service) |
| gRPC lattice | **`:50151`** — `zndx.engine.v1.Engine` (+ native `aegir.engine`) |
| Postgres lattice | **`:5555`** |
| Capability hint | `instruct` |
| Product lifecycle | `just up` = `devenv up -d` + **stack-health** (gateway `:8091`, vite, …) |
| Engine face | Capability engine may be **separate** from web stack (`just engine-serve` / `engine-ready`) — unit start **must** bring **:50151** Status, not only gateway health |
| Platform Metaflow | Use platform service when scheduling federated jobs; local mode remains for isolated eval |
| YK | RKE2 tasks → queue `root.aegir` (or contract queue names) |
| Peer session focus | [peer-unit-spec — aegir](./peer-unit-spec.md#filled-aegir) |
| Product notes | `Justfile` engine recipes; `components/signals-protocol` |

**Peer session deliverables (in Ægir tree):**

1. `scripts/systemd_start.sh` that ensures **federation face :50151** is ready
   (if `just up` alone does not start the capability engine, chain
   `engine-serve` / supervisor + `engine-ready` or equivalent).
2. `scripts/systemd_stop.sh` that does not kill foreign peers’ GPU leases
   carelessly (respect co-tenancy / lease tooling).
3. Accept: `grpcurl …:50151 …/Status` + optional gateway health if product needs it.
4. Pin signals-protocol submodule; keep OIP / `Complete` mapping current.

**Operator (after peer accept):**

```bash
just install-systemd --peers aegir --enable
sudo systemctl start signals.target
grpcurl -plaintext 127.0.0.1:50151 zndx.engine.v1.Engine/Status
just lattice-ci --require aegir
```

**Caution:** Ægir `just up` stack-health probes **gateway/vite**, not necessarily
the lattice port. A unit that only runs `just up` can be `active` while lattice-ci
still FAILs on `:50151` — fix that in the peer wrappers before enable.

---

### Atelier

| Fact | Value |
|------|--------|
| Role | Referee / CAI; capability engine on lattice |
| Checkout (lab) | `~/local/src/zndx/atelier` |
| Unit sample | [`infra/systemd/atelier.service`](../../../infra/systemd/atelier.service) |
| gRPC lattice | **`:50251`** — capability / `zndx.engine.v1.Engine` |
| Native servicer (devenv co-tenant) | **`:50071`** (`ATELIER_GRPC_PORT`) — product API; **not** the lattice accept port |
| Postgres lattice | **`:5533`** |
| Capability hint | `referee` |
| Product lifecycle | `just up` / devenv (grpc-server, gateway, qdrant, …) |
| Engine face | Capability engine recipes in `justfile` (`:50251`; vLLM children on foreign CUDA env) |
| Peer session focus | [peer-unit-spec — atelier](./peer-unit-spec.md#filled-atelier) |

**Peer session deliverables (in Atelier tree):**

1. Wrappers that wait on **`Engine/Status` at :50251** (lattice), not only
   native `:50071` readiness.
2. Document dual-port layout clearly for operators (servicer vs federation).
3. Align `infra/systemd/atelier.service` sample paths; long `TimeoutStartSec` if
   models load at start.
4. Platform Metaflow/Airflow only when joining federated production paths.

**Operator (after peer accept):**

```bash
just install-systemd --peers atelier --enable
sudo systemctl start signals.target
grpcurl -plaintext 127.0.0.1:50251 zndx.engine.v1.Engine/Status
just lattice-ci --require atelier
```

**Caution:** README defaults sometimes mention gRPC `:50051` (CAI / single-tenant).
On a host co-tenant with Gaius, devenv uses **`:50071`** for the servicer and
**`:50251`** for the capability engine. Lattice CI only cares about **`:50251`**.

---

## External engines: Metabase (AGPL)

Metabase is an **optional** external peer. The core Signals stack does **not**
require it. Install only when you want federated **`dashboard`** capability.

| Fact | Value |
|------|--------|
| License | **AGPL-3.0** (Signals is **Apache-2.0**) |
| Role | External `dashboard` engine (`Status.project=metabase`) |
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
