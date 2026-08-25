-- Work (not the clock): Iceberg verify then Kudu DROP RANGE.
-- Gaius pg_cron on zndx_gaius :5444 inserts scheduled_tasks.gpu_metrics_settle.
-- The engine calls this function over SIGNALS_WAREHOUSE_DSN (:5455).
-- Do not cron.schedule this on the warehouse database.
-- Guru: #SL.00000026.SETTLE

CREATE OR REPLACE FUNCTION public.gpu_metrics_settle()
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  rec RECORD;
  now_h integer;
  ice_n bigint;
  dropped integer[] := ARRAY[]::integer[];
BEGIN
  now_h := floor(extract(epoch FROM clock_timestamp()) / 3600)::integer;
  FOR rec IN
    SELECT epoch_hour, count(*)::bigint AS n
      FROM gpu_metrics_tier0
     GROUP BY epoch_hour
  LOOP
    IF rec.epoch_hour >= now_h THEN
      CONTINUE;  -- live hour stays on Kudu
    END IF;
    SELECT count(*) INTO ice_n
      FROM gpu_metrics_tier1
     WHERE epoch_hour = rec.epoch_hour;
    IF ice_n IS NULL OR ice_n = 0 THEN
      RAISE EXCEPTION
        '#SL.00000026.SETTLE iceberg missing hour % — analog first (Metaflow GpuMetricsSettle)',
        rec.epoch_hour;
    END IF;
    IF ice_n < rec.n THEN
      RAISE EXCEPTION
        '#SL.00000026.SETTLE refuse DROP hour % ice % < kudu %',
        rec.epoch_hour, ice_n, rec.n;
    END IF;
    PERFORM impala_fdw_exec(
      'impala_kudu_srv',
      format(
        'ALTER TABLE signals_dataproducts.gpu_metrics_tier0 DROP RANGE PARTITION VALUE = %s',
        rec.epoch_hour
      )
    );
    dropped := array_append(dropped, rec.epoch_hour);
  END LOOP;
  RETURN jsonb_build_object('dropped', dropped, 'now_hour', now_h);
END;
$$;

COMMENT ON FUNCTION public.gpu_metrics_settle() IS
  'Iceberg-verify then Kudu DROP RANGE for closed gpu_metrics hours. Live hour is skipped. Fail-closed if analog is missing.';

-- Clock lives on Gaius zndx_gaius :5444 (scheduled_tasks), not here.
