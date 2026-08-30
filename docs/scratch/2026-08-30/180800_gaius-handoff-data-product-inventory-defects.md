# Handoff from Gaius: data-product inventory defects found while federating `gaius.curation.cot_reasoning`

Written 2026-08-30 from the Gaius session that landed the chain-of-thought reasoning
corpus as a federated data product. The **physical** path works end-to-end today —
Gaius PyIceberg → Polaris `signals` (:8181) → `s3://signals-dataproducts/iceberg/hx/cot_reasoning`
→ Signals Impala reads `hx.cot_reasoning` with zero registration; discovery over
`ServerQuery(kind=PRODUCTS)`. What does **not** work is the Signals-owned
**inventory** (`tx` / `details` / `hx_reasoning`), because the warehouse schema
cannot be applied on this Impala. Peers' publishes (`gaius.prospects.corpus`
*and* `gaius.curation.cot_reasoning`) therefore soft-fail to the History JSONL
(`build/state/data-product-history.jsonl`) — the inventory has never been live here.

Environment: tinybox, Impala fork `impalad version 5.0.0-SNAPSHOT DEBUG (build c907f06…,
2026-08-25)`, Polaris :8181, Kudu :7051, RustFS :9010.

## 1. `role` is a reserved word — schema apply aborts at `hx_exchange`

`ImpalaWarehouse.apply_schema()` (`src/signals/ops/warehouse.py:228`) splits each
file on `;` and executes statements in order; the first failure aborts the rest.

- `config/platform/data-products-kudu.sql:89` — `hx_exchange_tier0` column `role STRING`
- `config/platform/data-products-iceberg.sql:49` — `hx_exchange_tier1` column `role STRING`

Error (both files):
```
ParseException: Syntax error in line 7:   role STRING,   ^
Encountered: ROLE  Expected: FOREIGN, NON, PRIMARY, IDENTIFIER
Hint: reserved words have to be escaped with backticks
```
Consequence: `tx_tier0`, `details_tier0` were created (they precede the failure);
`hx_exchange_tier0`, `hx_reasoning_tier0` (and the tier1 twins) were **not**. Every
writer that touches `hx_reasoning` (`signals.ops.history.review` →
`insert_hx_reasoning`) fails.

Fix: backtick the identifier (`` `role` STRING ``) in both files — and anywhere the
column is referenced (`data-products-views.sql`, `warehouse.py` INSERT/SELECT
builders for `hx_exchange`), or rename it (e.g. `speaker`). Consider making
`apply_schema` continue past a failed statement and report all failures, so a
single reserved word does not silently leave the inventory half-built.

## 2. Iceberg tier1 tables created via Impala DDL cannot be loaded back

`data-products-iceberg.sql` created `tx_tier1` / `details_tier1` (they appeared in
`SHOW TABLES IN signals_dataproducts`), but:

```
DESCRIBE signals_dataproducts.tx_tier1
AnalysisException: Could not load table signals_dataproducts.tx_tier1 from catalog
CAUSED BY: TableLoadingException … CAUSED BY: TException: Every MetaProvider failed …
Kudu (tinybox.dev.vista.zndx.org:7051): … NoSuchObjectException(Table not found: signals_dataproducts.tx_tier1)
```
`INVALIDATE METADATA signals_dataproducts.tx_tier1` → `IllegalStateException: null`,
after which the two tables **disappear** from `SHOW TABLES` (phantom entries).
`data-products-views.sql` then fails (`Could not resolve table reference:
'signals_dataproducts.tx_tier1'`), so the merged `tx` / `details` / `hx_*` views
never exist.

The tier1 DDL uses `STORED AS ICEBERG TBLPROPERTIES ('iceberg.catalog'='polaris',
'write.location'='s3a://signals-dataproducts/iceberg/tx_tier1', …)`. The tier1 tables
that *do* work on this instance (`signal_tier1`, `gpu_metrics_tier1`,
`cognition_metrics_tier1`, `gpu_dcgm_tier1`) were registered **through Polaris**
(`IcebergHdf5Register` / PyIceberg — see `config/platform/signal-registry.sql`,
`scripts/signal_stack_verify.sh`), not by Impala `CREATE TABLE … STORED AS ICEBERG`.
Hypothesis: in this HMS-less local-catalog configuration, Impala's Iceberg DDL
writes metadata the `MultiMetaProvider` cannot resolve back (it falls through to the
Kudu provider). Recommended: create the data-product tier1 tables the same way the
working ones are — via Polaris (PyIceberg `catalog.create_table` in namespace
`signals_dataproducts`, `write.location` under `s3://signals-dataproducts/iceberg/`)
— then `data-products-views.sql` should apply.

## 3. Smaller items

- `config/platform/data-products.json` (bootstrap seed) has no entry for
  `gaius.curation.cot_reasoning` — `review(product=…)` creates it on first call
  once the inventory exists; add the seed if you want it present before the first
  run. Product shape (from Gaius `flows/article_curation/publish.py::CATALOG`):
  `id gaius.curation.cot_reasoning`, `kind reasoning`, `leaf root.internal.inference.extract`,
  `table_identifier hx.cot_reasoning`, `data_uri s3://signals-dataproducts/iceberg/hx/cot_reasoning`.
- `scripts/impala_query.py -q "SELECT count(*) AS rows …"` — `rows` is reserved in
  this Impala (cosmetic; my query).
- `queue_share`: every admit logs `queue share not APPLIED within 30.0s (still
  RECORDED) … YuniKorn/kubectl reconcile lagging` — the share never reaches
  APPLIED within the wait; harmless for admission (the pod binds), but the
  Signals-side apply lag is consistent.
- YuniKorn REST at `:30080` **is** reachable from tinybox (the "NodePort gap" in older
  notes is not a gap locally); `signals.cli.yk diff` printed nothing when run from a
  Gaius shell — verify the promoted queue config matches `federation-queues.yaml`
  (live `root.internal.inference.extract` shows `guaranteed=0`, `max=2`).
- Protocol: `signals-protocol` gained `ServerQuery(kind=PRODUCTS)` /
  `ProductHint` (commit `aab367f`) and `WatchWorkload` (`9ac131c`) — both additive
  v1; Signals may want to consume `PRODUCTS` in its federated view.

## How to verify once fixed (from `$SIGNALS_ROOT`, its own venv — not `uv run` from a Gaius shell)

```bash
.devenv/state/venv/bin/python -c "from signals.ops.warehouse import ImpalaWarehouse; ImpalaWarehouse().apply_schema()"
.devenv/state/venv/bin/python scripts/impala_query.py -q "SHOW TABLES IN signals_dataproducts"
#   expect: tx_tier0 tx_tier1 details_tier0 details_tier1 hx_exchange_* hx_reasoning_* + views tx details hx_exchange hx_reasoning
.devenv/state/venv/bin/python -m signals.ops review-product gaius.curation.cot_reasoning --kind updated --summary "manual verify"
.devenv/state/venv/bin/python scripts/impala_query.py -q "SELECT product_id, kind, summary FROM signals_dataproducts.tx ORDER BY ts_ns DESC LIMIT 3"
```
Then a Gaius article-curate run's `end` step should print
`Published gaius.curation.cot_reasoning tx=<uuidv7> (nominal)` instead of
`Product publish: History JSONL only — …`.
