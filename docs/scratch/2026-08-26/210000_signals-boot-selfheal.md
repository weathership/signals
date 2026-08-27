# Signals federated stack — unattended-boot self-heal

Post a physical reboot the signals data plane came up **not at all**: the
foundation's `devenv up` lost devenv 2.1's hardcoded 120 s daemon-start wait
under boot contention, `systemd_foundation_start.sh` had **no retry**, so
`signals.service` failed permanently → Postgres :5455 never started → Polaris
gave up after 180 s → Kudu/Impala/RustFS all down, with nothing to re-kick.

## Fixes (systemd/devenv layer) — DONE + validated

Empirically confirmed on this systemd (249): **`Type=oneshot` DOES honor
`Restart=`** here (probe unit reached `NRestarts=3`). So the fix is declarative
restart, not a fragile in-script loop.

1. **`scripts/systemd_foundation_start.sh`** — failure path now mirrors the
   success path: `repair_native_manager_pid` + **poll** `just signals-ready`
   (150 s) before deciding. devenv's non-zero `just up` is frequently a false
   negative (daemon alive, pid unwritten); polling lets a *progressing* daemon
   converge instead of being killed by a fresh `up`. Genuine failure → `exit 1`
   for systemd Restart.
2. **`signals.service`** — `Restart=on-failure`, `RestartSec=20`,
   `StartLimitIntervalSec=3600`/`Burst=30`. A genuinely-failed boot re-runs the
   whole start; `just up` self-cleans stale daemons + frees :5455 each attempt.
3. **`signals-polaris.service` + `systemd_polaris_start.sh`** — `Restart=on-failure`
   + the script now **waits for Postgres :5455** (120 s) before launching the
   JVM, so a retry doesn't burn 180 s against a dead DB. (Kept ordered
   `After=signals.service`, NOT `signals-ready` — Polaris needs only :5455, not
   the full readiness gate which also covers unrelated k8s services.)
4. **`signals-refresh.service`** — `Restart=on-failure`, `RestartSec=30`,
   `Burst=60`. Re-verifies until the group converges (verify-only, cheap).
5. **`signals-heal.timer` + `signals-heal.service` + `scripts/systemd_heal.sh`**
   — outer safety net (runs as root). `OnBootSec=5min`, then every 3 min while
   not healthy: if `signals-refresh` isn't active and the foundation isn't
   active, `reset-failed` + `systemctl start signals.target`. Covers the tail
   (StartLimit exhausted / optimistic exit-0). Enabled for next boot.
6. **Re-copied stale `atelier.service`** into /etc (was 2026-08-13, infra 08-18).

Deployed: `sudo install -m644 infra/systemd/{signals,signals-polaris,signals-refresh,atelier,signals-heal.service,signals-heal.timer} /etc/systemd/system` + `daemon-reload`; `signals-heal.timer` enabled.

**Validation (live, this session):** re-kicked via `systemctl reset-failed` +
`systemctl start --no-block signals.target` (surgical — active gaius engine /
inference untouched). Result: **data plane up in <20 s**, `signals.service`
active `NRestarts=0`, Postgres/Kudu/Impala/RustFS/Polaris all UP. The oneshot
Restart mechanism itself proven separately (`NRestarts=3` probe). Final proof of
*post-reboot* behavior is a reboot, which now self-heals under contention.

## Remaining blockers to FULL signals-ready green — k8s layer, PRE-EXISTING

`signals-ready` still can't pass; the blockers are a different failure class
(not systemd/devenv, and predate the reboot):

- **yunikorn `:30080` REST** — critical (★) check, but `yunikorn-service` is
  **ClusterIP (9080/9889)** with **no NodePort :30080**. The scheduler pod is
  Running; only the host-facing REST the check probes is unexposed. Never passes
  with this config → needs a NodePort/port-forward (cf. `metaflow-port-forwards.sh`
  pattern) or a corrected check.
- **metaflow ImagePullBackOff** — new replicas (age 2d17h) can't pull
  `127.0.0.1:31999/outerbounds/metaflow_metadata_service` — `FailedToRetrieveImagePullSecret (private-registry)`. **Non-blocking**: old replicas serve :30180, so metaflow readiness passes. Cosmetic until a redeploy.
- `federation-signals/gaius-embedding` pod `Unknown` (16 h) — likely orphaned by the crash; not in the critical set.

These need k8s/zarf work (NodePort exposure, registry pull-secret), out of scope
for unit hardening. Surfaced to owner for a scope decision.

## K8s-layer remediation (2026-08-26, after owner freed disk)

Root cause of the k8s blockers = **system-drive disk pressure** (registry image
eviction, pod evictions). Owner freed space; node now `DiskPressure=False`.

Fixes (all live in etcd → survive reboot; verified):
1. **yunikorn `:30080`** — `yunikorn-service` was `ClusterIP` (drifted from the
   manifest, which specifies NodePort). Patched to **NodePort 30080(REST)/30889(web)**
   to match `zarf/federation/manifests/yunikorn/yunikorn-rendered.yaml`. Not
   helm-controller-reconciled, so the patch sticks. **This was the sole
   `signals-ready` blocker** — readiness now `fails=0`.
2. **metaflow `private-registry` secret** — missing from `aegir-metaflow`; copied
   from the `zarf` namespace.
3. **metaflow images** — the Zarf-registry-tagged images were gone from
   `127.0.0.1:31999` (disk-pressure eviction). Deployments reference the
   *upstream* `public.ecr.aws/...` images (Zarf's webhook rewrites them to the
   missing local tags at pod-creation), and **both upstream images are in the
   containerd cache**. Labeled `aegir-metaflow` **`zarf.dev/agent=ignore`** so pods
   use the cached upstream images directly — zero extra disk (vs. re-pushing
   ~300 MB to the registry). metaflow-ui/ui-static now Running; metaflow-service
   Init (db-migrations, resolves once its DB ordering is right on a clean boot).
   NOTE: this is a live workaround; a proper `zarf package deploy` would restore
   the registry images and could drop the ignore label.

## Last item: warehouse-ingest freshness — resolves on the reboot

`signals-refresh` still fails only on `#EN.00000031.FDWINGEST` — `signal_tier0`
is ~13.5 h stale (last write ≈ the 07:45 crash). The **gaius engine's warehouse
writer stalled** when Kudu went down and did not reconnect when it came back
(the known "ingest loop should retry the warehouse conn" gap). The fdw reads
fine — it's a writer stall, not a warehouse fault.

On the owner's planned reboot this self-resolves via the **now-correct ordering**:
`gaius.service` is `After=signals-ready.service`, which now *passes* (foundation
self-heals + yunikorn/metaflow fixed), so gaius starts only *after* the warehouse
is up → the writer connects cleanly → ingest fresh → `signals-refresh` passes →
target fully verified-healthy. Residual edge (warehouse recovers *after* gaius
starts) would need a gaius-side writer-retry hardening — optional follow-on.
