# details_tier0 / details_tier1 + RustFS, no /tmp

Kudu schema design applied:
https://kudu.apache.org/docs/schema_design.html

- Expire via DROP RANGE PARTITION (not row DELETE; Kudu has no range delete).
- Range key = `epoch_day` (PK prefix). `t`/`tx_id` is UUID — identity only.
- HASH(e|product_id) × RANGE(epoch_day). Lab: 2 hash buckets, replica=1.
- `op` BOOLEAN cannot be in the PK.

Impala `core-site`/`hive-site`/`catalog_schema`/`hms` warehouse paths are
`s3a://signals-dataproducts/` (RustFS :9010). No `file:///tmp/signals-warehouse`.

10 tests green. Settle/verify/DROP job not wired yet.
