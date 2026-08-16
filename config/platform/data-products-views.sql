-- Logical warehouse names: details / tx / hx. Impala merges tiers.

CREATE VIEW IF NOT EXISTS signals_dataproducts.tx AS
SELECT epoch_hour, product_id, tx_id, ts_ns, kind, summary, source, ce_type
FROM signals_dataproducts.tx_tier0
UNION ALL
SELECT epoch_hour, product_id, tx_id, ts_ns, kind, summary, source, ce_type
FROM signals_dataproducts.tx_tier1;

CREATE VIEW IF NOT EXISTS signals_dataproducts.details AS
SELECT epoch_hour, e, a, t, v, op, ts_ns
FROM signals_dataproducts.details_tier0
UNION ALL
SELECT epoch_hour, e, a, t, v, op, ts_ns
FROM signals_dataproducts.details_tier1;

CREATE VIEW IF NOT EXISTS signals_dataproducts.hx_exchange AS
SELECT epoch_hour, product_id, tx_id, ts_ns, agent, role, message
FROM signals_dataproducts.hx_exchange_tier0
UNION ALL
SELECT epoch_hour, product_id, tx_id, ts_ns, agent, role, message
FROM signals_dataproducts.hx_exchange_tier1;

CREATE VIEW IF NOT EXISTS signals_dataproducts.hx_reasoning AS
SELECT epoch_hour, product_id, tx_id, agent, ts_ns, quality, lineage, delta, trace
FROM signals_dataproducts.hx_reasoning_tier0
UNION ALL
SELECT epoch_hour, product_id, tx_id, agent, ts_ns, quality, lineage, delta, trace
FROM signals_dataproducts.hx_reasoning_tier1;
