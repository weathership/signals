# Tiered signal warehouse: wired end to end (Postgres → Kudu → Iceberg+HDF5)

Guru: `#SL.00000027.SCHEMA2` · `#SL.00000029.HDF5SIGNAL` · `#SL.00000025.TIERUP`
Schema: `214236_schema-final-e2e.md`. Design: `195942_two-tier-schema-redesign.md`.

## Correction that shaped this

I proposed carrying the old `fetch_gpu_hist_buckets` pattern forward — app
queries Kudu for hot hours, Iceberg for the rest — as "the proven approach".
It is not: there is no proven approach in a novel tiered implementation, and
the old one was unreliable. **Readers use one surface.** The strip reads
`signal_tier0` because its 60 s window is inside the hot day by construction;
the broad Kumo window reads the `signal` UNION view and nothing else. That
puts the correctness pressure where it belongs: the HDF5 reader and Impala's
plan, not the caller.

## What changed

### Impala (submodule)
- `PlanNodes.thrift` `THdfsScanNode`: `17: hdf5_schema_json`, `18: hdf5_filter_json`.
- `IcebergScanPlanner` hands every data scan node the Iceberg expressions it
  pushed (`impalaIcebergPredicateMapping_` keys); `IcebergScanNode.toThrift`
  serialises the table schema + `AND` of those expressions when the scan has
  HDF5 files.
- BE `HdfsScanNodeBase` carries both strings; `HdfsHdf5Scanner` constructs
  `IcebergHdf5Scanner(path, schemaJson, filterJson)` and gains a
  `TYPE_DECIMAL` slot case (unscaled int at 4/8/16 bytes).
- FE `IcebergHdf5Scanner` was hardcoded to the 7-column gpu_metrics schema and
  built from a path only — `signal_tier1` could not be read at all. Now
  schema-driven with `filter()` applied; DECIMAL cells cross JNI as their
  unscaled `Long`.

### iceberg-hdf5 (semantics submodule, `321dce1`)
- `Hdf5ReadBuilder.filter()`/`split()` were `return this` → honoured.
- New `/signal` layout (schema_version 2): sorted `ts`, sorted `series_id`,
  `values int64[S][T]` (dec: unscaled + `@scale`), `present uint8[S][T]`.
  Bound-expression visitor lifts `ts_ns` bounds / `series_id` sets /
  `epoch_hour` eq → binary search + one jhdf hyperslab per series; Iceberg
  `Evaluator` runs as the residual, so narrowing only tightens.
- Legacy `/Machine` files: read whole, then residual-filtered — correct, not
  narrowed.
- 9 tests pass (5 new), fixture `analog/fixtures/signal_v2_small.h5`.
- jhdf widens `uint8`→`int[]`; the reader accepts every integer width.

### signals
- `scripts/IcebergHdf5Register.java`: table-agnostic; `signal_tier1` appends
  carry manifest bounds for `epoch_hour`/`ts_ns`/`series_id` (previously no
  `withMetrics` → only partition pruning).
- `scripts/signal_settle.py` + `just signal-settle`: closed hour → HDF5 → S3 →
  Iceberg append → Impala count verify → state row; `--drop-days` retires a
  Kudu day only when all 24 hours are verified. **No orchestration existed.**
- `config/platform/signal-registry.sql`: `catalog_tables` rows — Impala loads
  Kudu/VIEW tables ONLY from here; a Kudu table without a row is invisible to
  HS2. Two rollback leftovers deleted.
- `config/platform/signal-fdw.sql`: 8 foreign tables on **both** PGs; on
  :5444 created as `rch` (server owner) with grants to `gaius`.
- `scripts/systemd_target_verify.sh`: no longer checks itself (false FAIL every
  boot); freshness reads `signal_tier0` via kudu_scan instead of `max()` over
  the union.
- `scripts/signal_stack_verify.sh` + `just signal-verify`.
- `devenv.nix`: tserver `--array_cell_max_elem_num=4096`.

### gaius (`27f5ee2`)
- `warehouse_ingest.py`: `signal_series` seeded on boot (25 series); DCGM as
  INT at native precision (power in mW), cognition channels as DECIMAL; raw
  Prometheus parse (no `float()`); day-wide ranges via HS2 ALTER.
- `cognition_waterfall.py`: strip from `signal_tier0`; `fetch_gpu_hist_buckets`
  from the `signal` view with pushed predicates.
- `devenv.nix`: `gaius-engine` readiness probe (was "starting" forever).
- 24 tests pass.

## Restart reliability faults found

| Fault | Root cause | Fix |
|---|---|---|
| `gaius.service` "Permission denied /run/user/1001/devenv-…" at boot | `Linger=no` → no `/run/user/1001` before login | `loginctl enable-linger rch` (done) |
| signals foundation under `/tmp/devenv-85cf547`, login shell "no process manager" | same | same; next restart lands both surfaces in `/run/user/1001` |
| `signals-refresh` FAIL every boot | verifier checked its own `activating` unit | skip self |
| `gaius-engine starting` forever | no readiness probe | probe added |
| iceberg-hdf5 "release 17 not supported" | session inherits `JAVA_HOME`=JDK11 from gaius devenv | explicit `JAVA_HOME=.devenv/profile` |

## Verification

(appended after `just signals-restart`)
