# Federation resource classes

Queue path is the resource class. Project is identity (`federation.project`,
C2, `Engine/Yield`), not a parent that hoards GPUs.

Live policy: [`federation-queues.yaml`](./federation-queues.yaml). Promote
through the engine (`zndx.scheduler.v1`), never YuniKorn REST from a peer.

GPU occupancy key: `federation.zndx.org/gpu`. Advertise node capacity with
`scripts/advertise_federation_gpu.sh` (lab tinybox = 6).

| Leaf | Use | YK enforces | Peer still meters |
|------|-----|-------------|-------------------|
| `root.default` | Unannotated leftover | cpu/mem/apps | — |
| `root.platform` | Metaflow UI, Airflow, Eventing | cpu/mem/apps | — |
| `root.internal.compute` | CPU burst, idle sentinels, Ambient ticks (cap 8 apps) | cpu/mem/apps | — |
| `root.internal.inference.reasoning` | CoT / long-held chat | cpu/mem/gpu/apps | — |
| `root.internal.inference.coding` | Code models | cpu/mem/gpu/apps | — |
| `root.internal.inference.orchestration` | Planner / tool-router | cpu/mem/gpu/apps | — |
| `root.internal.inference.instruct` | Instruct / short chat | cpu/mem/gpu/apps | — |
| `root.internal.inference.embedding` | Embeddings | cpu/mem/gpu/apps | — |
| `root.internal.inference.heavy` | Standing thinking TP=4 (4 GPUs, 1 app) | cpu/mem/gpu/apps | — |
| `root.internal.inference.medium` | On-demand SAE TP=2 (max 2 GPUs, 1 app, **no guarantee**) | cpu/mem/gpu/apps | — |
| `root.internal.inference.light` | Interactive Ask 1.7B (1 GPU/app, max 2 apps) | cpu/mem/gpu/apps | — |
| `root.internal.inference.extract` | Offline OCR / docling / article-curate (**1 GPU guaranteed**, max 2, 2 apps). YK preempts medium (ask-sae, no floor) when extract work arrives. | cpu/mem/gpu/apps | — |
| `root.internal.inference.agent-rtc` | Hermes WebRTC / Kyutai STT (**1 GPU guaranteed**, 1 app, fenced). Dash is a valid leaf name (`rate-metered`). | cpu/mem/gpu/apps | — |
| `root.external.token-metered` | Pay-per-token APIs | apps (no GPU) | tokens |
| `root.external.rate-metered` | RPM/TPM APIs | apps (no GPU) | rpm |
| `root.external.subscription.rate-limited` | Grok ACP / xAI subscription | apps (no GPU) | subscription |

Do not submit to parent `root.internal.inference` (not a leaf).

Idle vLLM (loaded, not serving) does not release GPUs until the **proxy
sentinel** scale-to-zero last-gasp Yields the owning federated engine.
YK still only sees the Application token.

## Application stamps

```yaml
metadata:
  labels:
    federation.project: gaius          # identity / C2 / Yield
    federation.workload_id: <id>      # shared with C2 and Yield
    federation.resource_class: internal.inference.extract
    applicationId: <id>
    queue: root.internal.inference.extract
  annotations:
    yunikorn.apache.org/app-id: <id>
    yunikorn.apache.org/queue: root.internal.inference.extract
```

Host-engine GPU work requests `federation.zndx.org/gpu` only (never
`nvidia.com/gpu` on a CPU-only sentinel). In-cluster CUDA requests both.

Aegir, Atelier, Gaius, and Signals share the `internal.inference.*` leaves.
There is no `root.gaius` GPU slice.

YuniKorn places an Application **once**, when the `app-id` is first submitted.
Changing `yunikorn.apache.org/queue` on a later pod with the same id does not
move it. Use a new `app-id` (or let the old Application complete) to land on a
new leaf. Autogen leftovers stay on `root.default` until re-submitted.

`just redeploy` completes Signals-owned product Applications and resubmits
them. Host peers (Gaius, Metabase, …) stay on `signals.target`.
