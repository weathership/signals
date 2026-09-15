# FMP warehouse Kudu tier0 (gaius.fmp.warehouse)

Gaius Metaflow writes Starter Annual profile/filings/earnings through
Postgres impala_fdw `kudu_scan` into `signals_dataproducts.fmp_*_tier0`.
Schema is the nautilus scalar HS2 path (`CREATE … STORED AS KUDU`), not
`signals_kudu_create.cc`. Iceberg `fmp_*_tier1` is PENDING.

Apply: `python -m signals.ops schema-apply` (extra file `fmp-kudu.sql`).
Metabase reads Gaius `:5444` views `warehouse.v_fmp_*`, not Polarisfork
and not Gaius `:3100` `meta.*`.
