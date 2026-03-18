# Atlas AGE Backend: 10/10 Tier-0 BDD Scenarios Passing

## Summary

All 10 tier-0 BDD scenarios for the Atlas AGE backend now pass, completing in under 10 seconds. Starting point was 2/10 passing.

## Root Causes Found and Fixed

### 1. Models directory missing (Fix 1 from plan)
- **Symptom**: 0 bootstrap types loaded
- **Fix**: `devenv.nix` — symlink `$ATLAS_DIR/addons/models` to `$ATLAS_HOME/models`
- **Result**: 123 entity types now load on startup

### 2. Schema-qualified shadow table references (Fix 2 from plan)
- **Symptom**: `atlas_fti_vertex` not found under AGE's search_path
- **Fix**: Prefixed all shadow/meta table references with `public.` across 7 Java files (45 references)
- **Files**: AgeCypherExecutor, AtlasAgeGraph, AtlasAgeIndexQuery, AtlasAgeGraphIndexClient, AgeSchemaManager, AtlasAgeGraphManagement, AtlasAgeUniqueKeyHandler

### 3. Property keys not persisting (Fix 3 from plan)
- **Symptom**: `containsPropertyKey()` always returned false
- **Fix**: `AtlasAgeGraphManagement.loadExistingMetadata()` now parses `field_keys` JSONB to populate `propertyKeys` map

### 4. Missing lazy property loading (discovered during verification)
- **Symptom**: Entity retrieval returned 500 with null `__typeName`
- **Root cause**: `AtlasAgeGraphQuery.vertices()` returned vertices WITHOUT loading properties from the shadow table. Atlas retrieves entities via `graph.query().has("__guid", guid).vertices()` which went through `AtlasAgeGraphQuery`, not `AtlasAgeGraph.getVertices()`
- **Fix**: Added lazy property loading to `AtlasAgeVertex.getElementProperties()` and `AtlasAgeEdge.getElementProperties()`. Added `propertiesLoaded` flag to `AgeVertex` and `AgeEdge`. Made `loadVertexPropertiesFromShadow()` and `loadEdgePropertiesFromShadow()` package-private.
- **Files**: AgeVertex, AgeEdge, AtlasAgeVertex, AtlasAgeEdge, AtlasAgeGraph

### 5. JSONB array parsing missing (discovered during verification)
- **Symptom**: Parser corrupted property map when JSONB contained arrays like `__superTypeNames`
- **Fix**: Added array (`[...]`) and nested object (`{...}`) handling to `AgeCypherExecutor.parseKeyValuePairs()`
- **File**: AgeCypherExecutor

### 6. Connection pool exhaustion — was actually Kafka timeout (discovered during verification)
- **Symptom**: Entity creation took 60 seconds
- **Root cause**: Kafka producer blocked for 60s trying to send notifications to non-existent broker
- **Fix 1**: Changed `AtlasAgeGraph.commit()/rollback()` to use `commitAndRelease()/rollbackAndRelease()` so connections return to pool after transactions
- **Fix 2**: Added `atlas.kafka.max.block.ms=1000`, `request.timeout.ms=1000`, `delivery.timeout.ms=2000` to config
- **Result**: Entity creation went from 60s to ~1.3s

### 7. FTI trigger hard-coded property keys (discovered during verification)
- **Symptom**: Full-text search returned 0 results — trigger used `Asset.name` but actual key was `signals_test_asset.name`
- **Fix**: Rewrote trigger to use generic JSONB key pattern matching (`LIKE '%.name'`, `LIKE '%.qualifiedName'`, etc.)
- **File**: AgeSchemaManager

### 8. Search term hyphen handling (discovered during verification)
- **Symptom**: Search for "test-entity" produced invalid tsquery `testentity`
- **Fix**: `SolrToTsqueryParser.sanitizeTsqueryTerm()` now splits on hyphens/slashes and joins with `&`
- **File**: SolrToTsqueryParser

### 9. Suggestions NPE and operator precedence (discovered during verification)
- **Symptom**: Suggestions returned 500 — `indexFieldName` was null, and JSONB `%` operator had precedence issues
- **Fix**: Handle null `indexFieldName` by searching across `%.name`, `%.qualifiedName`, `%.description`. Used subquery with explicit parentheses for pg_trgm `%` operator.
- **File**: AtlasAgeGraphIndexClient

## Files Modified

| File | Changes |
|------|---------|
| `devenv.nix` | Models symlink |
| `config/atlas/atlas-application.properties` | Pool size 50, Kafka fast-fail timeouts |
| `features/platform/steps/helpers.py` | API timeout 60s |
| `AgeVertex.java` | `propertiesLoaded` flag |
| `AgeEdge.java` | `propertiesLoaded` flag |
| `AtlasAgeVertex.java` | Lazy property loading from shadow table |
| `AtlasAgeEdge.java` | Lazy property loading from shadow table |
| `AtlasAgeGraph.java` | commitAndRelease, package-private shadow loaders |
| `AtlasAgeGraphDatabase.java` | Default pool size 30 |
| `AgeCypherExecutor.java` | Array/object parsing in JSONB parser |
| `AtlasAgeGraphQuery.java` | (unchanged — lazy loading handles it) |
| `AtlasAgeIndexQuery.java` | public. prefix on shadow tables |
| `AtlasAgeGraphIndexClient.java` | Null-safe suggestions, pg_trgm fix |
| `AtlasAgeGraphManagement.java` | public. prefix, property key persistence |
| `AtlasAgeUniqueKeyHandler.java` | public. prefix |
| `AgeSchemaManager.java` | public. prefix, generic FTI trigger |
| `SolrToTsqueryParser.java` | Hyphen splitting in search terms |

## BDD Results

```
10 scenarios passed, 0 failed, 0 skipped
45 steps passed, 0 failed, 0 skipped
Took 0min 9.988s
```
