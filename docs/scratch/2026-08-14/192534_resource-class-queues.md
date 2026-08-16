# Resource-class YK queues (phase 1)

Replace project-parent leaves (`root.gaius`, `root.signals`, …) with a
scarcity tree. GPU occupancy is the Application claim
(`federation.zndx.org/gpu`), not a later pass. CUDA stays on the host
engine unless the work is an in-cluster GPU pod.

## Landed

- `config/scheduler/federation-queues.yaml` + `resource-classes.md`
- `provided` then `fixed: root.default` (no namespace rule)
- Node token advertise: `scripts/advertise_federation_gpu.sh`
- Submitters: Metaflow → `root.platform`; yield-proof / minifi ksvc →
  `root.internal.compute`; GPU-token proof on `root.internal.inference.extract`
- Hermetic policy tests; doctrine in yunikorn-queue-management, sentinel-yield,
  peer-integration, minifi_sentinels

## Not this cut

- MCP `yk_resource_classes` / `yk_suggest_queue` (phase 2)
- Protocol `SuggestQueue` (phase 3)
- Gaius/Aegir submitter patches (consume the annotation contract)

## Promote

Live: `applied=True archive=20260814T192622Z`. YK tree is resource-class.
`provided` is first. `root.internal.inference` max `federation.zndx.org/gpu=6`.
GPU-token proof Application landed on `root.internal.inference.extract` with
allocated gpu=1 (YK schedulerName). tinybox allocatable token=6.

Metaflow service is Running with `queue=root.platform` on the new pod, but
the YK Application `yunikorn-metaflow-platform` was created earlier on
`root.default` (same app-id). YK does not re-place an existing Application.
Autogen apps stay on default until re-submitted with a new id.

```bash
uv run python -m signals.cli.yk write-scratch config/scheduler/federation-queues.yaml
uv run python -m signals.cli.yk promote --dry-run
uv run python -m signals.cli.yk promote
SIGNALS_FEDERATION_GPU_NODE=tinybox ./scripts/advertise_federation_gpu.sh
```
