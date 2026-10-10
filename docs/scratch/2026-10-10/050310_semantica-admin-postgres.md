# Semantica admin Postgres on :5588

Semantica's devenv Postgres is the peer admin database. It is not Signals `:5455`.

- `port_lattice_postgres` `5588` and `peers[].engine_pg_port` `5588` in `config/platform/peer-contract.json`.
- `admin.graph` stays in that database. Heavy node, edge, provenance, and chunk rows are Kudu tier0 (`signals_dataproducts.semantica_*_tier0`) through the Signals `impala_fdw`.
- Iceberg is the settle tier. Impala still cannot write it.
