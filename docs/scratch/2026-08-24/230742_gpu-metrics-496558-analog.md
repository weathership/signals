# gpu_metrics soak analog 496558 (23:07Z)

Closed hour **496558** analog 21036 warehouse rows → Polarisfork HDF5
(jsonl 21600; honest catalog-stall gap). Iceberg verify 21036.
**DROP RANGE 496558 not applied** (mutation blocked). UNION double-counts
that hour (42072) until DROP. Live **496559** on engine FDW Kudu
(`pid 4115269`). SHOW RANGE still `496558` … `496582`.
