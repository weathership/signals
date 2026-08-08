# Atlas OpenLineage M2 kickoff

**Date:** 2026-08-08

## Shipped (signals trunk)

- Kerberos-required stack, Marquez-web default process, portable backup, identity docs
- Commit: `feat: Kerberos-required stack, Marquez UI, portable backup, and OL doctrine`
- Pushed: `origin/trunk`

## Atlas submodule (`rch/signals`)

M2 start in `components/atlas`:

| Piece | Role |
|-------|------|
| `web.xml` | Additional Jersey mapping `/api/v1/*` |
| `AtlasSecurityConfig` | `/api/v1/**` ignored (lab OL + marquez-web; ZT at edge in prod) |
| `OpenLineageStore` | AGE graph `signals_ol` + `public.lineage_events` on Atlas JDBC |
| `OpenLineageREST` | POST/GET lineage, namespaces, jobs, runs, datasets |

Rebuild Atlas webapp and restart Atlas to exercise:

```bash
devenv tasks run atlas:build
# restart atlas process
curl -sS -X POST http://127.0.0.1:21010/api/v1/lineage -H 'Content-Type: application/json' -d '{...}'
curl -sS http://127.0.0.1:21010/api/v1/namespaces
```

## Next

- Unit/integration smoke for ingest + marquez-web
- Parent repo submodule pointer bump after atlas push
- Flink dual-path BDD steps (M3)
