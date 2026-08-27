# Airflow UI check + preflight loop fix (2026-08-26)

Context: Signals owns platform Metaflow + Airflow. Goal: Airflow UI available the way
Marquez-web is, as the first step toward a top-down schedule view (Metaflow DAGs +
federated pg_cron clocks mirrored into central Airflow).

## State found

| Surface | State |
|---------|-------|
| Airflow 3.1.7 (helm `airflow` rev 12, ns `airflow`) | api-server / scheduler / dag-processor / triggerer all 1/1 |
| UI / REST | `http://127.0.0.1:30800` — React SPA, FAB login admin/admin, `POST /auth/token` → JWT OK |
| `/api/v2/monitor/health` | metadatabase, scheduler, triggerer, dag_processor all healthy |
| DAGs | `signals_ci`, `signals_eventing_ci` (paused), `signals_smoke`, `signals_eventing_smoke`; 0 import errors; last runs 08-12 |
| Metaflow metadata 2.5.0 (ns `metaflow`) | `:30180/ping` → pong |
| Marquez-web / Atlas | `:21011` / `:21010` up |
| signals-ui `:9889` | **down** — restart loop (76 iterations since 23:41) |

`gpu_metrics_settle_dag.py` (added 08-25) is in the repo but not in the DAG ConfigMap; it
imports `signals.ops.gpu_metrics_settle`, which the stock `apache/airflow:3.1.7` image
does not carry, so mounting it would only produce an import error. Left unmounted.

## Root cause of the churn

`processes.signals-ui` runs `scripts/signals_stack_preflight.sh` on every start. The
process-compose daemon (and this login session) carry
`KUBECONFIG=/etc/rancher/rke2/rke2.yaml` — root-only `0600`. The preflight's Eventing gate
used `${KUBECONFIG:-~/.kube/rke2.yaml}` verbatim, so **every kubectl in the gate failed
silently and the Broker could never be seen as Ready**, before *and* after bootstrap.
`signals_ready.sh`, `federation_preflight.sh` and `knative_eventing_bootstrap.sh` all pick a
*readable* kubeconfig (`-r` test → `~/.kube/rke2.yaml`), which is why the bootstrap it
launched kept reporting success while the gate kept failing — an unwinnable loop:
`die` → signals-ui exit → restart → same again. And the bootstrap it ran each time:

1. `kubectl delete pods --all --force` in `knative-eventing` on **every** run (rolled the
   whole eventing control plane → Broker flips not-Ready again);
2. `rollout restart` of the Airflow dag-processor on every run, even when the DAG
   ConfigMap was `unchanged` (Deployment generation reached **3178**; a new RS every ~65s).

Self-sustaining, and it hammered an already loaded node (load ≈ 16 from vLLM workers;
root FS 97% → ephemeral-storage evictions: 58 dead pods in `airflow`, 10 in `metaflow`,
10 in `signals-events`, 80 in `aegir-metaflow`). Scheduler's 19 restarts were PG "in
recovery mode" after the 23:41 devenv restart (transient).

## Changes

| File | Change |
|------|--------|
| `scripts/signals_stack_preflight.sh` | `pick_kubeconfig()` (readable, same as signals_ready.sh) — the actual fix; plus `eventing_installed()` + `eventing_wait()`: an installed Broker gets `SIGNALS_STACK_EVENTING_WAIT` (120s) to settle before any bootstrap, and the post-bootstrap check waits too |
| `scripts/knative_eventing_bootstrap.sh` | replace only Zarf-rewritten pods (`:31999/` images) instead of `delete pods --all`; restart dag-processor only when the CM apply is not `unchanged` |
| `scripts/airflow_platform_bootstrap.sh` | DAG ConfigMap includes the eventing DAG files when present (values-signals.yaml subPath-mounts them; a missing key strands the dag-processor in ContainerCreating) |
| `devenv.nix` | shell summary lists Airflow 3 UI `:30800` and Metaflow `:30180` next to Marquez |
| `Justfile` | `just airflow-ui` — URL + `/monitor/health`; `OPEN=1` opens a browser |
| `docs/…/operations/devenv.md`, `docs/…/components/airflow.md` | port row, UI section, direction (top-down schedule view), stability note |

Scripts were replaced atomically (tmp + rename) so the in-flight preflight kept its old text;
the next signals-ui restart reads the new gate.

## Not done (needs a human decision)

- Dead pod records: `kubectl -n <ns> delete pods --field-selector=status.phase=Failed`
  (and `=Succeeded`) for `airflow`, `metaflow`, `signals-events` — blocked by the session's
  command classifier; harmless either way.
- Root FS at 97% (30 GiB free; kubelet evicts under 10 GiB). Something needs pruning
  (`crictl rmi --prune`, old builds, caches) or the evictions will recur.
