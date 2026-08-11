# Platform Metaflow direction

Captured user intent + research (Outerbounds K8s, Metaflow Airflow, event
triggering, Gaius isolation).

Canonical doc: `docs/current/src/architecture/metaflow-platform.md`

## Key decisions

1. **Metaflow is platform-critical** — not only Gaius-local.
2. **Base on Outerbounds K8s shape**, but **`eks_airflow` not `eks_argo`**.
3. **Airflow** for production DAG scheduling (`airflow create` → K8s pods).
4. **Knative Eventing** fills the event-trigger role stock Metaflow ties to
   **Argo Events** (Metaflow docs: event triggering is Argo-only today;
   Airflow path is `@schedule` only). Gaius already proved product triggering
   without Argo; platform formalizes that with Eventing → Airflow DAG runs.
5. **YuniKorn** schedules Metaflow task pods + Airflow workers; **RustFS** is
   S3 datastore; **shared PG** for metadata service.
6. Engine isolation (Gaius Tilt/PG) remains valid for solo devenv.

## Submodule

`components/metaflow` → `git@github.com:weathership/oss-metaflow.git` **`rch/devenv`**
(created from `master` @ dc39ff0 and pushed). Scope: Signals platform only —
no Gaius/Marquez edits from this tree.

## Next eng slice

M1: platform metadata service + RustFS bucket + config profile on RKE2;
patches on `rch/devenv` as needed.
