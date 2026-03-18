# Atlas AGE Backend — BDD Test Fix Implementation

**Date:** 2026-03-15
**Goal:** Close gap between Atlas AGE backend and BDD tier-0 test suite (2/10 passing → 10/10 target)

## Changes Made

### Fix 1: Models Symlink (`devenv.nix`)

Added symlink so `AtlasTypeDefStoreInitializer` finds bootstrap type definitions:

```bash
ln -sfn "$ATLAS_DIR/addons/models" "$ATLAS_HOME/models"
```

**Root cause:** Atlas sets `atlas.home=.devenv/atlas/` and looks for `${atlas.home}/models/`. That directory didn't exist. The actual model JSON files live in `components/atlas/addons/models/` (subdirs `0000-Area0/`, `1000-Hadoop/`, etc.).

**Unblocks:** Scenario 3 (bootstrap types) and transitively scenarios 4-10.

### Fix 2: Schema-qualify all table references (7 Java files)

Prefixed all bare table references with `public.` to avoid search_path resolution issues when AGE sets `search_path = ag_catalog, "$user", public`:

- `AgeSchemaManager.java` — CREATE TABLE/INDEX/TRIGGER (15 refs)
- `AgeCypherExecutor.java` — shadow table sync/delete (6 refs)
- `AtlasAgeGraph.java` — shadow table reads + clear() (8 refs)
- `AtlasAgeIndexQuery.java` — FTI queries (4 refs)
- `AtlasAgeGraphIndexClient.java` — aggregation/suggestion queries (2 refs)
- `AtlasAgeGraphManagement.java` — index metadata CRUD (2 refs)
- `AtlasAgeUniqueKeyHandler.java` — unique key CRUD (8 refs)

**Root cause:** `ensureAgeLoaded()` sets `search_path = ag_catalog, "$user", public`. The `ag_catalog` schema is searched first, and if the user schema doesn't exist, table resolution can fail depending on connection state.

### Fix 3: Persist property keys across management instances (`AtlasAgeGraphManagement.java`)

Enhanced `loadExistingMetadata()` to parse `field_keys` JSONB array from `atlas_index_meta` and populate the `propertyKeys` map. This makes `containsPropertyKey()` return `true` for previously created keys.

**Root cause:** Each `getManagementSystem()` call creates a new `AtlasAgeGraphManagement` with an empty `propertyKeys` HashMap. Without loading from persistent storage, `containsPropertyKey()` always returned `false`.

## Files Modified

| File | Lines Changed |
|------|--------------|
| `devenv.nix` | +2 (symlink) |
| `AgeSchemaManager.java` | 15 refs schema-qualified |
| `AgeCypherExecutor.java` | 6 refs schema-qualified |
| `AtlasAgeGraph.java` | 8 refs schema-qualified |
| `AtlasAgeIndexQuery.java` | 4 refs schema-qualified |
| `AtlasAgeGraphIndexClient.java` | 2 refs schema-qualified |
| `AtlasAgeGraphManagement.java` | 2 refs + loadExistingMetadata enhanced |
| `AtlasAgeUniqueKeyHandler.java` | 8 refs schema-qualified |

## Verification

Build: `mvn package` passed (BUILD SUCCESS, 4:26 min)

Next steps:
1. Restart Atlas: `devenv up`
2. Verify models loaded: check logs for `loadBootstrapTypeDefs` processing files
3. Run BDD: `uv run behave features/platform/health_atlas.feature --tags=@tier-0`
