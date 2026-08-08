# YuniKorn submodule + PR-K5 plan verification

**Date:** 2026-08-07

## Submodule: `components/yunikorn-core`

| Item | Value |
|------|--------|
| URL | `git@github.com:rch/asf-yunikorn-core.git` |
| Path | `components/yunikorn-core` |
| Branch | **`rch/devenv`** (created = `origin/master` @ `54fa576`) |
| Remote | `origin/rch/devenv` pushed |
| `.gitmodules` | `branch = rch/devenv` |

Matches the ASF component pattern (`atlas`, `kudu`, `impala`, … on `rch/devenv`).

**Note:** YuniKorn is the universal scheduler core (Go). It is **orthogonal** to PR-K5 (Kudu Kerberos for impala_fdw). Tracked here so devenv consumers share one submodule pin; wiring into `devenv.nix` / process-compose is a follow-on (not K5).

### Superproject git state

```
git add .gitmodules components/yunikorn-core
# submodule commit 54fa576d24fbf7b658992b5382c74d9b85125e30
```

(Not auto-committed; leave to user.)

## PR-K5 verification (Kerberos for `kudu_scan`)

Binding design expanded in `components/impala_fdw/docs/kudu_scan.md` §PR-K5 (rev 0.2.7).

### What already exists

- Principal resolution: `impala_fdw_resolve_principal` (mapping / role@realm)
- SPEC §11.3 one-principal model + stages S0–S6 (S3 = Kudu same principal)
- Lab path nosasl + dual executor proven (K0–K4)

### Gaps K5 must close

1. **HS2 kerberos still a stub** (`exec_impala.cpp`) — S2 incomplete
2. **Kudu builder** has no SASL/auth flags yet
3. **Client cache key** is masters-only → must include principal/ccache
4. **Devenv Kudu** not yet Kerberos-enforced (S0 lab)

### Recommended train

| Step | Work |
|------|------|
| K5a | Devenv: Kudu Kerberos SPNs + flags; unauthenticated clients fail |
| K5b | `exec_kudu` SASL builder + ccache/keytab; cache key expansion |
| K5c | Same principal as resolved for HS2; EXPLAIN/auth logging |
| K5d | (Recommended same train) HS2 GSS/SASL so S2+S3 land together |
| K5e | CI stays nosasl; tier-1 kerberos scenario opt-in |

### API anchors (verified)

- `KuduClientBuilder::sasl_protocol_name` (Impala default `"kudu"`)
- `require_authentication(true)`
- `import_authentication_credentials` / `ExportAuthenticationCredentials`
- Lab first: mechanism **C/D** (ticket cache / keytab), not full delegation A/B

### Exit criteria (product)

- `auth=kerberos` + `kudu_scan` succeeds as `signals@DEV.VISTA.ZNDX.ORG`
- Forced wrong principal fails closed
- nosasl CI/latency gates unchanged
- Warm-path cache still hits for same principal (N4 still valid)

