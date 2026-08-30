# Remediation: data-product inventory live, queue-share floors, PRODUCTS/WatchWorkload

Session picking up the Gaius handoff
(`180800_gaius-handoff-data-product-inventory-defects.md`). All three defect
areas remediated and verified live, plus the full protocol consumption pass.
Commits: `ebbf3ba` (inventory), `95655d5` (queue-share), `820be36` (protocol),
signals-ui `ec28b0a` + gitlink bump.

## Track A — inventory (had never been live)

- `role` → **`actor`** in `hx_exchange_*` (user decision; reserved word on this
  Impala fork). Touched kudu DDL, views, `warehouse.py` INSERT, `history.py`
  payload, ER doc.
- `apply_schema` no longer aborts at the first failure — every statement runs,
  one aggregate `WarehouseError` names each failure. `SCHEMA_SQL`, `CATALOG`,
  `BRIEF_DIR` repo-anchored (were cwd-relative).
- **tier1 via Polaris, not Impala DDL** — key discovery beyond the handoff:
  - this catalogd **auto-registers HS2 DDL** into `catalog_tables`
    (`tx_tier0`/`details_tier0` rows appeared without manual inserts), and
  - Polaris-registered Iceberg tables need **zero registration**
    (`gpu_dcgm_tier1` DESCRIBEs fine with **no** registry row — the
    signal-registry.sql:34 rollback deleted it).
  New `signals.ops.iceberg_register` (PyIceberg REST → Polaris `signals`,
  namespace `signals_dataproducts`): `tx/details/hx_exchange/hx_reasoning
  _tier1`, identity partitions on `product_id`/`e`, `signals.tier=1`, location
  from the catalog `default-base-location`. `data-products-iceberg.sql`
  retired; `pyiceberg` declared (was venv-only).
- Views rebuilt with the **tier1-masking predicate** (same as the `signal`
  view) so settle can never double-count.
- New entry point: `python -m signals.ops schema-apply` /
  `just data-products-schema` (there was NO call site before — the schema had
  only ever been applied by hand).
- Seeded `gaius.curation.cot_reasoning` (kind `reasoning`,
  `hx.cot_reasoning`, extract leaf) in `data-products.json` + ui fixture.

**Verified:** all 8 tables + 4 views exist and load; `review-product
gaius.curation.cot_reasoning` writes `tx` + `hx_reasoning` (trace retained,
no JSONL soft-fail); **survives a full `systemctl restart signals.target`**
(catalogd recycled). The earlier failed-run orphan tx `1788116515` (tx/details
rows without hx) is expected pre-fix debris.

## Track B — queue-share reconciler (extract floor was structurally impossible)

Three interlocking defects (2758 share records, **0 APPLIED**, floor never
live despite SoR commit a30c490):

1. **PromoteScratch silently failing since 2026-08-28 00:46**: engine
   inherited root-only `/etc/rancher/rke2/rke2.yaml` as `KUBECONFIG` from the
   `devenv up` shell; `ApplyConfig.from_env` even preferred ambient
   `KUBECONFIG` over `SIGNALS_YK_KUBECONFIG`. Captured live:
   `promote --dry-run` → `permission denied`. Fix: `resolve_kubeconfig()` —
   first **readable** of `SIGNALS_YK_KUBECONFIG`, `KUBECONFIG`,
   `~/.kube/{rke2.yaml,config}`, loud skip of unreadable env paths; engine
   start paths pin `SIGNALS_YK_KUBECONFIG`; the airflow task's
   `KUBECONFIG:-` default removed (its bootstrap resolves readably itself).
2. **Floor wiping**: `patch_occupancy` zeroed `guaranteed` for every
   occupancy queue with no active peer floor → declared SoR floors erased on
   every ingest. Now `max(declared baseline, merged peer floors)`;
   `BASELINE` repo-anchored (`SIGNALS_YK_BASELINE` overridable).
3. **APPLIED unreachable**: thread-per-request applier flipped only its own
   record `if state == RECORDED`, but same-peer churn superseded it first; a
   failed apply deferred forever. Now one **coalescing applier** (pending set
   of the scratch snapshot's record ids, batch flip on success, superseded
   stays SUPERSEDED, backoff retry on failure); dead gRPC context no longer
   passed to background PromoteScratch.

Plus `signals-yk diff --sor`: semantic live-vs-`federation-queues.yaml` diff
(exit 1 on drift) — the projection's scratch/current diff structurally cannot
answer "is the SoR actually promoted", which is exactly the check the handoff
tried to run from a Gaius shell. Tests rewritten to the RECORDED→APPLIED
contract (old ones asserted APPLIED synchronously — a state the code never
returned).

**Verified:** promote applied (`archive=20260830T214856Z`), live YK shows
`extract guaranteed=1 max=2` **and it survived live Gaius churn** (heavy=4
share active, newest 21:52 record **APPLIED** — first APPLIED ever);
`diff --sor` → `(live matches SoR federation-queues.yaml)`.

## Track C — PRODUCTS + WatchWorkload (full scope)

- Submodule `components/signals-protocol` 7cc9ad1 → **aab367f** (fetched from
  the Gaius checkout — commits are unpushed upstream; pushing stays with the
  user). Superseded k/v-WorkloadOffer stash verified and dropped. Python stubs
  regenerated (`just gen-zndx-engine-py`).
- **Serve**: `s2s.local_response` answers `PRODUCTS` from the warehouse
  inventory (`list_details` projection, 30 s cache; seed JSON as the degraded
  answer). Signals = warehouse of record → full federated catalog, per-hint
  peer attribution.
- **Collect**: `signals-yk collect-products` fan-out.
- **UI** (signals-ui `ec28b0a`): `collect_federation_products` (peer's own
  hint wins for its own product), `workload_snapshot` (first message off the
  held-open WatchWorkload stream), routes
  `/api/signals/v1/federation/{products,workloads}`, History page merges live
  hints (live badge + Iceberg table id), fixture seeded.

**Verified:** signals :50551 answers 7 hints (cot_reasoning carries
`hx.cot_reasoning` from warehouse facts); gaius :50051 answers its own 2;
WatchWorkload snapshot from Signals: `SETTLED`, thinking@Qwen3.8-27B SERVING.

## Smaller handoff items

- `:30080` reachable locally — confirmed (used throughout).
- `yk diff` printing nothing from a Gaius shell: structural (scratch/current
  only) + env; `--sor` is the real check now.
- queue-share "not APPLIED within 30 s": root-caused (above), fixed.

## Operational notes

- The systemd engine unit and the devenv engine process both claim :50551;
  after the target restart the systemd one won and the devenv twin `gave_up`,
  which cancelled `signals-ui` (after-chain). Resolved by stopping the unit's
  engine and letting the devenv graph own it (`just up` recycle).
- Several stale devenv daemons for this tree accumulate across restarts —
  `just up` reaps them (by cwd) by design.
