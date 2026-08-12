# Peer integration (federation engines + external services)

How sibling engines and **license-external** services attach to the Signals
foundation without re-hosting the critical plane.

## Two layers

| Layer | What | How peers use it |
|-------|------|------------------|
| **Process / group** | `signals.target` + foundation ready gate | systemd `After=signals-ready.service` |
| **Wire / product** | signals-protocol + platform endpoints | gRPC `zndx.engine.v1.Engine`, Metaflow/Airflow/CE, Atlas |

Machine-readable contract: [`config/platform/peer-contract.json`](../../../config/platform/peer-contract.json).  
Unit samples: [`infra/systemd/`](../../../infra/systemd/).

```text
                    ┌─────────────────────────────┐
                    │     signals.target          │
                    │  (group controller)         │
                    └─────────────┬───────────────┘
                                  │
           ┌──────────────────────┼──────────────────────┐
           ▼                      ▼                      ▼
   signals.service      signals-ready.service     (optional peers)
   just up / down       just signals-ready        After=ready
           │                      │                      │
           ▼                      ▼                      ▼
   critical plane          PASS ⇒ exit 0           aegir · atelier
   PG Kudu Impala          Kudu+Metaflow           gaius · synth
   YK Metaflow AF          critical included       metabase (AGPL ext.)
   Eventing Broker
```

## Foundation lifecycle

```bash
# Manual / CI
just up
just signals-ready          # check-only; exit 0 when critical plane is ready
just down                   # lattice-safe stop

# Group control (after installing infra/systemd samples)
sudo systemctl start signals.target
systemctl list-dependencies signals.target
sudo systemctl stop signals.target
```

**Do not** treat `devenv up -d` returning as “ready.” Peers wait on
`signals-ready` (or the oneshot unit that polls it). Prefer `just down` over bare
`devenv processes down` so Postgres `:5455` is released.

## What peers consume (not re-host)

| Concern | Use platform | Avoid |
|---------|--------------|--------|
| Workflow metadata | Metaflow `:30180` + `config/metaflow/platform.json` | Engine-local Tilt Metaflow as SoR |
| DAG production | Airflow `:30800` | Argo Workflows for Metaflow prod |
| Events | Knative Broker `signals-events/default` | Argo Events |
| Schedule / STZ | YuniKorn + Knative Serving | Unscheduled free-for-all pods |
| Lineage / governance | Atlas OL + tags | Peer Marquez DB |
| Analytic tables | Impala HS2 + Kudu (Kerberos) | Parallel warehouses on `:5455` |
| Object store | RustFS `:9010` | Competing S3 on same ports |

Port lattice (Postgres): cybersec `5438` · gaius `5444` · **signals `5455`** ·
atelier `5533` · aegir `5555` · synth `5566` · metabase engine `5577` ·
system/Metabase app DB may use `5432`.

## signals-protocol engines

Each peer registers **`zndx.engine.v1.Engine`** (federation face) beside any
native service. Lab gRPC lattice:

| Peer | Port | Notes |
|------|------|--------|
| Gaius | 50051 | Cognition / product engine |
| Ægir | 50151 | Instruct / inference peer |
| Atelier | 50251 | Referee / CAI |
| Synth | 50351 | Synthesis |
| Metabase (external) | 50451 | Capability **`dashboard`** |

Discovery: `grpcurl -plaintext 127.0.0.1:<port> zndx.engine.v1.Engine/Status`.  
Spec: [signals-protocol](../components/signals-protocol.md) submodule
`components/signals-protocol`.

OIP (KServe Open Inference Protocol) is the long-term portable inference face;
`Complete` remains a transitional convenience on many engines.

## External engines: Metabase (AGPL)

Metabase is **AGPL-3.0**. Signals is **Apache-2.0**. Those licenses conflict if
Metabase source or binaries are **combined into** the signals distribution.

### Correct integration (process boundary)

