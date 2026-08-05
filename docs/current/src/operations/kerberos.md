# Kerberos

A project-local MIT Kerberos KDC runs as a devenv process. Naming follows the
ZNDX host taxonomy (realistic for Vista lab identity), while the KDC itself
listens only on loopback.

## Naming model

| Layer | Value |
|-------|--------|
| Org TLD | `zndx.org` |
| Location | `vista` → realm **`VISTA.ZNDX.ORG`** |
| Posture | `dev` (in DNS label, not a separate realm) |
| Host | `tinybox` |
| Cloudflare / FQDN | **`tinybox.dev.vista.zndx.org`** |

Pattern: `{host}.{posture}.{location}.zndx.org`  
Realm is **location-oriented**; posture lives only in the hostname.

## Configuration

| Setting | Value |
|---------|-------|
| Realm | `VISTA.ZNDX.ORG` |
| Principal instance (FQDN) | `tinybox.dev.vista.zndx.org` |
| KDC port | `8848` (127.0.0.1) |
| Data directory | `.devenv/kdc/` (gitignored) |
| Env overrides | `KRB5_REALM`, `SIGNALS_KRB_HOST`, `KRB5_KDC_PORT` |

### Local DNS

SPNs use the FQDN. Map it to loopback if not already resolvable:

```bash
echo '127.0.0.1 tinybox.dev.vista.zndx.org' | sudo tee -a /etc/hosts
```

Cloudflare DNS for `*.dev.vista.zndx.org` is for external naming; the devenv KDC
is **not** exposed via Cloudflare.

## Principals

| Principal | Type | Credentials |
|-----------|------|-------------|
| `postgres/tinybox.dev.vista.zndx.org@VISTA.ZNDX.ORG` | Service | `.devenv/kdc/postgres.keytab` |
| `impala/tinybox.dev.vista.zndx.org@VISTA.ZNDX.ORG` | Service | `.devenv/kdc/impala.keytab` |
| `HTTP/tinybox.dev.vista.zndx.org@VISTA.ZNDX.ORG` | Service (Atlas/Ranger SPNEGO) | `.devenv/kdc/http.keytab` |
| `kudu/tinybox.dev.vista.zndx.org@VISTA.ZNDX.ORG` | Service | `.devenv/kdc/kudu.keytab` |
| `signals@VISTA.ZNDX.ORG` | User | Password: `signals` |
| `signals/admin@VISTA.ZNDX.ORG` | Admin (optional) | Password: `signals` |

## Usage

```bash
kinit signals          # default_realm is VISTA.ZNDX.ORG
# or: kinit signals@VISTA.ZNDX.ORG
klist
kdestroy
```

## Management

```bash
devenv tasks run signals:kdc-init    # Initialize/verify KDC
devenv tasks run signals:kdc-reset   # Reset KDC database (required after realm renames)
```

The shell sets `KRB5_CONFIG`, `KRB5_KDC_PROFILE`, and `KRB5CCNAME` to project-local
paths under `.devenv/kdc/`.

### Migration from `KRBTEST.COM`

Older checkouts used toy realm `KRBTEST.COM` and `postgres/localhost` SPNs. After
pulling the ZNDX naming change:

```bash
devenv tasks run signals:kdc-reset
```

Discard any cached tickets (`kdestroy`) and old keytabs under `.devenv/kdc/`.
