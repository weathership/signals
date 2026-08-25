-- Impala HMS-free catalog registry (database signals_catalog on :5455).
-- KuduMetaProvider/IcebergMetaProvider load tables ONLY from catalog_tables;
-- a Kudu table that exists on the master but has no row here is invisible to
-- HS2 (ALTER RANGE PARTITION, views, UNION). Kudu tables themselves are
-- created by scripts/signals_kudu_create.cc — never HS2 CREATE (#SL.00000027.SCHEMA2).

INSERT INTO catalog_databases (name, location)
VALUES ('signals_dataproducts', 's3a://signals-dataproducts/iceberg')
ON CONFLICT (name) DO NOTHING;

INSERT INTO catalog_tables (db_name, table_name, table_type, parameters) VALUES
  ('signals_dataproducts', 'signal_series', 'KUDU',
   '{"kudu.table_name": "impala::signals_dataproducts.signal_series", "kudu.master_addresses": "tinybox.dev.vista.zndx.org:7051"}'),
  ('signals_dataproducts', 'signal_tier0', 'KUDU',
   '{"kudu.table_name": "impala::signals_dataproducts.signal_tier0", "kudu.master_addresses": "tinybox.dev.vista.zndx.org:7051", "signals.tier": "0", "signals.expire": "drop_range_partition", "signals.range_unit": "day"}'),
  ('signals_dataproducts', 'latent_tier0', 'KUDU',
   '{"kudu.table_name": "impala::signals_dataproducts.latent_tier0", "kudu.master_addresses": "tinybox.dev.vista.zndx.org:7051", "signals.tier": "0", "signals.range_unit": "day"}'),
  ('signals_dataproducts', 'clt_feature', 'KUDU',
   '{"kudu.table_name": "impala::signals_dataproducts.clt_feature", "kudu.master_addresses": "tinybox.dev.vista.zndx.org:7051"}'),
  ('signals_dataproducts', 'clt_label', 'KUDU',
   '{"kudu.table_name": "impala::signals_dataproducts.clt_label", "kudu.master_addresses": "tinybox.dev.vista.zndx.org:7051"}'),
  ('signals_dataproducts', 'clt_activation_tier0', 'KUDU',
   '{"kudu.table_name": "impala::signals_dataproducts.clt_activation_tier0", "kudu.master_addresses": "tinybox.dev.vista.zndx.org:7051", "signals.tier": "0", "signals.range_unit": "day"}'),
  ('signals_dataproducts', 'signal_tier1', 'ICEBERG',
   '{"location": "s3://signals-dataproducts/iceberg/signals_dataproducts/signal_tier1", "table_type": "ICEBERG", "iceberg.catalog": "polaris", "write.format.default": "hdf5", "signals.tier": "1"}'),
  ('signals_dataproducts', 'signal', 'VIEW',
   '{"view.original": "SELECT epoch_hour, ts_ns, series_id, src, gpu, inst, val_i, val_d FROM signals_dataproducts.signal_tier0 UNION ALL SELECT epoch_hour, ts_ns, series_id, src, gpu, inst, val_i, val_d FROM signals_dataproducts.signal_tier1 t1 WHERE t1.epoch_hour NOT IN (SELECT epoch_hour FROM signals_dataproducts.signal_tier0 GROUP BY 1)",
     "view.expanded": "SELECT epoch_hour, ts_ns, series_id, src, gpu, inst, val_i, val_d FROM signals_dataproducts.signal_tier0 UNION ALL SELECT epoch_hour, ts_ns, series_id, src, gpu, inst, val_i, val_d FROM signals_dataproducts.signal_tier1 t1 WHERE t1.epoch_hour NOT IN (SELECT epoch_hour FROM signals_dataproducts.signal_tier0 GROUP BY 1)"}')
ON CONFLICT (db_name, table_name) DO UPDATE SET
  table_type = EXCLUDED.table_type, parameters = EXCLUDED.parameters;

-- Rollback leftovers from 2026-08-24 (created through the crashing HS2 path;
-- their Kudu tables were dropped, these Iceberg shells hold nothing).
DELETE FROM catalog_tables
 WHERE db_name = 'signals_dataproducts'
   AND table_name IN ('cognition_metrics_tier1', 'gpu_dcgm_tier1');
