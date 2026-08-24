# HMS-free gpu_metrics UNION view (04:59Z)

`CREATE VIEW IF NOT EXISTS signals_dataproducts.gpu_metrics AS
  SELECT … FROM gpu_metrics_tier0 UNION ALL SELECT … FROM gpu_metrics_tier1`
now succeeds without HMS. `catalog_tables` row is `VIEW` with
`view.original` / `view.expanded`. HS2 `SHOW TABLES` lists it.
`SELECT epoch_hour, count(*) FROM gpu_metrics GROUP BY 1` returns all
four hours (closed hours double-count while they remain in Kudu).

Do not DROP Kudu ranges yet: FDW `:5455` `gpu_metrics` is still
`kudu_scan` of tier0 (HS2 GSSAPI not in `impala_sql`). Strip=1h uses
those tablets.
