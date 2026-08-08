# Governance scale plane: Kudu + RustFS for multi-engine devenv

**Date:** 2026-08-08

## Motivation

signals-protocol work multiplies concurrent federation clients. Postgres+AGE
cannot absorb bulk entity/tag/object traffic from Gaius + Aegir + Atelier +
Hermes simultaneously. Scale plane:

- **Kudu projections** — Atlas (`atlas.*` existing) + Ranger denorm (new)
- **RustFS** — objects on `$SIGNALS_DATA_ROOT/rustfs` (:9010)
- **AGE/PG** — thin topology + Ranger **admin** SoR only

## Landed this pass

| Item | Path |
|------|------|
| Doctrine | `docs/current/src/architecture/governance-scale-plane.md` |
| Ranger Kudu DDL + FDW | `config/ranger/kudu_projections*.sql` |
| Seed | `just ranger-kudu-projections-seed` / `just gov-kudu-projections-seed` |
| RustFS process | `processes.rustfs` + devenv input pin + buckets task |
| Protocol core | P0b prerequisite phase |

## Still open (critical)

1. Atlas **outbox worker** (continuous fill of projections)
2. Ranger TagSync → `ranger.tag_resource` UPSERT
3. Engines default to FDW projections for bulk reads
4. Discovery `OBJECT_STORE` + `GOV_PROJECTIONS` in signals-protocol
5. Live verify rustfs after `devenv up` (needs flake lock update for input)
