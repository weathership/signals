# Peer Data Products (RustFS)

What another Signals project needs in order to **formally maintain its
own data product** on the shared object plane. Contract:
[signals-protocol data products](../../../components/signals-protocol/specification/protocol/data_products.md).
Warehouse internals: [Data Products History](../architecture/data-product-history.md).

Signals runs the warehouse and RustFS. The peer runs the **flow** that
produces the product and the **ACP observation** of what that flow
retained. Gaius `prospects` is the next consumer of this shape.

## 1. Do not build a second warehouse

| Peer does | Peer does not |
|-----------|----------------|
| Own `{peer}.{domain}.{name}` | Create `details` / `tx` / `hx` tables |
| Write **bytes** to RustFS | Copy product rows into Gaius/Ægir/Atelier Postgres |
| Point Metaflow at platform profile | Use `METAFLOW_DEFAULT_DATASTORE=local` on the shared host |
| Emit `dev.signals.dataproduct.updated` + UUIDv7 `tx_id` | Mint v4 ids or rewrite a rejected id |
| Fill quality / lineage / delta / nominal on `hx_*` | Re-inventory in the UI or a JSON file |
| Stamp a resource-class YK queue | Invent `root.gaius` / `root.aegir` |

pglite (`:5455`) is Signals admin (AGE, Ranger). Peer PG ports stay
engine-private. **Never bind RustFS `:9010`.**

## 2. Object plane

Lab: `http://127.0.0.1:9010` (`peer-contract.json` → `endpoints.rustfs_s3`).
In-cluster: `http://signals-rustfs.metaflow.svc.cluster.local:9010`.

| Bucket / prefix | Use |
|-----------------|-----|
| `s3://metaflow/metaflow/` | Platform Metaflow CAS (code package, artifacts, env) |
| `s3://signals-dataproducts/` | Iceberg warehouse + optional `{peer}/…` blobs |

Copy `config/metaflow/platform.json` (or `METAFLOW_PROFILE=platform`):

```json
{
  "METAFLOW_DEFAULT_METADATA": "service",
  "METAFLOW_SERVICE_URL": "http://127.0.0.1:30180",
  "METAFLOW_DEFAULT_DATASTORE": "s3",
  "METAFLOW_DATASTORE_SYSROOT_S3": "s3://metaflow/metaflow",
  "METAFLOW_S3_ENDPOINT_URL": "http://127.0.0.1:9010"
}
```

Fail closed if datastore is `local`, unset, a foreign bucket, or an
endpoint that is not RustFS. Signals enforces this in
`signals.ops.metaflow_store.require_rustfs`.

Product **facts** name the URI. A prospects parquet that landed at
`s3://signals-dataproducts/gaius/prospects/{run}/…` is the object; the
`details` row is the claim that it exists and is current.

## 3. Register the product

Stable id, peer prefix, YK **leaf** (resource class, not project):

```text
gaius.prospects.<name>
peer: gaius
kind: corpus | cognition | snapshot | …
leaf: root.internal.inference.extract   # example — pick the class that matches the work
```

`config/platform/data-products.json` is a **seed** for a first INSERT,
then retired. After that, SoR is the Impala views over Kudu + Iceberg.
Ask Signals to seed once, or call `signals.ops.history.record_event` /
`review` with the product dict.

Do not add a History row in signals-ui by editing HTML.

## 4. Map the Metaflow run into `details`

Each successful run is one `tx` (`kind` = `updated` | `snapshot` | peer
kind, `source` = the peer). `tx_id` is UUIDv7 (Signals can mint; if the
peer mints, it **must** be v7).

Map at least:

| Fact (`a`) | Typical `v` |
|------------|-------------|
| `peer`, `title`, `kind`, `leaf`, `agent_focus` | Catalog identity |
| `flow_name`, `run_id`, `pathspec` | Metaflow identity |
| `snapshot_uri` | `{sysroot}/{flow}/{run}` |
| `data_uri` | `{sysroot}/{flow}/data` (CAS) |
| `code_package`, `code_package_sha` | Immutable source |
| `deps` | `@conda` / `@pypi` / default |
| `yk_app_id`, `yk_queue` | Admission claim |
| `object_store`, `datastore_root`, `rustfs_endpoint` | Must be RustFS |

