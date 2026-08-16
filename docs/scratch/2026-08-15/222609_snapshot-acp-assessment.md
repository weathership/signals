# ACP assessment is part of the snapshot product

`signals.metaflow.snapshots` was mapping the Metaflow triple and writing a
brief, but `hx_reasoning.quality/lineage/delta` were empty and the upkeep
walk was not observed. The product now **is** that observation.

## Observer

`assess_upkeep` scores `data-product.tier-upkeep`:

- Nominal: legal FSM (`settled` or holding on the path), ADD = 168h,
  settle week via `DROP RANGE PARTITION` (never `DELETE FROM`), snapshot
  on RustFS, YK `root.platform`.
- Holding is nominal in-progress — not failed, not done.
- Off-nominal: failed FSM, missing walk on an upkeep run, local
  datastore, DELETE FROM. Recorded, then fail-closed.
- Other flows: `not_upkeep` (still an observation).

`data-product.history-review` is walked to `understood` (nominal /
not_upkeep) or `failed` (off-nominal). Agent id `acp-observer`.

`DataProductTierUpkeep.end` passes `self.doc` into the snapshot tx.
