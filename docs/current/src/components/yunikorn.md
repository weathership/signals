# YuniKorn

Submodule: `components/yunikorn-core` → `git@github.com:rch/asf-yunikorn-core.git`.

## Role in Signals federation

Apache YuniKorn is the **required admission/scheduling instance** for
**MiNiFi sentinels** on system-wide RKE2—not the sentinel substrate and not the
scale-to-zero controller (that is Knative Serving). Product path is
**K8s-first** (RKE2 + Knative + YK); no permanent no-K8s sentinel mode.

| Concern | Authority |
|---------|-----------|
| Sentinel agent, C2, overwatch | **MiNiFi C++** (`components/minifi-cpp`) |
| Scale sentinel pods **to zero** | **Knative Serving** (KPA) |
| Multi-tenant queues, fair-share, preemption of **claims** | **YuniKorn** (this submodule) |
| Actual GPU/engine work | Host gRPC engines |

See signals-protocol:

`specification/operations/minifi_sentinels.md`

## Web UI

Upstream YuniKorn no longer ships a maintained web UI. Signals will **not**
deploy stock Angular YuniKorn-web.

| Piece | Role |
|-------|------|
| **`signals-ui`** | Product control-plane service — **strict superset** of yk-web capabilities |
| Repo | `git@github.com:weathership/signals-ui.git` |
| Submodule | `components/signals-ui` (when added) |
| Stack | **Idiomatic Rust** service (no Node runtime); Keiretsu + Kumo dark/light |
| YK API | Full `/ws/v1/*` surface used by yk-web (contract-tested) |
| Value-add | Sentinels, OTel, Atlas OL lineage, engine discovery |

- Plan: [Signals Control Plane UI](../architecture/signals-control-plane-ui.md)
- Capability reference only: `~/local/src/asf/rch-yunikorn-web/`
