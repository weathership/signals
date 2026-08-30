# Impala-leverage assessment of the Polaris-tier1 remediation (`ebbf3ba`)

Written 2026-08-30 from the Gaius session, at the user's request, after the
data-product inventory remediation landed. Question examined: did "tier1 via
Polaris, not Impala DDL" drift from the transparent-hierarchy intent
(Kudu + Impala + Iceberg, one surface)? Evidence: repo sweep of this tree
(incl. the Impala fork sources under `components/impala`) plus live HS2
queries against the running stack.

## Verdict: convergence, not drift — with the tier1 write path doctrine-PENDING

**The query surface did not move.** All four merged views (`tx`, `details`,
`hx_exchange`, `hx_reasoning`) are Impala views in
`config/platform/data-products-views.sql`, unioning Kudu tier0 with Iceberg
tier1 and masking settled-hours with the same predicate shape as the `signal`
view (the mask was *added* in this remediation — previously a bare UNION ALL).
Every reader goes through the views over HS2: `warehouse.py`
`get_product`/`list_details`/`list_tx` (:330/:342/:355) and the federated
`PRODUCTS` answer (`engine/s2s.py:249`). The only `pyiceberg` importer in the
repo is `ops/iceberg_register.py`, and it only creates tables. Verified live:
`SHOW CREATE VIEW tx` shows the union+mask; the views serve rows
(tx=8, details=108, hx_reasoning=1, latest tx =
`gaius.curation.cot_reasoning | updated | manual verify post-remediation`).
One surface, no app-side tier splitting — **intent held**.

**What moved is exactly one thing: tier1 table DDL** — and on this fork it was
never Impala's to own:

- `components/impala/.../catalog/local/IcebergMetaProvider.java:198-199`
  marks every REST-discovered Iceberg table `ACCESSTYPE_READ`
  ("Only allow READONLY operations"), and
  `Analyzer.ensureTableWriteSupported` rejects writes to anything not
  RW. **Polaris-discovered Iceberg tables are read-only to Impala by
  construction.**
