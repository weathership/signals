# signals-federation Zarf — live deploy notes

**Package:** `/raid/signals/zarf-build/zarf-package-signals-federation-amd64-0.1.0.tar.zst` (Zarf v0.70.1)  
**Cluster:** tinybox RKE2 — Knative + Kourier + YuniKorn + minifi-sentinel ksvc  
**Converge:** `python3 -m converge verify` → **11/11 OK**

## Fixes required for bare-metal air-gap

1. **linux/amd64 digests** — Zarf rejects multi-arch OCI indexes (Knative release digests).
2. **serving-core CRDs stripped** — upstream core embeds CRDs; separate `serving-crds` component would double-own Helm releases.
3. **No separate config-network / config-autoscaler charts** — already in serving-core; use onDeploy patches.
4. **Kourier Service = NodePort** — LoadBalancer EXTERNAL-IP pending hangs Helm health forever.
5. **Retag digests after push** — digest-only registry entries; agent/Helm want tags (`scripts/retag-registry-tags.sh`).
6. **ksvc image by digest** — Knative controller cannot resolve tags via `127.0.0.1:31999` from inside pods.

## Live state (session)

- `knative-serving`: activator, autoscaler, controller, webhook, net-kourier — Running
- `kourier-system`: 3scale-kourier-gateway — Running
- `yunikorn`: scheduler + admission — Running
- `federation-signals/minifi-sentinel` ksvc Ready (health :8080 wrapper)
- `enable-scale-to-zero=true`

## Init skew

Cluster `zarf package list` still shows **init v0.66.0** while CLI/package are **v0.70.1**. App package deploy succeeded; re-init to 0.70.1 when convenient.
