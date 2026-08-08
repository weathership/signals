# Apache AGE: integrate / enhance opportunities (signals)

AGE is already the Atlas graph spine (`atlas_graph`, Apache-2.0). Same license class as Atlas/Ranger/Kudu/Impala. Worth **direct contributions** where Kudu projections and FDW leave gaps AGE is better suited to own.

## Already in-tree (Atlas AGE fork)

- Shadow FTI / unique key tables + triggers (`AgeSchemaManager`)
- Functional indexes on `__guid` / `qualifiedName` / `age_id`
- Gremlin→Cypher translator, bulk hydrate `vertex_id = ANY(ARRAY[…])`
- Cypher executor + connection pool `search_path`

These are the right place for **transactional graph of record** work.

## High-value AGE enhancements (upstream or fork)

| Area | Why | Signals payoff |
|------|-----|----------------|
| **Stable binary / UUID property type** | Atlas guids are 16-byte identities; today often strings in agtype | Align AGE property storage with Kudu BINARY projections; cleaner dual-write |
| **Native `= ANY` / batch id lookup in Cypher** | Atlas already batches FTI SQL; Cypher path often 1-id-at-a-time | Glossary / impact expand without leaving Cypher |
| **Vertex/edge delete replica identity helpers** | Logical decoding must emit full edge endpoints for Kudu dual adjacency | Document + sample `REPLICA IDENTITY FULL` for label tables; optional AGE helper |
| **Notification / CDC hooks for graph mutates** | Outbox needs full payloads | First-class “graph change” stream for projection sync |
| **Hybrid plan: Cypher seed + SQL frontier** | Freeze traversal is procedural SQL over FDW | AGE function that returns guid frontier as `bytea[]` for FDW hop |
| **Classification / property multi-get** | UI “open entity” stays on AGE | Keep; expose bulk property fetch by guid list for search hydration |
| **Index push for type-scoped unique attrs** | Digest is type‖QN on Kudu; AGE unique keys are already type-aware | Ensure unique index API matches Atlas type-scoped uniqueness |
| **Explain / metrics for cypher()** | Hard to compare AGE hop vs FDW hop | Fair frontier benchmarks |

## Better left out of AGE

| Topic | Prefer |
|-------|--------|
| Columnar bulk entity docs / audit by time | Kudu projections |
| Tag-invert “all PII” at estate scale | Kudu `entity_classifications` |
| Fulltext over whole estate | PG FTI now; later dedicated search—not AGE core |
| Multi-hop TC materialization for Impala | Kudu TC table if measured necessary |

## Integration patterns (no fork required)

1. **Cypher for topology, FDW for bulk hop** — AGE resolves seed guids; frontier loop uses `atlas_edge_*` foreign tables.
2. **Dual-write from AtlasAgeGraph** — on createEdge/deleteEdge, enqueue outbox events (or call notify) with full (src, elabel, dst).
3. **Shared guid codec** — single library: 16-byte UUID ↔ agtype string ↔ Kudu BINARY ↔ PG `bytea`.
4. **RLS on AGE shadow tables** vs FDW foreign tables — document which plane enforces which role.

## Contribution posture

- Prefer **upstreamable** AGE patches (batch lookup, replica identity docs, UUID helpers).
- Keep Atlas-specific shadow schema in the Atlas AGE module (already forked).
- Measure before adding TC or deep Cypher multi-hop optimizers—FDW frontier may suffice.

## Related freeze

`211412_atlas-kudu-projection-freeze.md` — AGE remains SoR; Kudu derived.
