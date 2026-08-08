# Atlas entity pivot: hive_* → rdbms_* (Aegir parity)

**Decision (2026-08-08):** Governance entity types for signals-managed tables use
Atlas stock **RDBMS** model, same family as Aegir.

## Types

| Type | Source |
|------|--------|
| `rdbms_instance` | `components/atlas/addons/models/2000-RDBMS/2010-rdbms_model.json` |
| `rdbms_db` | same |
| `rdbms_table` | same |
| `rdbms_column` | same |
| (+ index / FK) | optional later |

Nothing against Hive — it is simply not in the stack out of the gate
(Postgres front → Impala SQL → Kudu storage).

## Cutover surface (code still on hive_*)

- `features/platform/steps/helpers.py` — `register_impala_table_in_atlas`
- `features/platform/steps/integration_steps.py`
- `features/environment.py` cleanup
- `src/sigint/atlas_client.py`

Attribute mapping notes for cutover:
- hive `type` → rdbms_column `data_type`
- hive `tableType` → rdbms_table `type` (optional string)
- hive `db` / `columns` relationships → `rdbms_db_tables` / `rdbms_table_columns`
- Consider creating one `rdbms_instance` for the lab cluster (rdbms_type=impala/kudu)

## Docs updated

- `docs/current/src/reference/roadmap.md` §2
- `docs/current/src/architecture/meta-tagging.md`
- `docs/current/src/scenarios/testing.md`
