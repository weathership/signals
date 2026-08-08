# Storage root and stack backup

## One path

```bash
just bootstrap           # Kerberos required (KDC, keytabs, kinit, FQDN env)
devenv up -d             # Impala + Kudu start only with Kerberos
just backup              # full portable snapshot of all services (GSSAPI Impala)
just restore <stamp>     # full portable restore + verify
```

There is **no** NOSASL fallback, no service menu, no Kudu physical mode, and no
partial success. Bootstrap and stack processes **require** Kerberos.

## Durable data plane

```text
$SIGNALS_DATA_ROOT/          # default lab: /raid/signals  (user-chosen)
  kudu/                      # live Kudu FS — local to this host only
  rustfs/                    # RustFS volume (S3 API :9010; see governance-scale-plane)
  flink/
  backups/<stamp>/           # portable stamps only
  logical-restore/kudu/      # staged Parquet after just restore
```

Override once: `SIGNALS_DATA_ROOT=/raid/signals` in `.env`.

**Scale:** Atlas/Ranger bulk paths use **Kudu projections** (`just gov-kudu-projections-seed`);
objects use **RustFS** on `rustfs/` — not Postgres heap. Doctrine:
[Governance scale plane](../architecture/governance-scale-plane.md).

## What is portable

| Service | Portable artifact |
|---------|-------------------|
| Atlas (`signals` PG + AGE) | `postgres/signals.dump` |
| Ranger | `postgres/ranger.dump` (+ conf if installed) |
| Catalog | `postgres/signals_catalog.dump` |
| Polaris | dump if DB exists, else `polaris.ABSENT` |
| **Kudu tables** | `logical/kudu/*.parquet` via **DataFusion** (not FS copy) |
| rustfs / flink | `filesystem/*.tgz` or `*.EMPTY` |

Kudu **on-disk** directories are never part of a successful stamp. Hostnames are
embedded in tablet metadata; cross-host restore is **logical only** (Impala scan
→ Parquet on backup; DataFusion verify + stage on restore; CREATE/INSERT on the
new cluster).

## Stamp layout

```text
$SIGNALS_BACKUP_DIR/<UTC-stamp>/
  MANIFEST.json          # path=full-portable-all-services, portable=true, status=ok
  SHA256SUMS
  postgres/
  logical/               # DataFusion package (signals-df)
    MANIFEST.json
    kudu/
  ranger-conf/
  filesystem/            # rustfs, flink only
```

Failed runs leave `FAILED` and `status=failed` — **`just restore` refuses them**.

## Requirements

| Command | Needs |
|---------|--------|
| `just backup` | **Kerberos** ticket + GSSAPI Impala HS2 on FQDN; Postgres; Kudu; `signals-df` |
| `just restore` | Postgres up; `signals-df` for logical verify; full ok stamp |

```bash
just bootstrap           # required once per machine
devenv up -d
just kerberos-status     # expect: impala HS2 GSSAPI OK
just signals-df-build    # optional; also auto-built on backup
```

Impala and Kudu **only** run with Kerberos. Clients dial `$SIGNALS_KRB_HOST`
(never `127.0.0.1`). Logical Kudu export uses `signals.impala` / `impala_query.py`
(GSSAPI only).

## DataFusion

`crates/signals-df` owns the logical plane for every table-shaped service over
time (`logical/<service>/`). Today Kudu export is Impala → CSV → Parquet; verify
and SQL scale through DataFusion without Spark.

## Atlas + OL

Atlas SoR is `signals` PG. Portable governance (+ future OL labels) rides in
`signals.dump`. Marquez-web has no separate database.
