# Applications as federated occupancy (options only)

Not implemented. Consideration for representing Gaius/Atelier/Aegir GPU
work on Applications, with docling as the first YK-queued example.

## Why the page is empty of meaning

Applications is yk-web parity: admitted YK apps on a queue. Live work sits
on `root.default` (namespace placement → fixed default). Host engines hold
GPUs via `/tmp/zndx-gpu-leases` (refuse-only). `Status.gpu_ids` is advisory.
YK does not see Aegir/Atelier/Gaius vLLM.

Gaius already evicts **its own** vLLM for docling (`run_flow_with_gpu_management`)
and restores after. That recovery pattern is real and Gaius-local. It cannot
preempt Atelier classification.

## Constraint

YK can only preempt **claims** (pods/apps it admitted). Isolation without
YK seeing both sides is pin-and-hope. Preempt-and-resume requires the
steady-state party to be a claim **and** checkpointable.

## Options (short)

1. **YK-native GPU pods** — `@kubernetes` + `nvidia.com/gpu` on
   `root.gaius.docling` / `root.atelier.classify`. Device plugin required.
   Isolation and preemption work. Host vLLM must leave those GPUs.
2. **Split pin** — burst jobs (docling) on YK; host engines pin disjoint
   GPUs YK cannot allocate. Gives (a) isolation. Does **not** give (b)
   Atelier resume after a docling burst.
3. **Claim shim** — YK admits a placeholder; host engine uses the GPU.
   Preempt = YK kills claim → engine checkpoints (Gaius SIGUSR1 pattern).
   Matches sentinel doctrine (YK admits; host executes).
4. **Signals lease broker** — not YK. Visibility only unless we invent
   a second scheduler. Reject as SoR.

Prefer 2 then 3. Time-slicing is not a substitute (OCR + vLLM on one GPU
is the current collision).

## Applications surface (later)

Correlate one row: YK app · queue · project · capability · GPU ids ·
Metaflow/OTel/OL ids · preemptible · resume-after. Not a second nvidia-smi.

## Amendment: sentinels are Applications

From YK’s view there is one kind. A MiNiFi C++ sentinel **is** the
Application: 1:1 with a schedulable process (engine child, Metaflow step,
ACP agent, docling convert), not a second fleet beside yk-web apps.

The written sentinel spec currently *names* them claims and then forbids
`nvidia.com/gpu` on the sentinel pod (host engines hold GPUs). That is the
false split. If the sentinel is the Application, its resource vector is the
process it represents; preemption of that Application must yield the host
process. Scale-to-zero is the idle form of the same object (min-scale 1
while the GPU is held). UI should not have a Sentinels panel as another
kind. Option 3 is not a dummy pod — it is the sentinel.

## Discovery: Gaius capability scheduler vs sentinel proxy

Gaius already implemented YK *vocabulary* in-process (`workloads.py`,
`BeginWorkload`, makespan CP-SAT, restore plans). It never creates a K8s
object. Metaflow-in-cluster is a real YK Application; a local ACP/GPU agent
is only a Gaius `ActiveWorkload`. signals-ui must not invent a third table.

Keep Gaius as the *local planner* (which endpoint to evict/restore). Gate
exclusive GPU start on a real YK-admitted sentinel Application. OTel =
occupancy truth; C2 = preempt/yield. Sentinel resource vector must account
the claim (not a 50m CPU watcher). Do not put host CUDA inside the sentinel
pod by default — node-local extended resource or exclusive GPU claim bound
to the host process.

Multi-server: stop federating ResourceManagers; place the sentinel on the
node that owns the process. `workload_id` is the shared key
(Gaius ↔ YK app ↔ OTel ↔ C2).

## Engine as C2 server

Each federated engine is the C2 server for the sentinels it created.
MiNiFi C2 is **agent-pull**: heartbeat POST, operations in the response
(default period 30s). YK does not push to the engine.

Preempt path that works: kubelet SIGTERM → sentinel last-gasp heartbeat
(`phase=preempted`) → engine C2 REST → engine ends the 1:1 process.
Heartbeat-timeout-only is too slow for GPUs. Reverse path: engine finishes
→ STOP in next heartbeat → agent exits → YK claim gone.

Peer-scoped: Gaius C2 does not own Aegir agents. Signals is not the C2
server for product engines.

## Headless NiFi as shared C2

Alternative: one in-cluster C2 (NiFi or dedicated `c2-server`) for all
sentinels; processors call engines on `zndx.engine.v1`. C2 stays Apache
e2e; engines do not reimplement heartbeat REST.

Needs a federation **yield** RPC (Complete/Remediate are the wrong verbs).
Preempt path gains a hop: SIGTERM → C2 → processor → Engine.yield.
Peer-scoped unit stop still kills processes locally; NiFi is not the
process owner. Applications still only lists YK. Prefer official C2
protocol ownership over four custom C2 servers; do not require a full
NiFi UI cluster if a C2 server + thin processors suffice.

## Canvas vs headless

Lift Gaius OTLP→NiFi + TriggerMetaflow to a Signals-owned NiFi (C2 +
federation OTel). Runtime can be headless. Canvas is the *authoring /
wiring map* of C2, OTel, and yield processors — not Applications, not
the operator occupancy surface. Same law as yk-web: available, not
primary. Yield↔OTel association stays systems engineering on that
canvas.

## Implemented (2026-08-14)

- `Engine/Yield` in signals-protocol (additive v1).
- Signals engine proof process table + loopback POST `/workloads`.
- `signals-c2` HTTP (`:50561`) last-gasp/heartbeat → gRPC Yield.
- Lab: `just sentinel-yield-lab`. NiFi still independent / not in UI.

## Amendment: resource-class queues (same day)

Occupancy is not a later cut. Policy tree is scarcity
(`root.internal.inference.*`, `root.external.*`, `root.platform`) with
`provided` placement. GPU claim key is `federation.zndx.org/gpu` on the
Application. Host CUDA stays on the engine; do not bind `nvidia.com/gpu`
into a CPU-only sentinel. See `config/scheduler/federation-queues.yaml`.