- `aegir-metaflow` `metaflow-ui` is in `Init:ImagePullBackOff` (missing `private-registry`
  pull secret) — Aegir's, noted only.

## Verification (01:14 UTC)

- Iteration 81 of the signals-ui process — first with both fixes on disk — printed
  `=== Knative Eventing … (KUBECONFIG=/home/rch/.kube/rke2.yaml)` →
  `OK  Knative Eventing Broker signals-events/default Ready` → `Starting signals-ui`.
- `curl :9889/readyz` → 200 (`ready: true`, scheduler_ready, yk_configured); loop stopped (81 iterations).
- `airflow-dag-processor` generation flat at 3181 (was +1 per ~65s); knative-eventing pods
  6 min old and climbing; last bootstrap run logged `configmap/signals-airflow-dags unchanged`
  and no `restarted`.
- `just signals-ready` → READY; `just airflow-ui` → health all healthy.

## Follow-up (same session)

- Dead pod records deleted: 192 Failed cluster-wide + 10 Succeeded in `airflow`/`metaflow`/`signals-events`.
  `airflow` 5 Running, `metaflow` 1, `signals-events` 1. `aegir-metaflow` keeps 5 pending
  (`ImagePullBackOff`, missing `private-registry` secret) — may be wound down.
- **Python is devenv's**: new `scripts/signals_python.sh` (`signals_python_path` / `signals_py`);
  `signals_ready.sh`, `systemd_engine_start.sh`, `systemd_c2_start.sh` and the
  `atlas_frontier_bench` recipe no longer fall back to host `python3`. `just signals-ready`
  now reports `signals-engine PASS`.

## Image delivery — proposal (for the Airflow / Metaflow runtime image)

Need: a `signals` runtime importable inside Airflow (`gpu_metrics_settle` DAG →
`signals.ops`) and inside KubernetesPodOperator / Metaflow task pods, built from the
**same `uv.lock`** devenv uses, delivered air-gap via the existing Zarf registry
(`zarf-docker-registry`, NodePort 31999, already in-cluster; `zarf.dev/agent: ignore` on
the Airflow ns exists only because we never published our own image there).

Facts that shape it (checked 2026-08-26): devenv **2.1.0** — `containers.*` builds
from-scratch Nix images via nix2container (`copyToRoot`, `startupCommand`, `entrypoint`,
`maxLayers`; **no `fromImage`**) and `devenv container copy` pushes with skopeo;
`outputs` exposes arbitrary derivations (`devenv build outputs.<x>`); nix2container is a
devenv input already. Tools present: `zarf` 0.70.1, `nix`; no skopeo/crane/tekton on host.

Recommended shape — devenv builds, Zarf delivers, no new controller:

1. **One closure, two images.** `outputs.signals-runtime` = Nix closure of python312 +
   the uv-locked venv (uv2nix/pyproject.nix from `uv.lock`, or `uv sync --frozen` in a
   fixed-output derivation) + `src/signals`. Image A `signals-runtime` (from scratch,
   `containers.signals-runtime` — devenv handles it directly) for Metaflow/KPO task pods.
   Image B `airflow-signals` = **stock `apache/airflow:3.1.7` + the same closure layered
   at `/opt/signals`** via nix2container `buildImage { fromImage = pullImage …; layers = [ closure ] }`
   under `outputs.images.airflow` (devenv `containers` can't do `fromImage`; the module's
   own nix2container input can). DAGs call the closure with **`ExternalPythonOperator`
   (`python=/opt/signals/venv/bin/python`)** so Airflow's interpreter and ours never share
   site-packages — no dependency negotiation with Airflow's constraints, and
   `PythonOperator` imports of `signals.*` stop being an image-coupling problem.
2. **Delivery = Zarf.** Add both images to `zarf/federation/zarf.yaml` (by digest, as the
   Knative images are), `zarf package create` as today → registry `:31999`; chart values
   `images.airflow.repository` → the Zarf-rewritten ref, and drop `zarf.dev/agent: ignore`
   on the Airflow ns/pods. Peers get the images with the federation package, same as YK/Knative.
3. **Tekton only if a build has to happen off-host.** On tinybox the build is `nix build`
   from devenv, which is already reproducible; a Tekton pipeline would be a pod running the
   same `devenv build` with a Nix cache mount. Worth it when there is a build farm or
   builds must be event-driven in-cluster (git push → Tekton → push); until then
   `just image-build` / `just image-push` (devenv tasks) + a `*-ci` gate that builds and
   diffs the image digest in `signals_ci` is enough and one fewer controller on a loaded node.
4. Versioning: tag = `signals-0.1.0+g<sha>` and always also the digest; Airflow chart pins
   the digest so `helm upgrade` is a real rollout only when the closure changed.
