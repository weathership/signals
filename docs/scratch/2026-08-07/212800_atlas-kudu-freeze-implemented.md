# Atlas Kudu freeze locked + phase-1a landed

## Freeze

Canonical: `docs/scratch/2026-08-07/211412_atlas-kudu-projection-freeze.md`  
Outbox: `docs/current/src/architecture/atlas-kudu-outbox.md`

## Landed

| Artifact | Path |
|----------|------|
| Impala/Kudu DDL | `config/atlas/kudu_projections.sql` |
| PG foreign tables | `config/atlas/kudu_projections_fdw.sql` |
| Seed script | `scripts/atlas_kudu_projections_seed.sh` / `just atlas-kudu-projections-seed` |
| FDW deparse/pushdown | `components/impala_fdw/src/deparse.c` |
| FDW plan/scan | `components/impala_fdw/src/impala_fdw.c` (projection, WHERE, LIMIT, EXPLAIN) |
| SPEC | phase **1a** exit criteria; IN/ANY required |

## Verified

- All six `atlas.*` tables created via HS2.
- Foreign tables registered on `:5455/signals`.
- EXPLAIN shows e.g.  
  `SELECT \`type_name\`, \`name\` FROM \`atlas\`.\`entity_flat\` WHERE \`type_name\` = 'hive_table'`  
  and  
  `… edge_out WHERE \`src\` IN (CAST(unhex('…') AS BINARY))`.
- BINARY literals deparsed as `CAST(unhex('…') AS BINARY)` (Impala rejects bare `X'…'` vs BINARY).

## Still open (next)

1. Frontier batching measurements (batch size vs hop latency).
2. `libkudu_client` / true `kudu_scan` (currently falls back to HS2 with pushdown).
3. Outbox worker + REPLICA IDENTITY / Atlas notification delete payloads.
4. Param/bind deparse for prepared `= ANY($1)` (phase 1 Const-only; array Const from `decode`/`ARRAY[...]` works).
5. Recreate `fdw_smoke` foreign table if needed after FDW reinstall.
