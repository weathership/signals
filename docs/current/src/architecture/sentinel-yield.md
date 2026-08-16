# Sentinel Applications and Yield

A MiNiFi C++ sentinel **is** the YuniKorn Application: 1:1 with a schedulable
process. signals-ui Applications lists only what YK admitted.

## Closed loop

```text
YK ends Application  →  last-gasp / heartbeat (C2 HTTP)
                     →  Signals C2
                     →  gRPC zndx.engine.v1.Engine/Yield
                     →  owning engine ends the local process
```

Two wires on the C2 process: **HTTP** toward sentinels; **gRPC Yield** toward
the lattice engine from `peer-contract.json`. Sentinels never dial gRPC.

| Reason | When |
|--------|------|
| `PREEMPTED` | YK / kubelet ended the sentinel |
| `COMPLETED` | work finished |
| `ORPHAN` | missed heartbeat (SIGKILL / node loss fallback) |
| `UNIT_STOP` | peer-scoped unit stop |

Unknown `workload_id` is idempotent (`ok=true`, `process_ended=false`).

## Resource claim

The Application’s resource vector **is** the claim. GPU work asks for
`federation.zndx.org/gpu` on the sentinel (or on an in-cluster pod). That is
how YK sees occupancy and how preemption frees a card. CUDA still runs on the
host engine unless the work is an in-cluster GPU pod (`nvidia.com/gpu` **and**
the federation token). Do not request `nvidia.com/gpu` on a CPU-only MiNiFi
container.

Queue path is the resource class (`root.internal.inference.extract`,
`root.internal.compute`, …), not `root.{project}`. Project stays on
`federation.project` for C2 and Yield.

Platform warehouse upkeep (`data-product.tier-upkeep`) uses a **flow-level
proxy sentinel** on `root.platform` (`signals-dataproduct-tier-upkeep`)
when the Metaflow run is not itself a YK Application. A `@kubernetes`
step is an Application — same `app-id` / `workload_id`.

## What this cut is not

- NiFi proper / canvas (optional later K8s fielding for OTel wiring; not
  signals-ui)
- Per-engine C2 servers
- Gaius/Aegir/Atelier `Yield` bodies (they implement the same RPC; Gaius
  maps onto `CompleteWorkload` / restore)
- Moving host vLLM into the sentinel container

## Unit

`signals-c2.service` is foundation (with the engine): `signals.target` Wants it;
it `After=` `signals-engine.service`. Start/stop wrappers:
`scripts/systemd_c2_{start,stop}.sh`.

```bash
sudo systemctl start signals-c2.service   # or: start signals.target
curl -sf http://127.0.0.1:50561/healthz
```

`just signals-ready` records C2 as WARN until the unit is up (C2 starts after ready).

## Lab

```bash
# engine on :50551, control :50552, C2 :50561
just sentinel-yield-lab
```

Protocol: `components/signals-protocol` `Engine/Yield`.
Ops design: `specification/operations/minifi_sentinels.md`.
