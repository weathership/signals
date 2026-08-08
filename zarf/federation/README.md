# signals-federation (Zarf package)

**Dedicated** air-gap package for federation **control plane** on RKE2:

| Ships | Does not ship |
|-------|----------------|
| Knative Serving (KPA scale-to-zero) | Host gRPC engines (Ægir/Atelier/Gaius) |
| YuniKorn (admission / queues) | cybersec-dask / Jupyter / Panel |
| MiNiFi C++ sentinel images + Knative Services | Full NiFi cluster (optional later) |

**Lifecycle is independent of `cybersec-dask`.** That package will later defer
to and adopt these standards; do not merge the two packages.

| Spec | Location |
|------|----------|
| Sentinel design | `components/signals-protocol/specification/operations/minifi_sentinels.md` |
| Identity | `…/kerberos_and_secretspec.md` |
| Converge FSM pattern | cybersec `zarf/converge/` (Layer A/B) — port here under `converge/` |

## Package identity

| Field | Value |
|-------|--------|
| Zarf name | `signals-federation` |
| Version | see `zarf.yaml` `metadata.version` |
| Architecture | `amd64` |

**Air-gap rule (cybersec-hard-won):** Zarf **binary**, **init** tarball, and
**this package** must share the **same Zarf major/minor** (pin in
`BOOTSTRAP_VERSIONS.txt` when frozen).

## Layout

```text
zarf/federation/
  zarf.yaml                 # package definition
  BOOTSTRAP_VERSIONS.txt    # zarf + component version pins (fill as frozen)
  README.md                 # this file
  charts/                   # vendored Helm charts (YK, etc.) — gitignored tgz OK
  images/                   # Dockerfiles / build notes for minifi-sentinel
  manifests/                # CRDs, queues, Knative Services, namespaces
  converge/                 # FSM: detect → remediate → fixpoint (stdlib Python)
  scripts/                  # clean-slate helpers that only touch federation ns
```

Legacy `zarf/zarf.yaml` (`signals-360` Dask/engine scaffold) is **not** this
package. Prefer `signals-federation` for all new K8s control-plane work.

## Build / deploy (skeleton)

```bash
# After images/charts are vendored and online once (or from mirror):
cd zarf/federation
zarf package create . --confirm
# → zarf-package-signals-federation-amd64-<ver>.tar.zst

# Air-gap node (Zarf already inited or converge T0–T1):
zarf package deploy zarf-package-signals-federation-amd64-*.tar.zst --confirm

# Converge (when engine is filled out):
python3 -m converge apply    # from zarf/federation with PYTHONPATH=.
python3 -m converge verify
```

## Component order (binding)

1. `knative-crds`  
2. `knative-serving` (`enable-scale-to-zero: true`, KPA)  
3. `yunikorn` (queues `root.{project}`)  
4. `minifi-sentinel-images`  
5. `minifi-sentinel-ksvc` (Knative Services)  

Host engines remain outside this package; they are gated by sentinel
admission per the protocol.

## Coexistence with cybersec-dask

Same RKE2 node may run both packages. **Namespaces must not collide.**
Federation uses e.g. `knative-serving`, `yunikorn`, `federation-*`.
Cybersec keeps `dask`, `jupyterhub`, `panel-viz`. Shared **Zarf registry**
is fine; watch disk (registry PVC size).
