# Kerberos

A project-local MIT Kerberos KDC runs as a devenv process.

## Configuration

| Setting | Value |
|---------|-------|
| Realm | `KRBTEST.COM` |
| KDC port | `8848` (127.0.0.1) |
| Data directory | `.devenv/kdc/` (gitignored) |

## Principals

| Principal | Type | Credentials |
|-----------|------|-------------|
| `postgres/localhost@KRBTEST.COM` | Service | Keytab at `.devenv/kdc/postgres.keytab` |
| `signals@KRBTEST.COM` | User | Password: `signals` |

## Usage

```bash
kinit signals          # Get ticket (password: signals)
klist                  # Show current tickets
kdestroy               # Destroy tickets
```

## Management

```bash
devenv tasks run signals:kdc-init    # Initialize/verify KDC
devenv tasks run signals:kdc-reset   # Reset KDC database
```

The shell automatically sets `KRB5_CONFIG`, `KRB5_KDC_PROFILE`, and `KRB5CCNAME` to project-local paths.
