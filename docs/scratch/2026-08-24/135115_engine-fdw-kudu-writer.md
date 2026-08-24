# Engine FDW writer + Impala DROP RANGE PARTITION

Gaius engine is the Kudu writer (`INSERT gpu_metrics_tier0` via
`kudu_scan`). `scripts/gpu_metrics_kudu_ingest.py` exits: sidecar retired.

`impala_fdw_exec(server, sql)` runs Impala
`ALTER TABLE … ADD/DROP RANGE PARTITION` (and `SHOW RANGE PARTITIONS`)
over HS2 GSSAPI. After catalogd `TableLoadingException`, it reconnects and
requires SHOW RANGE to match. Test: ADD then DROP `VALUE = 496566`.

SPEC G6/N2: Iceberg cold + UNION on `impala_sql`; `kudu_scan` stays Kudu.
G12: expire is whole-range `DROP RANGE PARTITION` only.

Analog hour load prefers FDW `gpu_metrics_tier0` over jsonl.
