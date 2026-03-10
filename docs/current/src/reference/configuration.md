# Configuration

## Key Files

| File | Purpose |
|------|---------|
| `devenv.nix` | Packages, services, processes, tasks, shell configuration |
| `devenv.yaml` | Nix inputs configuration |
| `.envrc` | direnv integration |
| `.env` | Runtime environment variables (dotenv) |
| `scripts/kdc-init.sh` | Idempotent KDC initialization |
| `pyproject.toml` | Python project config (dependencies, dev tools) |
| `Tiltfile` | Tilt dev iteration config (image builds, port forwards) |

## Infrastructure Configuration

| File | Purpose |
|------|---------|
| `infra/aws/tofu/variables.tf` | OpenTofu variable definitions |
| `infra/aws/tofu/terraform.tfvars` | Shared deployment defaults |
| `infra/aws/ansible/group_vars/all.yml` | Ansible shared variables |
| `zarf/zarf.yaml` | Air-gap package definition |
| `policy/tofu/*.rego` | OPA policies for OpenTofu plans |
| `policy/k8s/*.rego` | OPA policies for Kubernetes |

## Environment Variables

### Kerberos

| Variable | Default | Purpose |
|----------|---------|---------|
| `KRB5_REALM` | `KRBTEST.COM` | Kerberos realm |
| `KRB5_KDC_PORT` | `8848` | KDC listener port |
| `KRB5_CONFIG` | `.devenv/kdc/krb5.conf` | krb5 client config (set by shell) |
| `KRB5_KDC_PROFILE` | `.devenv/kdc/kdc.conf` | KDC server config (set by shell) |
| `KRB5CCNAME` | `.devenv/kdc/krb5cc` | Credential cache (set by shell) |

### AWS / Cloudflare (set for deployment)

| Variable | Purpose |
|----------|---------|
| `AWS_REGION` | AWS region for provisioning |
| `CLOUDFLARE_TUNNEL_TOKEN` | Tunnel credentials (from tofu output) |
| `CLOUDFLARE_TUNNEL_ID` | Tunnel identifier (from tofu output) |

## Project Structure

```
signals-360/
├── components/          # ASF submodules (atlas, ranger, kudu, ...)
├── docs/
│   ├── current/         # mdbook documentation
│   └── scratch/         # Work notes
├── features/            # BDD feature specifications
│   ├── agent/           # S01-S03 scenarios
│   ├── analytics/       # S04-S06 scenarios
│   └── platform/        # Infrastructure scenarios
├── infra/               # Deployment infrastructure
│   └── aws/             # OpenTofu + Ansible
├── policy/              # OPA Rego policies
├── scripts/             # Shell scripts (kdc-init)
├── tilt/                # Tilt dev overlays
├── zarf/                # Air-gap packaging
├── devenv.nix           # Development environment
├── pyproject.toml       # Python project config
└── Tiltfile             # Tilt configuration
```
