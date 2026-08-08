# Product cutover: hive_* → rdbms_* (signals)

**Date:** 2026-08-08  
**Cross-ref:** Aegir Atlas `http://127.0.0.1:21000` (rdbms_table live; hive_table still present there as legacy)

## Code

| File | Change |
|------|--------|
| `src/sigint/atlas_client.py` | `register_table` / find_* → rdbms_*; instance+db+table+column bulk |
| `features/platform/steps/helpers.py` | same; constants `ATLAS_*_TYPE` |
| `features/platform/steps/integration_steps.py` | all lookups/searches/deletes use rdbms_table/column |
| `features/environment.py` | PII cleanup deletes rdbms_table |

## Attribute mapping (hive → rdbms)

| hive | rdbms |
|------|-------|
| column `type` | `data_type` |
| table `tableType` | `type` = `"TABLE"` (Aegir pattern) |
| db `clusterName` | parent `rdbms_instance` (`rdbms_type=Kudu`) |
| `hive_table_columns` | `rdbms_table_columns` |

## Intentional leftovers

- Atlas submodule still ships `1000-Hadoop` hive model (upstream)
- HMS optional tasks / hive-site.xml stubs for Impala HMS-free bootstrap
- Roadmap Phase 1 historical mention
- Aegir :21000 may still have old hive_* entities — their cleanup is separate

## Not done this pass

- Live tier-1 BDD against signals Atlas :21010 (was 503 earlier)
- Re-seed atlas.entity_flat projection rows (type_name was hive_table smoke data)
- Purge any existing hive_* entities in signals Atlas DB
