# gpu_metrics soak analog 496554 (19:11Z)

Closed hour **496554** analog 13974 warehouse rows → Polarisfork HDF5
(jsonl 21558; honest recycle/engine-down gap). Iceberg verify 13974.
**DROP RANGE 496554** verified; SHOW RANGE `496555` … `496574`. Live
**496555** on engine FDW Kudu after `devenv processes restart
gaius-engine`. UNION no longer double-counts that hour.
