# Apache Kudu Architecture Direction Research

Date: 2026-03-11

## Summary

Research into recent Apache Kudu development activity (2025-2026), focusing on
flatbuffers integration, gRPC adoption, Iceberg integration, Arrow support,
REST API, and wire protocol changes.

---

## 1. FlatBuffers Integration (KUDU-1261)

**Status:** Actively landing on master, slated for Kudu 1.19.0

FlatBuffers 25.2.10 was introduced into Kudu's third-party dependencies in
mid-2025. The primary use case is serializing/deserializing array cell data in
`RowOperationsPB.indirect_data`.

### Scope
- Currently limited to **one-dimensional arrays of scalar types**
- A FlatBuffers schema `array1d.fbs` defines the wire format
- Java classes generated from the schema; `Array1dSerdes` implements serdes
  for all scalar types
- C++: FlatBuffers used as a **header-only library** in serdes-test benchmarks

### Performance
- FlatBuffers serdes is **7-8x faster** than Protobuf (user CPU time, with
  buffer verification enabled)
- Benefits: no temporary serdes objects, buffer memory reuse without
  reallocation/copy, small runtime footprint

### Future Direction
- FlatBuffers could be extended to arbitrary nested types (structs, maps, etc.)
- The project acknowledges that **switching to Arrow IPC format** for nested
  type serialization is the best long-term option
- This positions FlatBuffers as a stepping stone toward full Arrow IPC adoption

### Key Commits
- `KUDU-1261 introduce Flatbuffers into thirdparty` (June 2025)
- `KUDU-1261 introduce nested types for ColumnSchemaPB`
- `KUDU-1261 [Java] Implement serdes of Array Type column`
- `KUDU-1261 [Java] Array Datatype client support`
- `KUDU-1261 Add array type support to Python client`
- `KUDU-1261 [Java] Add array column support in AlterTableOptions`
- `KUDU-1261 introduce ARRAY_1D_COLUMN_TYPE feature for masters`
- `[benchmarks] flatbuffers used as header-only library` (Dec 2025)

---

## 2. gRPC Adoption

**Status:** No evidence of active work or plans

Kudu continues to use its custom RPC framework (KRPC), which provides:
- Asynchronous communication across multiplexed connections
- Built-in TLS and Kerberos/SASL support
- Tight integration with Kudu's consensus and tablet protocols

No JIRAs, design docs, or mailing list discussions were found regarding
migrating from KRPC to gRPC. The KRPC design is documented at:
https://github.com/apache/kudu/blob/master/docs/design-docs/rpc.md

---

## 3. Iceberg Integration

**Status:** No evidence of integration plans

No Kudu-specific Iceberg JIRAs or design docs were found. The Iceberg ecosystem
survey (2025-2026) lists Spark (96.4%), Trino (60.7%), Flink (32.1%), and
DuckDB (28.6%) as primary engines -- Kudu is not mentioned.

Kudu's storage model (mutable columnar with Raft consensus) is architecturally
different from Iceberg's immutable Parquet/ORC file-based approach, so deep
integration would be non-trivial.

---

## 4. Arrow Support (KUDU-2077)

**Status:** Partially implemented, JIRA reopened/unresolved

### What Exists
- Since **Kudu 1.12**, Kudu supports a **columnar wire format** that is Arrow-compatible
- Java client: `setRowDataFormat()` on `KuduScanner` / `AsyncKuduScanner`
- Server-side: copies buffers from `ColumnBlock` to scan response, builds
  `arrow::Arrays` client-side

### What Doesn't Exist
- Full Arrow IPC spec compliance (KUDU-2077 remains open since 2020)
- Arrow Flight / Arrow Flight SQL endpoints
- No evidence of Arrow Flight adoption plans

### Connection to FlatBuffers
- Arrow IPC format itself uses FlatBuffers for metadata serialization
- The Kudu team explicitly notes Arrow IPC as the long-term serialization
  target for nested types, which aligns with the FlatBuffers introduction

---

## 5. REST API (New in 1.19.0)

**Status:** Landed on master, shipping in Kudu 1.19.0

Blog post by Gabriella Lotz (November 2025):
https://kudu.apache.org/2025/11/10/introducing-rest-api.html

### Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/tables` | List all tables |
| POST | `/api/v1/tables` | Create a new table |
| GET | `/api/v1/tables/<table_id>` | Get table details |
| PUT | `/api/v1/tables/<table_id>` | Update table metadata |
| DELETE | `/api/v1/tables/<table_id>` | Delete a table |
| GET | `/api/v1/leader` | Leader master discovery |

### Configuration
- Must enable: `--enable_rest_api` and `--webserver_enabled`
- Supports Kerberos/SPNEGO authentication
- OpenAPI spec: `www/swagger/kudu-api.json`
- Leader endpoint returns JSON: `{ "leader": "http://hostname:port" }`
- REST API tests include 1D array column support (KUDU-3714)

---

## 6. Wire Protocol Changes

No fundamental wire protocol changes beyond the existing columnar (Arrow-compatible)
scan format introduced in 1.12. The KRPC wire protocol itself remains stable.

The FlatBuffers introduction affects the **payload encoding** within
`RowOperationsPB.indirect_data` for array-typed columns, not the RPC framing.

---

## 7. Other Notable Development (2025-2026)

### Kudu 1.18.0 (July 2025)
- Segmented LRU cache (experimental)
- Embedded RocksDB for LBM metadata (experimental)
- JWT client authentication API
- Auto-incrementing column enhancements
- Prometheus metrics at tablet level
- Spark dependency upgraded to 3.5
- AArch64 platform support

### Kudu 1.18.1 (January 2026)
- Maintenance release with critical bug fixes
- OpenSSL 3.4+ compatibility fix

### Active on Master (targeting 1.19.0)
- **REST API** for table DDL
- **1D array column type** (KUDU-1261) across C++, Java, Python clients
- **FlatBuffers** for array serialization
- **IPv6 support** (KUDU-1457) -- multi-part effort across networking stack
- **Compaction improvements** -- KUDU-3734 includes undo delta size in rowset picking
- **Externalized Flink Connector** 2.0.0 (standalone, supports Flink 1.19/1.20)

---

## 8. Architecture Direction Assessment

### Near-term (1.19.0)
Kudu is becoming more accessible:
- REST API lowers the barrier for DDL operations and catalog integration
- Array column types expand the data model beyond flat scalars
- FlatBuffers provides efficient serialization for new nested types

### Medium-term
The team has explicitly flagged **Arrow IPC** as the preferred long-term
serialization format for nested types. This creates a natural path:
1. FlatBuffers for 1D arrays (now)
2. Arrow IPC for arbitrary nested types (future)
3. Potentially deeper Arrow ecosystem integration

### What Kudu is NOT doing
- No gRPC migration planned (KRPC remains)
- No Iceberg integration
- No Arrow Flight endpoints
- No fundamental wire protocol replacement

### Relevance to signals-360
- The REST API (`/api/v1/tables`, `/api/v1/leader`) provides a lightweight
  integration surface for catalog discovery without requiring Kudu client libraries
- FlatBuffers as a shared dependency (Kudu and signals-360 devenv both include it)
- The Arrow-compatible columnar scan format could be leveraged for efficient
  data transfer to visualization pipelines (HoloViews/Datashader/Dask)
