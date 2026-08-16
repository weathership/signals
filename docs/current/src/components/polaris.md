# Polaris

Apache Polaris is the Iceberg REST catalog. Signals vendors it as
`components/polaris` from [`rch/asf-polaris`](https://github.com/rch/asf-polaris)
pinned at **apache-polaris-1.3.0-incubating** (`c940ded0`) — the same pin
realized in `cldr/cybersec/thirdparty/polaris`.

## Role

Polaris is the catalog for data-product Iceberg tables on **RustFS**. It is
**not** a product warehouse. JDBC persistence on Postgres `:5455` / database
`polaris` holds catalog metadata (namespaces, table pointers). Product
**details / tx / `hx`** settle as Iceberg `*_tier1` under
`s3a://signals-dataproducts/iceberg` (RustFS). Hot land is Kudu `*_tier0`.

See [Data Products History](../architecture/data-product-history.md).

## Lab surfaces

| Surface | Port |
|---------|------|
| REST catalog | `:8181` |
| Management / health | `:8182` (`/q/health/ready`) |

```bash
git submodule update --init components/polaris
just rebuild                         # assemble + restart polaris + wait :8182
# or: just polaris-install && devenv up -d
just signals-ready                   # polaris is WARN until :8182 answers
SKIP_POLARIS_BUILD=1 just rebuild    # restart only (Metabase SKIP_FE analogue)
```

Catalog create: `scripts/setup_polaris_catalog.sh` (catalog name `signals`,
warehouse `s3://signals-dataproducts/iceberg`).

## systemd

`signals-polaris.service` is a foundation unit (`PartOf=signals.target`).
`systemctl restart signals.target` waits for (or starts) Polaris after
`signals.service`. Prefer the devenv process when `just up` is the owner.

## Impala

`config/impala/catalog_config_dir/polaris.properties` points Impala at
`http://localhost:8181/api/catalog` with warehouse `signals`.
