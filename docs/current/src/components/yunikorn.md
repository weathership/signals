# YuniKorn

Submodule: `components/yunikorn-core` → `git@github.com:rch/asf-yunikorn-core.git`.

## Role in Signals federation

Apache YuniKorn is an **optional admission/scheduling instance** for
**MiNiFi sentinels** on system-wide RKE2—not the sentinel substrate itself.

| Concern | Authority |
|---------|-----------|
| Sentinel agent, C2, overwatch | **MiNiFi C++** (`components/minifi-cpp`) |
| Multi-tenant queues, fair-share, preemption of **claims** | **YuniKorn** (this submodule) |
| Actual GPU/engine work | Host gRPC engines |

See signals-protocol:

`specification/operations/minifi_sentinels.md`
