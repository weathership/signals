# FMP warehouse Kudu tier0 (gaius.fmp.warehouse)

Gaius Metaflow writes Starter Annual profile/filings/earnings through
Postgres impala_fdw `kudu_scan` into `signals_dataproducts.fmp_*_tier0`.
Apply is `signals_kudu_create.cc` (libkudu_client) plus `catalog_tables`
rows — the same path as `signal_tier0`. Writers INSERT through Postgres
`impala_fdw` `kudu_scan`. Python impyla is not required. Iceberg
`fmp_*_tier1` is PENDING.

Metabase reads Gaius `:5444` views `warehouse.v_fmp_*` over the kudu_scan
foreign tables, not Polarisfork and not Gaius `:3100` `meta.*`.
