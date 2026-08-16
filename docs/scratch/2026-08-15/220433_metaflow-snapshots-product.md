# First data product: Metaflow run snapshots

`signals.metaflow.snapshots` is the first Signals-owned product. Metaflow
already retains an immutable (code, data, deps) triple per run; we map that
into Kudu `details` and fail closed unless the datastore is RustFS.

## Mapping

| Metaflow | details fact |
|----------|--------------|
| flow / run | `flow_name`, `run_id`, `pathspec` |
| code package URL/sha | `code_package`, `code_package_sha` |
| `{sysroot}/{flow}/data` CAS | `data_uri` |
| `{sysroot}/{flow}/{run}` | `snapshot_uri` |
| conda/pypi/default | `deps` |
| YK proxy or k8s step | `yk_app_id`, `yk_queue` |

Product `e` stays `signals.metaflow.snapshots`. `latest_*` is the current
run; `run.{flow}/{run_id}.*` keeps every retained snapshot in the projection.

ACP brief adds **Snapshot retained (net result of the flow)** — quality of
the triple on RustFS, lineage (pathspec, sha, YK), delta vs prior run.

## RustFS

`config/metaflow/platform.json` already points at `s3://metaflow/metaflow`
@ `:9010`. `require_rustfs` refuses `local`, unset, foreign buckets, and
non-`:9010` / non-rustfs endpoints.

`DataProductTierUpkeep.end` records its own run via `record_from_current`.

```bash
just record-snapshot DataProductTierUpkeep 42 --code-sha abc
```
