# signals-federation Zarf package

Dedicated air-gap control-plane package for federation sentinels on RKE2.

| | |
|--|--|
| Path | `zarf/federation/` |
| Package name | `signals-federation` |
| Version | `0.1.0` |
| Zarf | **v0.70.1** |
| Spec | [minifi_sentinels.md](../../components/signals-protocol/specification/operations/minifi_sentinels.md) |

## Why dedicated

Knative / YuniKorn / MiNiFi lifecycle is **not** owned by `cybersec-dask` or the
legacy `zarf/zarf.yaml` `signals-360` scaffold. This package **takes
precedence**: residual cybersec app namespaces can be removed with
`zarf/federation/scripts/teardown-precedence.sh`. Cybersec later adopts these
standards rather than the reverse.

## Ships

1. Knative Serving (CRDs → controllers, Kourier, KPA `enable-scale-to-zero`)  
2. YuniKorn 1.9.0 (queues `root.{project}`)  
3. MiNiFi C++ sentinel Knative Service (`federation-signals/minifi-sentinel`)  

**Does not ship:** host gRPC engines, Dask, Jupyter, Panel-Viz.

## Images (linux/amd64 digests)

Zarf rejects multi-arch OCI **indexes**. Knative release digests in upstream
YAML are indexes — pin **platform** digests in `zarf.yaml` and manifests
(recorded in `BOOTSTRAP_VERSIONS.txt`). Rebuild:

```bash
cd zarf/federation
# re-resolve if versions change:
# podman manifest inspect <ref>  → digests[].platform.architecture=amd64
zarf package create . --confirm --output /raid/signals/zarf-build
```

## Deploy

```bash
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/rke2.yaml}"
# optional clean slate for cybersec apps
./zarf/federation/scripts/teardown-precedence.sh

zarf package deploy \
  /raid/signals/zarf-build/zarf-package-signals-federation-amd64-0.1.0.tar.zst \
  --confirm

cd zarf/federation && python3 -m converge verify
```

## Converge FSM

`zarf/federation/converge/` — Layer A/B catalog with live kubectl detects:

| Tier | Invariants |
|------|------------|
| T0 | node Ready, zarf ns |
| T2 | Knative CRDs, controllers, scale-to-zero CM |
| T3 | YuniKorn Ready, federation queues |
| T4 | ksvc present, STZ posture |
| T5 | C2 path packaged, OTel schema (collector TBD) |

```bash
cd zarf/federation && python3 -m converge list
python3 -m converge verify
```

## Scale-to-zero

`config-autoscaler` sets `enable-scale-to-zero=true`. Sentinel ksvc uses
`min-scale: "0"`. Idle revisions should drop to **0 pods** after the grace
period; activator wakes them on request.

## Multi-engine K8s coordination (soon)

RKE2 on the lab node is **scarce shared compute**. Multiple sibling repos
(Aegir, Atelier, Gaius, cybersec, Hermes, …) currently reach the same cluster
via independent Tilt / Helm / ad-hoc apply paths. That collides with
federation ownership:

| Failure mode | Example observed |
|--------------|------------------|
| Redeploy thrash | Aegir Tilt (`infra/tilt/`) recreated `aegir-metaflow` after `teardown-precedence.sh` |
| Image-pull noise | Metaflow images rewritten by Zarf agent to missing registry digests |
| Queue bypass | Workloads not submitted under `root.{aegir,atelier,gaius,signals,hermes}` |
| Scheduler conflict | Default kube-scheduler vs YuniKorn admission for capacity |

**Direction (federation-owned):**

1. **YuniKorn is the scheduler of record** for all federation and engine
   workloads on this RKE2 instance — queues already declared in package
   values (`root.default` + per-engine leaves).
2. **No long-running out-of-band Tilt** against shared namespaces without an
   explicit engine queue + resource request/limit that YK can enforce.
3. **Engine admission via sentinels / package surface** — host gRPC engines
   stay off-cluster; anything that *does* land on K8s goes through
   `signals-federation` (or a later per-engine Zarf component) so teardown
   and converge FSM remain authoritative.
4. **Coordination API (TBD)** — signals control plane (signals-ui + protocol)
   should expose queue/capacity and “who may deploy what” so sibling devenvs
   do not fight for the same node.

Until that lands: stop engine-local process-compose / Tilt that targets RKE2
before federation teardown or redeploy (`devenv processes down` in Aegir, etc.).

## See also

- [zarf.md](./zarf.md) (legacy notes)  
- [minifi-cpp component](../components/minifi-cpp.md)  
- Package README: `zarf/federation/README.md`  
