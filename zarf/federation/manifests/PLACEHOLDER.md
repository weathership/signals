# Manifests

| Path | Role |
|------|------|
| `knative/serving-crds.yaml` | Knative Serving CRDs only (install first) |
| `knative/serving-core.yaml` | Controllers/config — **CRDs stripped** so Zarf Helm releases do not double-own CRDs |
| `knative/kourier.yaml` | net-kourier + Envoy |
| `knative/config-network-kourier.yaml` | ingress-class = Kourier |
| `knative/config-autoscaler-scale-to-zero.yaml` | `enable-scale-to-zero=true` |
| `yunikorn/values.yaml` | Helm values: federation queues |
| `namespaces.yaml` | `federation-{system,aegir,atelier,gaius,signals,hermes}` |
| `sentinels/minifi-ksvc-signals.yaml` | Knative Service minifi-sentinel (health :8080 + agent) |

When bumping Knative: re-download CRDs + core, strip CRDs from core with a proper multi-doc YAML parser, re-pin **linux/amd64** image digests (see `BOOTSTRAP_VERSIONS.txt`).
