-- Impala HMS-free catalog registry (database signals_catalog on :5455).
-- KUDU/VIEW rows are load-bearing: KuduMetaProvider serves HS2 only from
-- catalog_tables, so a Kudu table created OUTSIDE HS2 (signals_kudu_create.cc)
-- is invisible without its row here. catalogd auto-registers its own HS2 DDL.
-- ICEBERG rows are INERT: Iceberg tables are Polaris-discovered live (every
-- registry read filters table_type IN ('KUDU','VIEW')).
-- Two DISTINCT pendings — do not conflate:
--   * signal Kudu tables come from scripts/signals_kudu_create.cc because HS2
--     `CREATE ... STORED AS KUDU` crashed the tserver for THIS shape (see the
--     .cc header); Kudu HS2 CREATE otherwise works (data-products-kudu.sql
--     applies over HS2 and auto-registers).
--   * Impala Iceberg DDL/DML is PENDING in-fork (#SL.00000027.SCHEMA2;
--     upstream IMPALA-13586 read-only "yet") — Polaris registration and
--     out-of-band settle are the bridge.

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
