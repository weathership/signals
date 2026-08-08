# Vocabulary: signals_table, not hive_table

**Context:** K5b smokes still filtered `type_name = 'hive_table'` because the seed row in
`atlas.entity_flat` used Atlas bootstrap type names. That is fixture residue, not architecture.

## Layers (keep distinct)

```
Client
  → PostgreSQL (FDW, GRANT/RLS, foreign tables)
      → impala_fdw
          → kudu_scan  → libkudu_client → Kudu masters/tservers
          → impala_sql → Impala HS2     → Kudu (only)
  → Atlas (governance types over the same assets)
```

- **No Hive as storage.** No HMS as catalog of record (HMS-free Impala).
- **Impala** is the analytical SQL engine over Kudu (later Iceberg).
- **Postgres** is the interactive / policy front end.
- **`kudu_table`** FDW option = physical Kudu name. Keep that meaning.
- **Atlas entity type** for “a table in this platform” = **`signals_table`**
  (not `hive_table`, not “Impala-as-Hive”).

## Seed / smoke

Live lab row today: `type_name=hive_table`, `name=fdw_smoke`. Prefer re-seed to
`type_name=signals_table` once typedef exists, or use `name`/`guid` filters in FDW
smokes so we do not teach hive vocabulary in docs.

## Code still on hive_* (cutover backlog)

- `features/platform/steps/helpers.py` `register_impala_table_in_atlas`
- `features/platform/steps/integration_steps.py`
- `src/sigint/atlas_client.py`
- Roadmap §2 updated 2026-08-08 to target `signals_*`
