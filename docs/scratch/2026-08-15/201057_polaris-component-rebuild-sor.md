# Polaris component, just rebuild, RustFS sole SoR

## Polarisfork

Cyberphy `thirdparty/polaris` was empty. Realized pin is
`~/local/src/cldr/cybersec/thirdparty/polaris` —
`apache-polaris-1.3.0-incubating` (`c940ded0`).

Signals now vendors that pin as `components/polaris` → `rch/asf-polaris`
(same SHA). `polaris:install` builds from the submodule, not a fresh
`git clone` of apache/polaris.

## Stack

- `processes.polaris` + `polaris-init` in devenv (warehouse
  `s3://signals-dataproducts/iceberg` on RustFS).
- `signals-polaris.service` + `Wants=` on `signals.target`.
- pglite `polaris` DB = catalog metadata only. Product rows stay Iceberg.

## just rebuild (Metabase-shaped)

`just rebuild` → `scripts/signals_rebuild.sh`:

1. `devenv tasks run polaris:install`
2. `devenv processes restart polaris` (or `devenv up -d`)
3. wait `http://127.0.0.1:8182/q/health/ready`
4. `setup_polaris_catalog.sh`

`SKIP_POLARIS_BUILD=1` is the `SKIP_FE=1` analogue. Distinct from
`just redeploy` (K8s) and Metabase `just rebuild` (AGPL tree).

## SoR

`signals.ops.warehouse` writes Iceberg only; refuses Postgres DSNs.
`review-product` no longer appends JSONL as a warehouse.
8 tests in `tests/signals/test_data_products.py`.