| Do | Don't |
|----|--------|
| Keep checkout under `~/local/src/agpl/metabase` (or equivalent AGPL tree) | Add Metabase as a signals submodule / vendored jar |
| Run `metabase.service` with `WorkingDirectory=` on that tree | Ship AGPL sources inside ASL2 containers without a separate legal plan |
| Vendor **only** `signals-protocol` inside the Metabase tree | Copy Metabase FE/BE into `weathership/signals` |
| Advertise via engine `Status` (`capability=dashboard`, non-secret `base_url`) | Put DB passwords on the federation wire |
| Order `After=signals-ready.service` | Start dashboard before Kudu/Metaflow/Airflow are ready |

mbengine (in the Metabase tree) is the gRPC daemon: product HTTP `:3200`,
federation gRPC `:50451`. See that tree’s `README.engine.md`.

### What “leverage signals-federation” means for Metabase

1. **Foundation ready** — Atlas, Impala/Kudu, Metaflow, Airflow, Eventing, YK.
2. **Optional platform Metaflow profile** — same `platform.json` as other peers
   for flows that produce dashboards or CE triggers.
3. **CloudEvents** — e.g. curate-finished → Broker → Airflow CI DAG (extend
   `TYPE_DAG_MAP` when a real Metabase DAG exists).
4. **YK queues** — if Metabase-related K8s work lands on RKE2, use
   `root.<engine>` style queues; do not bypass YuniKorn for production tasks.
5. **No second critical plane** — Metabase’s engine Postgres (`:5577`) and app
   DB (`:5432`) are **local to that product**, not replacements for signals PG.

## Systemd membership

```bash
# Enable only peers that exist on this host
sudo systemctl enable signals.target signals.service signals-ready.service
sudo systemctl enable gaius.service metabase.service   # example subset
sudo systemctl start signals.target
```

- `PartOf=signals.target` — stop/restart of the group propagates.
- `WantedBy=signals.target` — enable/disable controls membership.
- Peers use `Wants=signals-ready.service` (soft): foundation failure does not
  hard-fail peer units; switch to `Requires=` if you need a hard gate.

Details: [infra/systemd/README.md](../../../infra/systemd/README.md).

## Lattice CI (after peers claim ready)

Foundation ready ≠ engines listening. Probe the gRPC lattice from the contract:

```bash
just lattice-ci                      # PASS listening peers; SKIP absent
just lattice-ci --require gaius,metabase
just lattice-ci --all                # every peer in contract must answer Status
just lattice-ci --json
```

This is an elevated **CI** gate (`scripts/lattice_ci.sh`), not a one-off smoke
script and not part of `signals-ready` (critical plane only).

## Shared peer-unit specs

Copy-ready acceptance templates for peer-repo sessions:

→ [Peer unit acceptance spec](./peer-unit-spec.md)

## Install systemd (foundation)

**Prerequisite:** system-wide tools on the host `PATH` used by systemd (not
devenv/nix-only): **`just`**, **`kubectl`**, and **`grpcurl`** (for
`just lattice-ci`). See `infra/systemd/README.md`.

```bash
just install-systemd --enable --start          # foundation target only
just install-systemd --peers gaius,metabase --enable   # install samples; enable when ready
```

Do not enable peer units until that peer’s local unit + Status work is done.

## Checklist for a new peer

1. Own a lattice Postgres port and gRPC engine port (document in peer-contract).
2. Vendor `signals-protocol`; implement `zndx.engine.v1.Engine/Status` (+ OIP path).
3. `After=signals-ready.service`; never bind `:5455` / `:9010`.
4. Point Metaflow at platform profile when joining federation.
5. Publish CE to platform Broker; do not add Argo for production Metaflow.
6. If license ≠ ASL2, keep the tree **external** and integrate only via process + wire.
7. Satisfy [peer-unit-spec](./peer-unit-spec.md) accept criteria; verify with `just lattice-ci --require <id>`.

## Related

- [Critical plane](../architecture/stack-critical-plane.md)
- [Platform Metaflow](../architecture/metaflow-platform.md)
- [signals-protocol](../components/signals-protocol.md)
- [Development environment](./devenv.md)
- [Peer unit acceptance spec](./peer-unit-spec.md)
