# Logical portable backup via DataFusion (not Kudu FS)

**Date:** 2026-08-08

## Decision

- Kudu **physical** FS under `$SIGNALS_DATA_ROOT/kudu` is **local-only** (embedded hostnames).
- Portable backup uses **logical** Parquet under `stamp/logical/` owned by **Apache DataFusion**
  (`crates/signals-df`), not Spark.
- Uniform service layout: `logical/<service>/{tables.json,*.parquet}`.
- `just backup` default `SIGNALS_BACKUP_KUDU=logical`; `physical-local` is non-portable lab only.
- `just restore` refuses NON_PORTABLE Kudu tars; DataFusion-verifies logical packages and stages
  to `$SIGNALS_DATA_ROOT/logical-restore/`.

## Verified

- `cargo build -p signals-df` ok
- `signals-df` init/ingest/verify smoke ok
- `SIGNALS_BACKUP_KUDU=skip just backup --services atlas,ranger` exit 0
