# YuniKorn

Submodule: `components/yunikorn-core` → `git@github.com:rch/asf-yunikorn-core.git`.

## Role in Signals federation

Apache YuniKorn is the **admission/scheduling instance** for
**MiNiFi sentinels** on system-wide RKE2—not the sentinel substrate and not the
scale-to-zero controller.

| Concern | Authority |
|---------|-----------|
| Sentinel agent, C2, overwatch | **MiNiFi C++** (`components/minifi-cpp`) |
| Scale sentinel pods **to zero** | **Knative Serving** (KPA) |
| Multi-tenant queues, fair-share, preemption of **claims** | **YuniKorn** (this submodule) |
| Actual GPU/engine work | Host gRPC engines |

See signals-protocol:

`specification/operations/minifi_sentinels.md`
