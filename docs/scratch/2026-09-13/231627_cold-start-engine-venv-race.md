# Cold-start engine/venv race (2026-09-13)

After a federated `signals.target` stop (RKE2 data-dir move), `systemctl start
signals.target` brought the foundation, peers, and Hermes back, but
`signals-engine.service` failed:

```
ModuleNotFoundError: No module named 'grpc'
timed out waiting for Status on :50551
```

## What actually happened

1. Foundation `just up` started `processes.signals-engine` as `uv run python -m
   signals.engine`. On this cold start that `uv run` **re-synced** the devenv
   venv (torch/CUDA/grpcio, many minutes) and held `.devenv/state/venv/.lock`.
2. `signals-ready` is the *critical plane* (PG/Kudu/Impala), not the Python
   engine. It went active while uv was still downloading.
3. `signals-engine.service` (After=ready) spawned a **second** interpreter
   against `.devenv/state/venv/bin/python`. The binary existed; grpc did not.
   60s Status poll failed. Type=oneshot RemainAfterExit, **no Restart=**.
4. `signals-heal` saw foundation active and **no-op'd** ("letting Restart
   converge"). The engine stayed failed.

## Remediation

- `signals_python_path` requires `import grpc` (rc=2 if the venv is half-built).
- Engine/C2 systemd wrappers are membership hooks: wait for compose-owned
  Status/healthz (grpcurl, so the wait does not need grpc in the venv). Do not
  spawn while `python -m signals.engine` is already running in this checkout.
- devenv: task `signals:uv-sync` before the engine process; process exec uses
  the venv binary (no `uv run` at start).
- Heal: if refresh is not active, reset-failed + `start signals.target` (does
  not recycle live peers).
- TimeoutStartSec=1200 on the engine unit (Gaius-class cold start).
- Gate: `just signals-cold-start-ci` (script contracts + complete recycle +
  lattice-ci). Routine, not a smoke.
- `uv run` (ready probes + engine exec) syncs the **dev** group →
  sentence-transformers → torch/CUDA onto `~/.cache/uv` on `/`. Hundreds of
  overlapping Status probes filled root from 86 Gi free to 2 Gi and kubelet
  DiskPressure-evicted ingress/dcgm. Cache now `/raid/cache/uv`;
  `signals:uv-sync` is `uv sync --frozen --no-dev`.

## RKE2 (same window)

`data-dir: /raid/rancher/rke2` in `/etc/rancher/rke2/config.yaml`. Old
`/var/lib/rancher` removed. Node Ready, DiskPressure=False, `/` ~86G free.
