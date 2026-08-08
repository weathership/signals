# Checkpoint F1–F8 fixes + PR-K3

**Date:** 2026-08-07  
**Input:** `checkpoint-review-01.md` + user summary

## Must-fix wrong results

| ID | Fix |
|----|-----|
| **F1** | `attrs_for_foreign_scan`: tlist ∪ local-qual Vars; whole-row (`varattno==0`) → all columns |
| **F2** | Push LIMIT only if Const COUNT, **no OFFSET**, **local_exprs NIL**; else PG Limit applies after residual |
| **F2+promote** | column_sample auto only when limit_pushable (no local residual) |

## Secondary

| ID | Fix |
|----|-----|
| **F3** | free-before-call (pstrdup then free malloc row); `MemoryContextRegisterResetCallback` → `impala_kudu_scan_close` |
| **F4** | `type_supported` = BOOL/INT8/INT64/STRING/BINARY only |
| **F5** | HS2 `GetResultSetMetadata` → `col_is_binary[]`; no batch NUL-sniff hex |
| **F6** | `catch (...)` on kudu open/next |
| **F7** | `ImpalaFdwInterruptPending()` in HS2 wait loop |
| **F8** | auto demote `elog(LOG)` not WARNING |

## PR-K3

- `path_select.c`: full PK → `gov.pk_lookup`; allowlist IN/eq → `gov.filtered_scan` (never incomplete PK as pk_lookup); residual → sql.general / no auto kudu
- GUCs: `impala_fdw.enable_kudu_scan`, `log_path_choice`, `sample_max`
- KD16: forced kudu + local residual → ERROR at Begin

## Smoke

- LIMIT 10 OFFSET 5 → Remote SQL **without** LIMIT; returns 10 rows
- eq/IN multiset diff **0**
- `access=auto` + `src = ANY(...)` → ShapeId `gov.filtered_scan`, AccessMethod `kudu_scan`

## Next

PR-K4: frontier bench + FT default `auto`
