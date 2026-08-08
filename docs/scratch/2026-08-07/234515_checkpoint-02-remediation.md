# Checkpoint 02 remediation (N1–N4 + polish)

**Date:** 2026-08-07  
**Source:** `checkpoint-review-02.md`

## N1 LIMIT under upper plan nodes — fixed

`extract_pushable_limit` now refuses LIMIT when any of:
- OFFSET present
- `limitOption` not COUNT/DEFAULT (WITH TIES; real enum check, not dead `#ifdef`)
- `sortClause`, `distinctClause`, `groupClause`, `groupingSets`, `havingQual`
- `hasAggs`, `hasWindowFuncs`, `hasTargetSRFs`

Verified:
- `SELECT count(*) FROM atlas_edge_out LIMIT 1` → **297** (full count); Remote SQL **no LIMIT**
- `… ORDER BY dst LIMIT 5` → Remote SQL **no LIMIT**; Sort above Foreign Scan

## N2 Multiset gate — fixed

Bench stores per-hop `row_multiset` (`Counter`) + `visited_set`;  
`summarize_compare` requires set match + hop multiset match + all-hops multiset match.

Re-run gates: **all true**, PASS=true.

## N3 hs2-smoke link — fixed

`ImpalaFdwSetInterruptCheck` function-pointer hook in `exec_impala.cpp`  
(default no-op); `_PG_init` registers backend `InterruptPending` probe.  
`make hs2-smoke` links without `impala_fdw.o`.

## N4 Warm session — measured

Same-backend EXPLAIN ANALYZE ×3 for point hop:

| path | cold | warm | warm2 |
|------|-----:|-----:|------:|
| HS2 | ~67 ms | ~68 ms | ~80 ms |
| kudu | **~30 ms** | **~0.47 ms** | **~0.44 ms** |

- kudu cold→warm cache speedup **~63×**
- warm HS2/kudu speedup **~144×**
- dst multiset match between paths **true**

## Polish

- N5: allowlist promotion requires **eq/IN only** (not range/`<>`); `qn_digest` unique_lookup scoped to `entity_by_qn`
- N5: `column_sample` only remote-empty + pushable LIMIT
- N6: `impala_kudu_scan_close` `catch (...)`; kudu mcxt callback retained; **HS2 mcxt callback not registered** (caused SIGSEGV on short LIMIT scans — EndForeignScan still closes HS2)
- `MarkGUCPrefixReserved("impala_fdw")`

## Lab-ready

| Criterion | Status |
|-----------|--------|
| Correct | ✅ N1 closed; multiset gate enforced |
| Auto-promote Atlas adjacency | ✅ unchanged |
| Latency targets (backend) | ✅ + warm path documented |

