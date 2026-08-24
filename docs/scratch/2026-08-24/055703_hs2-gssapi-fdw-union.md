# HS2 GSSAPI Thrift-over-SASL: FDW UNION reads

`impala_fdw` OpenSession over GSSAPI works. Postgres `:5455` can `SELECT`
Iceberg `gpu_metrics_tier1` and the Impala UNION view `gpu_metrics`.

Closed Kudu hour ranges 496537–496540 were **not** dropped (UNION ALL still
double-counts those hours).

## Fixes

- Build and link Thrift **0.22** with the generated TCLIService stubs
  (0.16 `TBinaryProtocol` SIGSEGVs on the first read: missing `writeUUID`
  vtable slot). Guru: `#SL.00000028.HS2GSSAPI`.
- Drain Impala's final SASL COMPLETE frame (`05 00 00 00 00`) after Cyrus
  returns `SASL_OK`, then use `TFramedTransport` on the socket fd (QOP=auth).
- Replace `impala_fdw.so` via `install`/`mv` (new inode), never `cp -f` onto
  a mapped backend.

## Verified

- HS2 GSSAPI `COUNT(*) FROM gpu_metrics_tier1` = 75648
- FDW `gpu_metrics` `access=impala_sql` UNION COUNT = kudu + iceberg
- `INSERT INTO gpu_metrics_tier0` (kudu_scan) still round-trips

Writes stay on `gpu_metrics_tier0`. Reads of the hierarchy use `gpu_metrics`.
