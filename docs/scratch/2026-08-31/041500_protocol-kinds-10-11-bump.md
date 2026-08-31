# signals-protocol bump: kinds COGNITION(10) + CONTRIBUTIONS(11)

Submodule aeb8f6e -> 112a01b (pushed to origin/trunk by the gaius
session; both peers now pin the same head). Stubs regenerated per
scripts/gen_zndx_engine_py.sh into both trees.

- kind=COGNITION (10): a peer's cognition overview (CognitionHint).
  Signals has no cognition unit — unset hint is honest (documented in
  local_response; conformance-tested).
- kind=CONTRIBUTIONS (11): a peer's contributions by source and workflow
  (ContributionsHint, items stamped with their system of record).
  Signals answering is PENDING: Atlas+OpenLineage (Marquez sources —
  currently 0, fix planned), Metaflow, and Airflow will answer as each
  system of record comes online. Until then the unset hint is honest,
  never an error — gaius's collectors treat it as absence.

Live conformance: the RUNNING engine (pre-bump stubs) already answers
unknown kinds with project-only responses, so the lattice was conformant
before any restart; the bump makes the kinds nameable in code and tests.
test_engine_s2s: 13/13.

Note: gen_zndx_engine_py.sh runs `uv run`, which re-synced the project
.venv (dev venv). The LIVE engine runs from .devenv/state/venv and was
untouched — but the script deserves a venv-pinned invocation someday.

## Marquez 'Sources' fixed (Atlas-OL facade + gaius facets)

Root causes, all three verified live before the fix landed:
1. `ingestRunEvent` never materialized sources — only the never-called
   explicit upsert APIs wrote `lineage_sources` (0 rows vs 2,890 events);
   `buildDataset` hardcoded `sourceName:"default"`.
2. No producer sent `dataSource` facets (gaius's Dataset class supported
   them; flows never populated them).
3. Deploy chain rot: the signals devenv stack is ORPHANED (native manager
   dead; processes live in the other session's login scope) so
   `devenv processes restart atlas` cannot work and
   `signals-engine.service` only recycles the engine; AND the maven WAR
   shipped a STALE `WEB-INF/classes` while `target/classes` held the
   fresh compile.

Fixes: Atlas ingest-time source materialization + `lineage_dataset_sources`
map + truthful dataset/graph rendering (atlas submodule); gaius now
attaches per-namespace `dataSource` facets (gaius-kb, gaius-feeds,
signals-iceberg, …); `scripts/atlas_restart_fresh.sh` is the sanctioned
stopgap restart (reuses the running JVM, replays the devenv exec,
overlays fresh classes over the stale WAR, never trusts an inherited
PGPORT — a gaius-shell leak pointed the materialized conf at :5444 once;
signals PG is :5455).

Validated: /api/v1/sources = default + gaius-kb (uri from facet);
gaius.kb/current/heuristics flips to sourceName=gaius-kb; 12 namespaces,
jobs, graph, marquez-web all green. Follow-ons: map Source `type` from
the facet uri scheme (gaius-kb shows POSTGRESQL, the column default);
bring the stack back under a live manager; fix the war-plugin staleness.
