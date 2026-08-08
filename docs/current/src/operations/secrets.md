# Secrets (SecretSpec)

Signals uses [SecretSpec](https://secretspec.dev/) with [devenv integration](https://devenv.sh/integrations/secretspec/)
so secrets are **declared** in-repo and **provided** per environment.

## Layout

| File | Role |
|------|------|
| `secretspec.toml` | Declares secret *names* and descriptions — **never values** |
| `devenv.yaml` → `secretspec:` | Enables SecretSpec (`provider: dotenv`, `profile: default`) |
| `.env` (gitignored) | Local provider for dotenv; copy from `.env.example` |
| `devenv.nix` `env` | **Non-secret** identity: realm, host, ports (`KRB5_REALM`, `SIGNALS_KRB_ENV`, …) |

## Kerberos + env segment

| Concern | Where |
|---------|--------|
| Realm `DEV.VISTA.ZNDX.ORG` | `devenv.nix` / `KRB5_REALM` (not a secret) |
| PG role `signals` | Principal primary via `pg_ident` |
| Keytab **paths** | SecretSpec: `SIGNALS_KRB_USER_KEYTAB`, `POSTGRES_KRB_KEYTAB`, … |
| Live TGTs | Runtime (`kinit` / `KRB5CCNAME`) — not long-lived SecretSpec values |

Align SecretSpec **profile** with `SIGNALS_KRB_ENV` when using multi-env:

| Profile | Typical realm |
|---------|----------------|
| `default` / `dev` | `DEV.VISTA.ZNDX.ORG` |
| `stage` | `STAGE.VISTA.ZNDX.ORG` |

```bash
devenv --secretspec-profile dev shell
# or CI:
devenv --secretspec-provider env --secretspec-profile stage shell
```

## Local workflow

```bash
cp .env.example .env          # edit as needed
just kdc-reset                # mints .devenv/kdc/*.keytab including signals.keytab
# optional in .env:
# SIGNALS_KRB_USER_KEYTAB=.devenv/kdc/signals.keytab
# POSTGRES_KRB_KEYTAB=.devenv/kdc/postgres.keytab

devenv shell                  # SecretSpec + dotenv enabled
secretspec run -- just tag default.my_table
```

Interactive lab uses `kinit signals` (password) or a user keytab — **Kerberos is
the expected path for signals users**, not an optional add-on. Headless / FDW
jobs prefer `SIGNALS_KRB_USER_KEYTAB` from SecretSpec.

**Federation:** Signals is the first adopter of Kerberos + SecretSpec. Sibling
projects (engines, ACP agents) must follow the binding procedures in the
**signals-protocol** submodule:

`components/signals-protocol/specification/operations/kerberos_and_secretspec.md`

That document covers principal catalog, shared secret names, keyring/sops
providers, `secretspec run` + `kinit` wrappers, and Ranger onboarding—so every
process that hits Impala/Kudu/Ranger has a principal without ambient shell
secrets.

## Declared secrets (summary)

See `secretspec.toml` for the full list. Groups:

- **Kerberos keytab paths** — client + postgres/impala/kudu/HTTP service keytabs  
- **LLM / Atlas** — `ANTHROPIC_API_KEY`, `CEREBRAS_API_KEY`, `SIGINT_ATLAS_PASSWORD`, …

All Kerberos-related secrets are `required = false` so pure local `kdc-init` works without SecretSpec values.

## Providers

| Provider | Use |
|----------|-----|
| `dotenv` | Default local (`.env`) |
| `env` | CI: secrets already in the environment |
| `keyring` | Per-machine OS keyring |
| `sops` / others | Shared encrypted stores when you add them |

```bash
devenv --secretspec-provider env shell
secretspec run -- uv run pytest tests/sigint/ -v
```

## Relation to HOCON

Pipeline config still flows **CLI > env > `config/base.conf`**. SecretSpec is how
those env vars get into the process for secret-bearing runs; HOCON still reads
`${?ANTHROPIC_API_KEY}` etc. Do not put secrets in `config/base.conf`.

## What not to put in SecretSpec

- Realm / host / port (non-secret config)
- Ticket cache contents (short-lived)
- Keytab *bytes* in git (paths or encrypted providers only)