Keep every retained version with `run.{flow}/{run_id}.*` so latest-wins
does not erase prior snapshots. `latest_*` is the current run only.

Reference: `signals.ops.metaflow_store.facts_from_run` (first product
`signals.metaflow.snapshots`).

```bash
# Signals-side record after a platform run (peer can wrap this)
uv run python -m signals.ops review-product gaius.prospects.corpus \
  --kind updated --summary 'prospects flow run 12'
```

Non-v7 `tx_id` → warehouse refuses → `Engine/Remediate` on **Gaius**
(`TX_ID_NOT_UUIDV7`, `capability=reauthor`). Gaius remints and
resubmits. Signals does not rewrite the id.

## 5. ACP assessment is part of the product

`hx_reasoning` on the same `tx_id` is not optional decoration. Empty
quality / lineage / delta means History is a changelog.

For a prospects (or any operational) flow, the agent **observes**:

1. **Quality** — is the retained object complete and on RustFS?
2. **Lineage** — pathspec, code sha, YK app, Atlas OL job
3. **Delta** — this run vs prior `latest_run_id` / last corpus pin
4. **Nominal** — did the method stay on its legal path? Holding is
   in-progress, not failure and not done.

Walk `data-product.history-review` to `understood` when the observation
is complete, `failed` when off-nominal. Do not treat a holding upkeep
or a still-running curate as terminal.

Signals' first product uses agent `acp-observer` for that walk. A Gaius
prospects flow should pass its method `doc` (FSM current, inputs/outputs)
into the same shape so an agent can say "proceeding nominally" without
re-deriving the warehouse.

**Peers do not implement `data-product.tier-upkeep`.** That ADD / copy /
verify / `DROP RANGE PARTITION` walk is Signals-owned. A peer flow that
drops Kudu ranges is off-nominal by construction.

## 6. Queue and process

| Work | Queue |
|------|--------|
| Prospects GPU extract / OCR | `root.internal.inference.extract` |
| Instruct / short generation | `root.internal.inference.instruct` |
| Embeddings | `root.internal.inference.embedding` |
| Platform Metaflow/Airflow itself | `root.platform` |
| Grok ACP review | `root.external.subscription.rate-limited` |

Stamp `yunikorn.apache.org/queue`, `yunikorn.apache.org/app-id`,
`federation.project=gaius` (or aegir / atelier). Project is a **label**,
not the queue parent. See
[Peer integration](./peer-integration.md#how-to-organize-work-on-queues).

Schedule the flow with **Airflow** (`airflow create` or API trigger) on
platform Metaflow. Publish `dev.signals.dataproduct.updated` (and
optionally `dev.metaflow.flow.finished`) to the Knative Broker
`signals-events/default`.

## 7. Gaius prospects (checklist)

1. `git submodule update --remote` on `signals-protocol` (trunk after
   `TX_ID_NOT_UUIDV7` + data-products spec). Regen engine stubs.
2. Implement `Remediate` for `TX_ID_NOT_UUIDV7` (remint v7).
3. Flow uses platform Metaflow + RustFS profile — no local datastore.
4. Choose `gaius.prospects.*` (or keep `gaius.cognition.outputs` if that
   **is** the product). Seed once via Signals.
5. `end` step: map run → facts; record `tx` + `details` + `hx`; include
   the method walk so nominal can be scored.
6. Objects live at `s3://metaflow/metaflow/…` and/or
   `s3://signals-dataproducts/gaius/…`. Facts store those URIs.
7. Do not write prospects rows to Gaius PG `:5444` as SoR.
8. Do not DROP warehouse partitions. Do not bind `:9010` or `:5455`.

## 8. Where to look in this tree

| Piece | Path |
|-------|------|
| Contract | `components/signals-protocol/specification/protocol/data_products.md` |
| UUIDv7 + Remediate | `…/protocol/tx_id.md`, `SignalKind.TX_ID_NOT_UUIDV7` |
| Seed catalog | `config/platform/data-products.json` |
| Writer | `src/signals/ops/history.py`, `src/signals/ops/warehouse.py` |
| Snapshot mapping | `src/signals/ops/metaflow_store.py` |
| Platform Metaflow | `config/metaflow/platform.json` |
| Endpoints | `config/platform/peer-contract.json` |
