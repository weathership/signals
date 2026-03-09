# Configuration

## Key Files

| File | Purpose |
|------|---------|
| `devenv.nix` | Packages, services, processes, tasks, shell configuration |
| `devenv.yaml` | Nix inputs configuration |
| `.envrc` | direnv integration |
| `.env` | Runtime environment variables (dotenv) |
| `scripts/kdc-init.sh` | Idempotent KDC initialization |

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `KRB5_REALM` | `KRBTEST.COM` | Kerberos realm |
| `KRB5_KDC_PORT` | `8848` | KDC listener port |
| `KRB5_CONFIG` | `.devenv/kdc/krb5.conf` | krb5 client config (set by shell) |
| `KRB5_KDC_PROFILE` | `.devenv/kdc/kdc.conf` | KDC server config (set by shell) |
| `KRB5CCNAME` | `.devenv/kdc/krb5cc` | Credential cache (set by shell) |
