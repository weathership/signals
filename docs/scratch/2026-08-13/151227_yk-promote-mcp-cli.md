# YuniKorn P2+: promote apply + CLI + MCP + UI hook

## Done

### ConfigMap apply adapter (`PromoteScratch`)
- `src/signals/engine/k8s_apply.py` — kubectl get/patch/apply of `queues.yaml`
- Prefer `yunikorn-configs`, fallback `yunikorn-defaults` (ns `yunikorn`)
- Preserves other CM keys; strips resourceVersion noise
- `dry_run` → `kubectl apply --dry-run=server`
- On apply failure: projection **unchanged**
- Env: `SIGNALS_YK_APPLY_ENABLED`, `SIGNALS_YK_CM_*`, `KUBECONFIG`

### Declared-config normalization
- Live `GET /ws/v1/config` returns runtime keys (`checksum`, `extra`,
  `deadlock*`) that `validate-conf` rejects
- `normalize_declared_config()` keeps only `partitions` for validate/promote/GET

### CLI (`signals-yk`)
- Ops: partitions, queues, config, validate, sync, health
- Lifecycle: write-scratch, diff [--live], promote [--dry-run], archives, restore, index

### MCP (`signals-yk-mcp` / `python -m signals.mcp.yk`)
- Minimal stdio JSON-RPC (no broken `mcp` package dependency)
- Tools: yk_health, yk_partitions, yk_queues, yk_config, yk_validate, yk_sync,
  yk_write_scratch, yk_diff, yk_promote, yk_archives, yk_restore, yk_index

### UI (engine-first hook)
- `Config.engine_target` from `SIGNALS_ENGINE_TARGET` (default `127.0.0.1:50551`)
- Settings shows lattice entry; documents migrate-off-REST for `/queues`
- Full Aegir lineup rewrite still open (engine-only panels)

### Tests
- `tests/signals/test_k8s_apply.py`
- `tests/signals/test_promote_servicer.py`
- `tests/signals/test_mcp_yk_tools.py`
- `tests/signals/test_normalize_config.py`
- 16 passed

### Live smoke (lab)
```
promote --dry-run → ok; validation allowed; CM yunikorn-configs server dry-run
MCP yk_health → healthy
```

## Still open
- signals-ui `/queues` full Aegir lineup over engine gRPC (tonic client)
- Optional live promote CI gate (elevated `*-ci`, not smoke)
- Peer lock-in commits (ops hygiene)
