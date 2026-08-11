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

**Primary surface is always `signals-ui`.** Stock YuniKorn web is secondary.

As an Apache project, YuniKorn prioritizes **core scheduler features**. The
bundled SPA (scheduler `:9889`, same-origin `/ws/v1`) may still ship with a
given release, or ship **disabled**, by upstream preference—not something
Signals owns or maintains. We do **not** deploy a separate `yunikorn-web`
chart or invest in Angular yk-web ourselves.

While our pinned YK version still includes and enables the stock UI,
**keeping it available is fine** (lab NodePort / `just yk-ui-forward`). When
we move to a YK release that ships it disabled (or without it), we simply
stop exposing it — no Signals feature depends on the stock SPA.

| Piece | Role |
|-------|------|
| **`signals-ui`** | **Primary** backplane — strict **superset** of yk-web capabilities |
| Repo | `git@github.com:weathership/signals-ui.git` |
| Submodule | `components/signals-ui` |
| Stack | **Rust / Axum** (no Node); Keiretsu + Cloudera logo (Atelier continuity) |
| YK | **Required** once the stack lands (`SIGNALS_YK_API_URL`) |
| YK API | Full `/ws/v1/*` surface used by yk-web (contract-tested) |
| Value-add | Sentinels, OTel, Atlas OL lineage, engine discovery |
| Stock YK web | Optional while upstream still embeds it; not a product dependency |

Marquez-web remains an OL **validation** UI only; operators should prefer
**signals-ui** for day-to-day control-plane work.

### Lab exposure (tinybox RKE2)

| Path | URL |
|------|-----|
| LAN classic (`just yk-ui-forward`) | `http://192.168.1.55:9889/` |
| LAN NodePort (durable) | `http://192.168.1.55:30889/` |
| REST | `http://127.0.0.1:30080/` (NodePort; also LAN `:30080`) |
| Recipes | `just yk-ui-forward` / `just yk-ui-forward-stop` |
| **signals-ui YK URL** | `SIGNALS_YK_API_URL` — **required**; devenv default `http://127.0.0.1:30080` |

**Stack path:** `devenv up` runs task `signals:federation-ready`
(`scripts/federation_preflight.sh`) **before** `signals-ui`. That confirms
(and if needed deploys) **YuniKorn + Knative** on the local RKE2 instance and
probes YK REST. signals-ui **does not start** without a live scheduler —
`SIGNALS_UI_ALLOW_NO_YK` is a hermetic-test escape only, never set by devenv.

```bash
just federation-ready          # same preflight
devenv tasks run signals:federation-ready
```

**Zero Trust:** this host’s WARP client is include-mode for Cloudflare CGNAT
only — it does **not** publish the lab LAN. For iPad/laptop off-LAN:

1. Zero Trust **private network** route for `192.168.1.0/24` (or the node IP)
   via a connector on this host, **or**
2. **cloudflared** named tunnel + Access application →
   `http://127.0.0.1:9889` (`cloudflared tunnel login` first).

Until either is configured, use the **LAN** URLs on the same Wi‑Fi/subnet.

- Plan: [Signals Control Plane UI](../architecture/signals-control-plane-ui.md)
- Capability reference only: `~/local/src/asf/rch-yunikorn-web/`
