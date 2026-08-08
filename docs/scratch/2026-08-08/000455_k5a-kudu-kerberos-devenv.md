# K5a: devenv Kudu Kerberos wiring

**Date:** 2026-08-08

## What landed

| Piece | Detail |
|-------|--------|
| Env | `SIGNALS_KUDU_KERBEROS=0\|1` (default **0**) |
| Keytab | `.devenv/kdc/kudu.keytab` (from `signals:kdc-init`) |
| Flags when ON | `--keytab_file`, `--principal=kudu/_HOST`, `--rpc_authentication=required`, `--rpc_encryption=optional` (override via `SIGNALS_KUDU_RPC_AUTH` / `SIGNALS_KUDU_RPC_ENCRYPTION`) |
| Processes | `kudu-master`, `kudu-tserver` in `devenv.nix` |
| Smoke | `scripts/kudu_kerberos_smoke.sh` / `just kudu-kerberos-smoke` |

## Smoke (MODE=0)

- kudu keytab has `kudu/tinybox.dev.vista.zndx.org@DEV.VISTA.ZNDX.ORG`
- signals.keytab present
- host resolves
- master UI up

## Enable secured Kudu (lab)

```bash
devenv tasks run signals:kdc-init
export SIGNALS_KUDU_KERBEROS=1
# restart only kudu processes (or full devenv up)
# Impala/FDW nosasl will fail OpenTable until K5b
just kudu-kerberos-smoke
```

## Next

**K5b:** `exec_kudu` SASL builder + cache key by principal/ccache.
