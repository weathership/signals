# signals-federation (Zarf package)

**Dedicated** air-gap package for federation **control plane** on RKE2.
**Takes precedence** over any residual `cybersec-dask` app surface (remove with
`scripts/teardown-precedence.sh` before first deploy if needed).

| Ships | Does not ship |
|-------|----------------|
| Knative Serving (KPA scale-to-zero) | Host gRPC engines (Ægir/Atelier/Gaius) |
| YuniKorn (admission / queues) | cybersec-dask / Jupyter / Panel |
| MiNiFi C++ sentinel images + Knative Services | Full NiFi cluster (optional later) |

| Spec | Location |
|------|----------|
| Sentinel design | `components/signals-protocol/specification/operations/minifi_sentinels.md` |
| Identity | `…/kerberos_and_secretspec.md` |
| Converge FSM | `zarf/federation/converge/` (Layer A/B, live kubectl detects) |

## Package identity

| Field | Value |
|-------|--------|
| Zarf name | `signals-federation` |
| Version | `0.1.0` (`zarf.yaml`) |
| Architecture | `amd64` |
| Zarf CLI / package | **v0.70.1** (pin in `BOOTSTRAP_VERSIONS.txt`) |

**Air-gap rule:** Zarf **binary**, **init** tarball, and **this package** should
share the same Zarf minor (prefer re-init to v0.70.1 if cluster still has
older `init`).

**Images:** Knative multi-arch OCI indexes are unsupported by Zarf — all images
are pinned to **linux/amd64** digests (see `BOOTSTRAP_VERSIONS.txt`).

## Layout

```text
zarf/federation/
  zarf.yaml
  BOOTSTRAP_VERSIONS.txt
  charts/yunikorn-1.9.0.tgz
  images/                   # optional custom sentinel Dockerfile
  manifests/
    knative/                # CRDs, core, kourier, STZ config
    yunikorn/values.yaml
    namespaces.yaml
    sentinels/minifi-ksvc-signals.yaml
  converge/                 # python3 -m converge list|verify
  scripts/teardown-precedence.sh
```

## Build / deploy

```bash
# Prefer /raid for package output (root disk is tight)
cd zarf/federation
zarf package create . --confirm --output /raid/signals/zarf-build
# → /raid/signals/zarf-build/zarf-package-signals-federation-amd64-0.1.0.tar.zst

# Optional: clear cybersec app namespaces (keeps zarf registry)
./scripts/teardown-precedence.sh

# Deploy (cluster must have zarf init + Ready node)
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/rke2.yaml}"
zarf package deploy /raid/signals/zarf-build/zarf-package-signals-federation-amd64-0.1.0.tar.zst --confirm

# Verify
cd zarf/federation && python3 -m converge verify
```

## Component order (binding)

1. `federation-images` — closed air-gap image set  
2. `knative-crds`  
3. `knative-serving` (core + Kourier + `enable-scale-to-zero: true`)  
4. `yunikorn` (queues `root.{aegir,atelier,gaius,signals,hermes}`)  
5. `minifi-sentinel-ksvc` (namespaces + Knative Service)

Host engines remain outside this package; they are gated by sentinel
admission per the protocol.

## Precedence vs cybersec-dask

Federation **owns** Knative / YuniKorn / MiNiFi on this node. Cybersec app
namespaces (`dask`, `jupyterhub`, `panel-viz`, …) may be removed. Shared Zarf
registry (`ns/zarf`) is kept unless `--full-zarf`.
