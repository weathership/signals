# Test Strategy + Upstream Kudu Research

## CI Test Strategy: Data Lifecycle Validation

### The Right Question

Not "what happens when PostgreSQL is down" (answer: everything is down, by
definition). The real question: **does data flow correctly through the
Kudu→Iceberg hot→warm lifecycle, and do architecture changes break that?**

### Workload Pattern

The validation workload models a realistic data landing pattern:

1. **Data lands in Kudu** — 1000 rows across 10 logical partitions
2. **~20% upsert load** — targets partitions 0-3 (hot), partitions 8-9 are cold
3. **Cold consolidation** — CTAS moves partitions 8-9 from Kudu to Iceberg
4. **Cross-tier queries** — UNION ALL spans both Kudu and Iceberg
5. **Ongoing mutations** — hot partitions continue to receive upserts,
   archived data is immutable

### What the CI Tests Verify

| Test | What Breaks If Architecture Changes |
|------|-------------------------------------|
| Kudu insert + upsert | KuduMetaProvider table construction wrong |
| CTAS Kudu→Iceberg | IcebergRESTCatalog DDL methods broken |
| Cross-tier UNION ALL | MultiMetaProvider chaining broken |
| Cross-tier row count | Data loss during consolidation |
| No cross-tier duplicates | DELETE after CTAS incomplete |
| Schema evolution | ALTER TABLE across both storage engines |
| Ongoing upserts | HMS-free DDL routing broke Kudu writes |

### Implementation

- **BDD feature**: `features/platform/data_lifecycle.feature` (5 scenarios)
- **Workload driver**: `tests/workload/lifecycle.py` (standalone + library)
- **Step defs**: `features/platform/steps/data_lifecycle_steps.py`
- **CI workflow**: `.github/workflows/catalog-ci.yml` (unit + integration)

### Two-tier CI

1. **Tier 0 (unit)**: ConfigLoaderTest runs on any Ubuntu runner, validates
   config parsing for both iceberg and kudu connector types
2. **Tier 1 (integration)**: Runs on self-hosted runner with devenv, exercises
   full data lifecycle against real Kudu/Impala/Polaris

---

## Upstream Kudu Research: FlatBuffers and Architecture Direction

### FlatBuffers in Kudu (KUDU-1261, targeting 1.19.0)

FlatBuffers 25.2.10 was introduced for serializing array column data in
`RowOperationsPB.indirect_data`. Performance: **7-8x faster than Protobuf**.

Current scope: 1D arrays of scalar types. The team explicitly states that
**Arrow IPC is the long-term target** for nested types (Arrow IPC itself
uses FlatBuffers for metadata).

### Kudu REST API (new, targeting 1.19.0)

A REST API was added for table DDL operations:
- `GET/POST/PUT/DELETE /api/v1/tables`
- `GET /api/v1/leader`
- Supports SPNEGO auth
- Flag: `--enable_rest_api`
- OpenAPI spec at `www/swagger/kudu-api.json`

**This is significant for us.** The REST API could replace direct Kudu client
library dependency for catalog discovery. KuduMetaProvider could query the
Kudu master REST API instead of using the Java client for table listing.

### What Kudu Is NOT Doing

- **No gRPC migration** — KRPC remains the wire protocol
- **No Iceberg integration** — fundamentally different storage models
- **No Arrow Flight endpoints** — partial Arrow support for scans (KUDU-2077)
  but stalled
- **No wire protocol changes** — FlatBuffers is payload encoding, not framing

### Implications for signals-360

| Kudu Development | Impact on Our Stack |
|-----------------|---------------------|
| REST API | KuduMetaProvider could use REST instead of Java client |
| FlatBuffers | Shared dependency; efficient nested type encoding |
| Arrow-compatible scan format | Feeds into Dask/Datashader pipeline efficiently |
| No gRPC | KRPC stays; gRPC replacement is our architecture layer, not Kudu's |
| No Iceberg in Kudu | Consolidation must remain at query layer (CTAS via Impala) |

### Revised Architecture Direction

```
Kudu Master REST API (/api/v1/tables)
    ↓ (catalog discovery)
KuduMetaProvider (PostgreSQL registry OR Kudu REST)
    ↓
MultiMetaProvider
    ├── KuduMetaProvider → Kudu (hot tier, KRPC)
    └── IcebergMetaProvider → Polaris REST → Iceberg (warm tier)
    ↓
Impala (query spanning both)
    ↓ (Arrow-compatible columnar scan from Kudu)
Dask/Datashader pipeline
    ↓
HoloViews visualization
```

The Kudu REST API is a natural fit for KuduMetaProvider's `loadTableList()`
— instead of querying our PostgreSQL registry, we could list tables directly
from the Kudu master. This would reduce the registry to databases-only
(since Kudu doesn't have a database concept) while Polaris handles Iceberg
table discovery natively.

### FlatBuffers as a Shared Wire Format

FlatBuffers is already a devenv dependency and is used by both Kudu (array
columns) and could be used by our gRPC engine for efficient message encoding.
The path from FlatBuffers → Arrow IPC → Arrow Flight is the natural evolution:

1. **Now**: FlatBuffers for Kudu array columns
2. **Near-term**: Arrow-compatible scan format for Kudu→Dask data path
3. **Future**: Arrow Flight SQL as a unified query interface
   (if/when Kudu or Impala adds Flight SQL support)
