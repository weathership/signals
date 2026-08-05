# Kerberos

A project-local MIT Kerberos KDC runs as a devenv process. Naming follows the
ZNDX host taxonomy, with the **environment segment in the realm** (not only in DNS).

## Naming model

| Layer | Value |
|-------|--------|
| Org TLD | `zndx.org` |
| Location | `vista` |
| Environment / posture | `dev` → realm segment **`DEV`** |
| Host short name | `tinybox` |
| Cloudflare / FQDN | **`tinybox.dev.vista.zndx.org`** |
| Kerberos realm | **`DEV.VISTA.ZNDX.ORG`** = `{ENV}.{LOCATION}.ZNDX.ORG` |
| User principal | `signals@DEV.VISTA.ZNDX.ORG` |
| PostgreSQL role | **`signals`** (primary only; realm stripped via `pg_ident`) |

Pattern:

- FQDN: `{host}.{env}.{location}.zndx.org`
- Realm: `{ENV}.{LOCATION}.ZNDX.ORG` (uppercase)
- PG / app role: Kerberos **primary** only — env lives in the realm, not the role name

Examples:

| Principal | PG role |
|-----------|---------|
| `signals@DEV.VISTA.ZNDX.ORG` | `signals` |
| `signals@STAGE.VISTA.ZNDX.ORG` | `signals` (different realm / KDC) |
| `analyst@DEV.VISTA.ZNDX.ORG` | `analyst` |

## Configuration

| Setting | Value |
|---------|-------|
| Realm | `DEV.VISTA.ZNDX.ORG` |
| Principal instance (FQDN) | `tinybox.dev.vista.zndx.org` |
| KDC port | `8848` (127.0.0.1) |
| Data directory | `.devenv/kdc/` (gitignored) |
| Env overrides | `KRB5_REALM`, `SIGNALS_KRB_ENV`, `SIGNALS_KRB_LOCATION`, `SIGNALS_KRB_HOST`, `KRB5_KDC_PORT` |

`kdc-init.sh` builds the default realm from `SIGNALS_KRB_ENV` + `SIGNALS_KRB_LOCATION` unless `KRB5_REALM` is set explicitly.

### Local DNS

```bash
echo '127.0.0.1 tinybox.dev.vista.zndx.org' | sudo tee -a /etc/hosts
```

## Principals

| Principal | Type | Credentials |
|-----------|------|-------------|
| `postgres/tinybox.dev.vista.zndx.org@DEV.VISTA.ZNDX.ORG` | Service (PG GSSAPI) | `.devenv/kdc/postgres.keytab` |
| `impala/tinybox.dev.vista.zndx.org@DEV.VISTA.ZNDX.ORG` | Service (Impala HS2) | `.devenv/kdc/impala.keytab` |
| `HTTP/tinybox.dev.vista.zndx.org@DEV.VISTA.ZNDX.ORG` | Service (Atlas/Ranger SPNEGO) | `.devenv/kdc/http.keytab` |
| `kudu/tinybox.dev.vista.zndx.org@DEV.VISTA.ZNDX.ORG` | Service (Kudu) | `.devenv/kdc/kudu.keytab` |
| `signals@DEV.VISTA.ZNDX.ORG` | User (PG role + FDW outbound) | Password: `signals` |
| `signals/admin@DEV.VISTA.ZNDX.ORG` | Admin (optional) | Password: `signals` |

### End-to-end identity (impala_fdw)

Target: authenticate to Postgres with **GSSAPI** as `signals@DEV.VISTA.ZNDX.ORG`,
map to PG role `signals`, then have `impala_fdw` use that **same principal** for
Impala HS2 and Kudu. See `components/impala_fdw/docs/SPEC.md` §11.3.

Example `pg_ident` idea (also written to `.devenv/kdc/pg_ident.map.example` on init):

```
# signals@DEV.VISTA.ZNDX.ORG → signals
krb_map  /^(.*)@DEV\.VISTA\.ZNDX\.ORG$  \1
```

## Usage

```bash
kinit signals          # default_realm is DEV.VISTA.ZNDX.ORG
# or: kinit signals@DEV.VISTA.ZNDX.ORG
klist
kdestroy
```

## Management

```bash
devenv tasks run signals:kdc-init    # Initialize/verify KDC
devenv tasks run signals:kdc-reset   # Reset KDC database (required after realm renames)
# or: just kdc-reset
```

### Migration from older realms

Prior checkouts used `KRBTEST.COM` or location-only `VISTA.ZNDX.ORG`. After pulling
env-in-realm naming (`DEV.VISTA.ZNDX.ORG`):

```bash
devenv tasks run signals:kdc-reset
kdestroy   # discard old tickets
```
