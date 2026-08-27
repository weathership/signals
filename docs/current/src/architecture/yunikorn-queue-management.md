# YuniKorn queue management (engine-first)

Signals owns **queue configuration and operational control** as a platform
capability. Thin clients never call YuniKorn REST as the product path.

## Architecture

```text
signals-ui · MCP · CLI
        │  gRPC only
        ▼
Signals engine :50551
  zndx.engine.v1.Engine          (Status — capability=scheduler, model=yunikorn)
  zndx.scheduler.v1.Scheduler    (ops + projection; vendor-agnostic)
        │ private HTTP / kube
        ▼
YK REST :30080  ·  ConfigMap apply (promote)   ← lab backend
```

Protocol: `components/signals-protocol` →
[`zndx.scheduler.v1`](../../components/signals-protocol/specification/protocol/scheduler_grpc.md).
YuniKorn is the **lab backend**, not the service name.

Official YK references:

- [Queue config](https://yunikorn.apache.org/docs/user_guide/queue_config/)
- [Scheduler REST](https://yunikorn.apache.org/docs/api/scheduler)

## Projection roots (Aegir-shaped)

Under `build/dev/` (or `SIGNALS_YK_PROJECTION_ROOT`):

| Root | Role |
|------|------|
| **current** | Active policy view + live overlay; regenerable via `SyncProjection` |
| **scratch** | Edit/review pending promote |
| **archive** | Freezes of past applied configs |

## API-symmetric clients

| Client | Entry |
|--------|--------|
| CLI | `signals-yk` / `uv run python -m signals.cli.yk` |
| MCP | `signals-yk-mcp` / `uv run python -m signals.mcp.yk` (stdio JSON-RPC) |
| Web | `/` Scheduler band + `/queues` lineup + `/applications` → engine gRPC (`SIGNALS_ENGINE_TARGET`) via `/api/engine/v1/*` |

### Queues lineup (Aegir geometry)

Full-height shell under chrome:

| Piece | Behavior |
|-------|----------|
| **Side-nav SECTION** | `archive` \| `current` \| `scratch` (same roots as projection) |
| **QUEUES / POLICY / OPS** | Seeds: queue notes, `config/queues`, `ops/diff`, `ops/nodes`, `ops/health`, Sync |
| **Canvas** | Horizontal panels (~33rem), `openFrom(i)` branch, × closes to parent |
| **Trail** | `sessionStorage` per layer; URL holds `?root=&open=&partition=` focus only |
| **Data** | Engine projection notes + virtual notes (declared YAML, nodes, health, diff) |

Legacy `/nodes` and `?panel=nodes` redirect to `/queues?open=ops/nodes`.
```bash
export SIGNALS_ENGINE_TARGET=127.0.0.1:50551
export KUBECONFIG=~/.kube/config   # for promote ConfigMap apply

uv run python -m signals.engine          # server
uv run python -m signals.cli.yk health
uv run python -m signals.cli.yk queues
uv run python -m signals.cli.yk config
uv run python -m signals.cli.yk sync

# policy lifecycle
uv run python -m signals.cli.yk write-scratch path/to/queues.yaml
uv run python -m signals.cli.yk diff --live
uv run python -m signals.cli.yk promote --dry-run
uv run python -m signals.cli.yk promote
uv run python -m signals.cli.yk archives
uv run python -m signals.cli.yk index --root current
```

MCP (engine gRPC only; tools mirror CLI):

```bash
export SIGNALS_ENGINE_TARGET=127.0.0.1:50551
uv run python -m signals.mcp.yk
# tools: yk_health, yk_queues, yk_config, yk_validate, yk_sync,
#        yk_write_scratch, yk_diff, yk_promote, yk_archives, yk_restore, yk_index
```

## Promote

`PromoteScratch` order:

1. Read **scratch** `queues.yaml`
2. Validate via YK `POST /ws/v1/validate-conf` (engine-private)
3. **dry_run**: optional `kubectl apply --dry-run=server` of ConfigMap patch; no projection write
4. **live**: apply ConfigMap → archive **current** → write scratch → current → best-effort `SyncProjection`

### ConfigMap adapter (engine-private)

| Env | Default | Meaning |
|-----|---------|---------|
| `SIGNALS_YK_APPLY_ENABLED` | `1` | Set `0` for local-only promote (no kubectl) |
| `SIGNALS_YK_CM_NAMESPACE` | `yunikorn` | Namespace |
| `SIGNALS_YK_CM_NAME` | `yunikorn-configs` | Primary CM (runtime override) |
| `SIGNALS_YK_CM_FALLBACK` | `yunikorn-defaults` | If primary missing |
| `SIGNALS_YK_CM_KEY` | `queues.yaml` | Data key |
| `KUBECONFIG` / `SIGNALS_YK_KUBECONFIG` | — | kubeconfig path |
| `SIGNALS_YK_KUBE_CONTEXT` | — | optional context |

Lab/RKE2: `yunikorn-configs` overrides `yunikorn-defaults` at runtime (zarf values).
Apply preserves other CM keys (e.g. admission controller flags).

On apply failure, projection is **not** mutated (`applied=false`).

## Resource-class tree

Queue path is **scarcity**, not project. Project stays identity (`federation.project`,
C2, `Engine/Yield`). Aegir / Atelier / Gaius / Signals share the same
`internal.inference.*` leaves.

Canonical policy: [`config/scheduler/federation-queues.yaml`](../../../config/scheduler/federation-queues.yaml).
Catalog prose: [`config/scheduler/resource-classes.md`](../../../config/scheduler/resource-classes.md).

```text
root.default                         leftover / unannotated (no GPU)
root.platform                        Metaflow, Airflow, Eventing
root.internal.compute                CPU burst / idle sentinels
root.internal.inference.{reasoning,coding,orchestration,instruct,embedding,extract}
root.external.token-metered          peer meters tokens
root.external.rate-metered           peer meters RPM
root.external.subscription.rate-limited   Grok ACP / xAI subscription
```

Placement (without `provided`, annotations are ignored and everything lands on
`root.default`):

```yaml
placementrules:
  - name: provided          # yunikorn.apache.org/queue
    create: false
  - name: fixed
    value: root.default
    create: false
```

**Queue share (WRK occupancy).** Peers send `Scheduler/RequestQueueShare`
(uuidv7 `request_id`, `workloads[]`, `shares[]` guaranteed/max, validity
window). Signals persists the time series, merges overlapping leftover
floors against parent GPU max 6 (`extract=1` vs light/CLT or medium/SAE),
and `PromoteScratch` applies `yunikorn-configs`. Peers never write
`queues.yaml`. Persist failure is `#YK.00000007.SHAREFAIL`.

**Idle occupancy.** Extended **inactivity** on a model (e.g. Qwen3.8) is
Knative KPA scale-to-zero of the **proxy sentinel Application**, then
MiNiFi C2 last-gasp → `Engine/Yield` on the **federated engine that owns
that vLLM**. Tokens (`federation.zndx.org/gpu`) free only when the
Application completes. Knative does not stop host CUDA. Serving /
`loading` keeps `min-scale: 1`. See
[MiNiFi sentinels](../../../components/signals-protocol/specification/operations/minifi_sentinels.md#43-what-drives-idle-for-a-sentinel-service).

GPU occupancy is the Application claim key `federation.zndx.org/gpu`. Advertise
node capacity with `scripts/advertise_federation_gpu.sh`. Host-engine sentinels
request that token only — never `nvidia.com/gpu` on a CPU-only pod (that binds
the card into the empty container). In-cluster CUDA pods request both.

Each leaf carries `properties.federation.*` (`class`, `yk_enforces`,
`peer_meters`, `examples`) so `GetQueueTree` is the discovery SoR. MCP catalog
tools come after this tree is live; protocol `SuggestQueue` later still.

An Application is placed **once**, when its `app-id` is first submitted.
Re-annotating a later pod with the same id does not move it; use a new id or
let the old Application complete. `root.default` holds unannotated leftovers
(including earlier autogen).

Turnkey refresh: `just redeploy` walks the `k8s.product-redeploy` FSM
([IT-ops FSM](./ops-fsm.md)). Probes are Brier-scored forecasts. Completing
still owns the `app-id`; timeout fails the procedure.
YK and Knative substrate apply only when missing or those manifests changed.
Not `signals.target` (host engines).
Not Metabase (host peer). Not a scorched-earth rebuild.

```bash
uv run python -m signals.cli.yk write-scratch config/scheduler/federation-queues.yaml
uv run python -m signals.cli.yk promote --dry-run
uv run python -m signals.cli.yk promote
```
