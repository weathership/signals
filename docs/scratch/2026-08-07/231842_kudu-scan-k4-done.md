# PR-K4 complete: frontier bench + Atlas FT auto

**Date:** 2026-08-07  
**Bench detail:** `docs/scratch/2026-08-07/231801_atlas_frontier_bench.md` (+ matching `.json`)

## Harness

`scripts/atlas_frontier_bench.py`:
- `--force-access {impala_sql,kudu_scan,auto}` — ALTER edge FTs
- `--compare` — HS2 then kudu on frozen seed
- `--measure exec` (default for gates) — EXPLAIN ANALYZE Execution Time  
  (wall-clock includes psql spawn ~100–200ms and is not used for absolute gates)

`just atlas-frontier-bench --compare --skip-seed`

## Results (nodes=100, fanout=2, depth=4, measure=exec)

| batch | hs2_exec_ms | kudu_exec_ms | speedup | visited |
|------:|------------:|-------------:|--------:|--------:|
| 8 | ~68 | **~33** | ~2.1× | 25=25 |
| 32 | ~70 | **~34** | ~2.1× | 25=25 |
| 64 | ~68 | **~29** | ~2.4× | 25=25 |
| 256 | ~65 | **~30** | ~2.2× | 25=25 |

B=32 hop exec_ms_sum (kudu): **~30 ms**

### Gates

| Gate | Result |
|------|--------|
| hop1 exec &lt; 50 ms | **PASS** (~30–34 ms) |
| B=32 hop exec &lt; 100 ms | **PASS** (~30 ms) |
| visited multiset match | **PASS** |
| EXPLAIN AccessMethod kudu_scan | **PASS** (`gov.filtered_scan`) |
| ≥10× when HS2≥500 ms | **N/A** (HS2 exec floor ~65–70 ms on this machine; not the old ~2.5 s session tax) |

**PASS=true** under backend Execution Time metric.

Note: original ~2.5 s/hop HS2 floor was dominated by session/planning tax that is
already lower in current devenv (~70 ms HS2). kudu_scan still wins ~2× and clears
absolute ms targets.

## FT defaults

`config/atlas/kudu_projections_fdw.sql`: all Atlas FTs + server  
`access` / `default_access` → **`auto`**, `kudu_masters` set.

## Next

PR-K5 Kerberos for kudu_scan (product identity); optional HS2 session reuse if
wall-clock multi-hop apps stay process-bound.