- The pre-existing rule `#SL.00000027.SCHEMA2` ("no HS2 Iceberg DDL on this
  stack") already encoded this; the handoff's phantom-table incident
  (`tx_tier1`/`details_tier1` failing DESCRIBE, vanishing on INVALIDATE) was
  its symptom.
- The remediation therefore *converges* the inventory with the tables that
  already work this way (`signal_tier1`, `gpu_metrics_tier1`,
  `gpu_dcgm_tier1`, `hx.cot_reasoning`) rather than inventing a pattern.

**The pending capability**: because REST-discovered tables are read-only to
Impala *today*, tier1 **settle writes** cannot be Impala `INSERT INTO …
SELECT` yet — for the inventory or anything else. The proven settles work
out-of-band (HDF5 + `IcebergHdf5Register.java` → Polaris REST; Impala's role
is `REFRESH` + `DROP RANGE PARTITION` + count-verify). **Doctrine (set by
the user on reviewing this assessment)**: Impala WILL become capable of
implementing the Transparent Hierarchical Storage over Kudu and Iceberg
through our own fork efforts — gradually, with purpose. Our documentation
therefore records Impala Iceberg DDL and Kudu→Iceberg operations as
**PENDING** (per upstream IMPALA-13586's own "not supported *yet*"), never
as out-of-scope or foreclosed; out-of-band settle is the bridge, not the
architecture.

## The two "discoveries", verified in fork source

1. **catalogd auto-registers HS2 DDL** — designed behavior, not accident:
   `SignalsDdlExecutor.java:149` (`registerTable` after Kudu CREATE, with
   rollback-drop) and `:199` (`registerView`), landing in `catalog_tables`
   via `KuduMetaProvider.registerTable/registerView` (INSERT … ON CONFLICT).
2. **Polaris tables need zero registry rows** — stronger than stated: an
   `ICEBERG` row in `catalog_tables` is **inert**. All three registry read
   paths filter `table_type IN ('KUDU','VIEW')`
   (`KuduMetaProvider.java:177-178, :200-204`;
   `CatalogServiceCatalog:2485-2487`); Iceberg tables are discovered live
   from Polaris (`IcebergMetaProvider.loadTableList/loadTable` via
   `catalog_config_dir/polaris.properties`). `gpu_dcgm_tier1`'s row was
   deleted by `signal-registry.sql:33-36` and it still DESCRIBEs/COUNTs fine
   (verified live).

## Real gaps for planning (ordered by consequence)

1. **Inventory settle is a no-op** — nothing writes tier1.
   `ops/tier_upkeep.py:67-86` steps `copying → verifying → dropping` without
   copying; `apply_sql=True` raises `NotImplementedError`; the flow's
   `settle` step (`flows/tier_upkeep.py:61-66`) only assigns variables. The
   `verifying` gate that must protect `DROP RANGE PARTITION` currently proves
   nothing. `tx_tier1` = 0 rows live.
2. **Settle-writer fragmentation decision**: the inventory tier1 tables are
   declared zstd-Parquet (`iceberg_register.py:36-42`) while
   `signal_tier1`/`gpu_metrics_tier1` are HDF5 via `IcebergHdf5Register`.
   Implementing inventory settle as PyIceberg-Parquet creates a third settle
   implementation; extending the Java registrar to Parquet would keep one
   registrar. Decide before writing the settle.
3. **The mask predicate cannot partition-prune the new tables.**
   `signal_tier1` is identity-partitioned on `epoch_hour`, so
   `WHERE epoch_hour NOT IN (…)` prunes; the four inventory tier1 tables
   partition on `product_id`/`e` (deliberate hotspot avoidance,
   `iceberg_register.py:172-175`) — so every merged-view read full-scans
   tier1. "Same predicate as the signal view" is true textually, not
   operationally. Candidate: two-field spec `(epoch_hour, product_id)` at the
   settle grain.
4. **`CREATE VIEW IF NOT EXISTS` is not update-idempotent**
   (`SignalsDdlExecutor.createView:191-197` early-returns on an existing
   row). The masking predicate landed only because the views had never been
   created; the next view change will silently keep the stale definition.
   Drop-and-recreate or a definition hash in `schema-apply`.
5. **`schema-apply` is still hand-run** (single call site
   `ops/__main__.py:180-193`, `just data-products-schema`; no boot/preflight/
   DAG wiring) — the same absence that let the inventory stay never-live.
   Same for `signal-registry.sql`.
6. **Registry/doc hygiene**: `signal-registry.sql`'s header states the
   pre-fork mental model ("no row here = invisible") — now wrong for ICEBERG
   and redundant for auto-registered tier0/views; its `signal_tier1` ICEBERG
   row is dead weight. Trim + correct.
7. **Known debris**: orphan tx `1788116515` (tx/details rows, no hx), noted
   in `215900_…` remediation doc.

## Provenance of the read-only-over-Iceberg posture (follow-up question)

**The engine gate is UPSTREAM's, not ours.** `IcebergMetaProvider.java` and
its `// Only allow READONLY operations` / `ACCESSTYPE_READ` line come
verbatim from Apache Impala commit `bd3486c05` (IMPALA-13586, "Initial
support for Iceberg REST Catalogs", Zoltan Borok-Nagy, 2024-12-20 — a
squashed Cloudera hackathon effort). Its commit message states the intent:
*"The support is read-only, i.e. DDL and DML statements are not supported
**yet**."* The gate is still present at the mirror tip (`caeacdf33`,
2026-02-27); none of the four later upstream commits touching the file relax
it. The enforcement point (`Analyzer.ensureTableWriteSupported`, "Write not
supported…") is also upstream (IMPALA-8593, 2019, Hive-3 table-capabilities
handling); the fork never touched `Analyzer.java`.

**The reinforcing notes are OURS — scope decisions layered on that gate:**
- `components/impala_fdw/README.md` "Storage scope": out-of-scope =
  "INSERT over `impala_sql` / Iceberg" (in-scope: Kudu INSERT/scan,
  Iceberg cold + UNION views read via `impala_sql`, `DROP RANGE PARTITION`
  via `impala_fdw_exec`).
- `config/platform/*-fdw.sql` headers ("`*_tier0` Kudu INSERTable;
  tier1/views always `impala_sql`"; "Iceberg FTs must not use kudu_scan").
- Guru `#SL.00000027.SCHEMA2` ("no HS2 Iceberg DDL on this stack") — ours,
  encoding the observed upstream limitation (the phantom-table incident is
  what trying HS2 Iceberg DDL against the REST-only path produces).

**Precedent that the fork can move such gates when it chooses:**
`6706f53a8` ("fe: HMS-free Kudu tables as READWRITE for FDW SELECT")
adjusted the access type for Kudu; the Iceberg gate was left as upstream
shipped it.

**Planning implication (per doctrine):** flipping `ACCESSTYPE_READ` alone
would not yield a working INSERT — upstream gated it because the
REST-catalog path lacks the DML/commit machinery. The **destination** is
(b): fork-implement the REST-catalog commit path into Impala's DML
planner/sink, gradually and purposefully (the client-side pieces exist in
our `IcebergHdf5Register`; the planner/sink wiring is the substantial part).
The **bridge** is (c): out-of-band settle, as signal/gpu_metrics do today.
Upstream IMPALA-13586 follow-ups (a) are tracked opportunistically — our
mirror should be refreshed periodically to harvest them. Our FDW/SQL notes
have been reworded accordingly: Impala Iceberg DDL and Kudu→Iceberg
operations are **PENDING**, attributed to upstream's "read-only *yet*".

## Gaius-side effects (for completeness)

- Peer publishes should now go nominal (inventory live) — the next
  article-curate `end` step should print `Published
  gaius.curation.cot_reasoning tx=<uuidv7> (nominal)` instead of the History
  JSONL soft-fail.
- The `role`→`actor` rename is Signals-internal (verified propagated:
  kudu DDL, views, INSERT builder, history payload, ER doc); Gaius publishes
  via `signals.ops` surfaces, so no Gaius change needed.
