# RKE2 lock-in: YuniKorn + Knative (signals-federation)

**When:** 2026-08-10  
**Cluster:** tinybox RKE2 (`192.168.1.55`), `KUBECONFIG` → rke2.yaml  
**Package:** `signals-federation` 0.1.0 already installed via Zarf

## Actions

1. `./zarf/federation/scripts/teardown-precedence.sh` — deleted `aegir-metaflow` + residual metaflow svc in `default`
2. First purge **raced** with Aegir Tilt (`app.kubernetes.io/managed-by: tilt` on Metaflow) — ns recreated with ImagePullBackOff
3. Operator ran `devenv processes down` in **aegir** → Tilt stop; second purge stuck
4. `helm uninstall argo-workflows -n default` — orphan release (no pods; CRDs kept by resource policy)
5. `python3 -m converge verify` → **11/11 OK**

## Locked surface (app namespaces)

| Namespace | Role |
|-----------|------|
| `yunikorn` | scheduler + admission (REST `:9080`, UI `:9889`) |
| `knative-serving` | controller, activator, autoscaler, webhook, net-kourier |
| `kourier-system` | gateway NodePort 32332/31995 |
| `federation-{aegir,atelier,gaius,hermes,signals,system}` | federation scopes; ksvc in signals |
| `zarf` | init registry (kept) |

**Gone:** `aegir-metaflow`  
**YK smoke:** `http://10.43.111.252:9080/ws/v1/clusters` returns 1.9.0 cluster JSON  
**STZ:** `enable-scale-to-zero=true`; `minifi-sentinel` Ready with 0 running pods  

signals-ui / clients:

```bash
export SIGNALS_YK_API_URL=http://192.168.1.55:9080
# cluster-internal: http://10.43.111.252:9080
```

## UI exposure (LAN + ZT path)

- **NodePort** (durable): web `30889`, REST `30080` on `192.168.1.55`
- **port-forward** `0.0.0.0:9889` + `:9080` via `just yk-ui-forward`
- Smoke: `http://192.168.1.55:9889/` → YuniKorn UI 200
- **ZT gap:** WARP include-mode does not route `192.168.1.0/24`; need private
  network route or cloudflared Access tunnel for off-LAN iPad/laptop

### Stock YK web vs signals-ui

Stock SPA still ships (enabled) with our YK 1.9.x pin and is fine to expose
in lab. Apache YK may ship it disabled in later releases to prefer core
scheduler work — we do not maintain the SPA. **signals-ui** is the primary
control plane; when a future pin disables/drops stock UI, drop the exposure
only.

### devenv: YK required (2026-08-11)

`SIGNALS_UI_ALLOW_NO_YK` is a **failure mode**, not a stack default.
`devenv up` runs `signals:federation-ready` → `scripts/federation_preflight.sh`
before signals-ui (confirm/deploy YK+Knative on RKE2, probe REST).
`SIGNALS_YK_API_URL` default `http://127.0.0.1:30080` in devenv.nix + `.env`.

## Backlog: multi-engine K8s coordination

**Need:** federation-owned coordination so sibling repos (Aegir/Atelier/Gaius/…) do not fight over this node.

- YK queues of record: `root.{default,aegir,atelier,gaius,signals,hermes}` (package values)
- No long-running independent Tilt/Helm against shared RKE2 without queue + resource envelope
- Control-plane visibility (signals-ui) for capacity / who may deploy
- Documented stop order before teardown (aegir `devenv processes down`, etc.)

Documented in:

- `docs/current/src/infrastructure/signals-federation-zarf.md` § Multi-engine K8s coordination
- `zarf/federation/README.md` + `scripts/teardown-precedence.sh` tilt warning

## Soft follow-ups

- Cluster Zarf **init still v0.66.0** vs package/CLI **v0.70.1** — re-init when convenient
- Converge queue deep-check still soft (`T3.queues-federation`)
- Orphan Argo Workflows **CRDs** remain (helm resource-policy); optional hard delete later
