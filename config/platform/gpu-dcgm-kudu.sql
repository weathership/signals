-- Extended DCGM fields — Kudu tier0. Sibling of gpu_metrics_tier0.
--
-- Narrow (field, value) rather than columns on gpu_metrics_tier0: that table
-- is created by the C++ gpu_kudu_create client (HS2 CREATE ... STORED AS KUDU
-- hits KUDU-2121), so Impala resolves it read-only through the catalog
-- registry and ALTER TABLE ... ADD COLUMNS raises TableNotFoundException.
-- Its Iceberg tier1 is READONLY to Impala as well. A sibling table needs no
-- mutation of either, and a further DCGM field costs no DDL at all.
--
-- Fields carried (DCGM_FI_DEV_*):
--   sm_clock_mhz  SM_CLOCK                  MHz
--   mem_temp_c    MEMORY_TEMP               C
--   energy_mj     TOTAL_ENERGY_CONSUMPTION  mJ since boot (monotonic)
--   xid_errors    XID_ERRORS                last XID; hardware fault signal

CREATE DATABASE IF NOT EXISTS signals_dataproducts;

CREATE TABLE IF NOT EXISTS signals_dataproducts.gpu_dcgm_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  gpu_index INT,
  field STRING,
  value DOUBLE,
  PRIMARY KEY (epoch_hour, ts_ns, gpu_index, field)
)
PARTITION BY HASH (gpu_index) PARTITIONS 2,
RANGE (epoch_hour) (
  PARTITION VALUES < 0
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.master_addresses' = 'tinybox.dev.vista.zndx.org:7051',
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.expire' = 'drop_range_partition',
  'signals.range_unit' = 'hour',
  'signals.range_width_hours' = '1',
  'signals.product' = 'gaius.machine.gpu_dcgm'
);
