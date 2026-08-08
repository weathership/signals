# SIGNALS_DATA_ROOT=/raid/signals + just backup

**Date:** 2026-08-08

## Done

- `scripts/signals_data_root.sh` — resolve root, ensure kudu/rustfs/flink/backups
- devenv: `env.SIGNALS_*`, Kudu processes use `$SIGNALS_KUDU_HOME` (not `.devenv/kudu`)
- task `signals:data-layout` before kudu-master/tserver
- `scripts/backup-stack.sh` / `restore-stack.sh` + `just backup` / `just restore`
- Docs: `operations/storage-and-backup.md`

## Verified

Live `just backup --services atlas,ranger` →  
`/raid/signals/backups/<stamp>/postgres/{signals,ranger}.dump`
