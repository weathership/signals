# Federation package scripts

Keep helpers **namespace-scoped** to federation / knative / yunikorn.

| Script (planned) | Purpose |
|------------------|---------|
| `clear-failed-noise.sh` | Optional: remove known-bad ns (e.g. failed ImagePull) **not** owned by cybersec-dask |
| `zarf-federation-clean-slate.sh` | Tear down **only** signals-federation Layer B (never cybersec-dask) |

Do **not** copy cybersec `zarf-clean-slate.sh` wholesale without filtering
namespaces — that would wipe the cyberphy surface on this node.
