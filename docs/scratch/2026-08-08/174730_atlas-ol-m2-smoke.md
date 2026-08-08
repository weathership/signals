# Atlas OpenLineage M2 — live smoke

**Date:** 2026-08-08

## Shipped

| Repo | Commit | Notes |
|------|--------|-------|
| signals `trunk` | pin `components/atlas` | submodule → `38cb9822c` |
| atlas `rch/signals` | `38cb9822c` | OpenLineageServlet on `/api/v1/*` |

## Why servlet (not Jersey)

Atlas `LineageResource` is `@Path("lineage")`. SpringServlet registers every
`@Path` bean on **every** mapping of that servlet, so sharing `jersey-servlet`
for `/api/v1/*` made `POST/GET /api/v1/lineage` hit Atlas lineage (WADL only
showed `{guid}/inputs/graph` etc.; TerminatingRule → 500).

`OpenLineageServlet` owns `/api/v1/*` exclusively; governance stays on
`/api/atlas/*`.

## Live smoke (Atlas :21010)

```
GET  /api/v1/health                     → 200 {"status":"ok","surface":"openlineage-marquez-v1"}
POST /api/v1/lineage                    → 201 RunEvent receipt
GET  /api/v1/namespaces                 → signals.lab
GET  /api/v1/namespaces/.../jobs|runs   → demo.etl_customers + run
GET  /api/v1/namespaces/kudu/datasets   → raw/curated.customers
GET  /api/v1/lineage?nodeId=job:...     → bipartite graph
public.lineage_events                   → row present
AGE graph signals_ol                    → Job/Run/Dataset labels
```

Marquez-web proxy (setupProxy → Atlas): verified on `:3001` (lab `:3000`
occupied by atelier Vite). `GET /api/v1/health` + `/namespaces` via UI host 200.

## Rebuild / restart

```bash
# from signals root
export SIG_MAVEN_REPO=$PWD/.devenv/m2
(cd components/atlas && mvn -Dmaven.repo.local=$SIG_MAVEN_REPO package -pl webapp -am \
  -Dmaven.test.skip=true -DskipUTs=true -DGRAPH-PROVIDER=age \
  -Dcheckstyle.skip=true -DskipEnunciate=true -Dmockito.version=3.5.10)
# restart Atlas process on :21010 with webapp target
```

## Next (M3)

- Flink dual-path BDD (OL → Atlas `/api/v1` + governance path)
- Optional: reclaim `:3000` for marquez-web when atelier not bound
- Tighten dual-mapping docs; contract tests against Marquez API subset
