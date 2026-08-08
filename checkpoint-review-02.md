# Checkpoint Review 02 — impala_fdw direct-to-Kudu path (PR-K3/K4 + checkpoint-01 remediation)

- **Date:** 2026-08-07
- **Scope:** Working tree of `components/impala_fdw/` (still uncommitted on `trunk` @ `d1d6b95`) plus the superproject bench/config assets that PR-K4 touches: `scripts/atlas_frontier_bench.py`, `config/atlas/kudu_projections_fdw.sql`, `devenv.nix` build wiring. Delta reviewed against `checkpoint-review-01.md`.
- **Claimed state:** `docs/kudu_scan.md` rev 0.2.5 — checkpoint F1–F8 fixes applied, PR-K3 (strict selector, GUCs, KD16) and PR-K4 (bench gates, Atlas FT `access=auto`) complete.
- **Verdict:** The claimed state is real — every checkpoint-01 finding I marked must-fix or should-fix is verifiably remediated, the K3 selector faithfully implements the KD15 promotion table, and the bench shows the kudu path under the absolute latency targets measured inside the backend (~30 ms vs 50/100 ms gates) with auto-promotion confirmed in EXPLAIN. Three things still stand between this and "lab-ready, correct": one remaining wrong-results hole in LIMIT pushdown (aggregates / ORDER BY / DISTINCT), an equivalence gate that compares **counts** rather than the row multisets the design requires, and a broken `hs2-smoke` link. All are small fixes.

---

## Checkpoint-01 findings — remediation verified

| 01-ID | Status | Where verified |
|-------|--------|----------------|
| F1 columns for local quals / whole-row | ✅ **Fixed** | `attrs_for_foreign_scan` unions tlist + local-qual Vars; `varattno==0` expands to all live columns (`impala_fdw.c:329-365`) |
| F2 LIMIT vs OFFSET / local quals | ✅ **Fixed** (but see **N1** — the fix is incomplete for other upper-plan shapes) | `extract_pushable_limit` refuses OFFSET; plan gates on `local_exprs == NIL` (`impala_fdw.c:793-826, 890-897`) |
| F3 error-path cleanup | ✅ **Fixed** | Free-before-call row copy in Iterate (`impala_fdw.c:1223-1241`); `MemoryContextRegisterResetCallback` closes the Kudu scanner on abort (`impala_fdw.c:119-131, 1154-1159`). Callback struct lives in the same context it's registered in — correct pattern |
| F4 type freeze | ✅ **Fixed** | `type_supported` = BOOL/INT8/INT64/STRING/BINARY only; FLOAT/DOUBLE/VARCHAR/INT16/INT32 removed from both projection decode and predicate encode; the dead STRING-branch logic in `make_kudu_value` was also cleaned up (`exec_kudu.cpp:164-179, 345-407`) |
| F5 HS2 content sniffing | ✅ **Fixed** | `TGetResultSetMetadata` → `col_is_binary[]`; hex conversion is type-driven, NUL-sniffing removed (`exec_impala.cpp` `load_result_metadata`) |
| F6 exception firewall | ✅ **Fixed** for open/next (`exec_kudu.cpp:541-567, 774-796`); `impala_kudu_scan_close` is still unwrapped — see N8 |
| F7 interrupt responsiveness | ✅ **Fixed** for the HS2 wait loop via `ImpalaFdwInterruptPending()` poll — but the export breaks the standalone smoke tool, see **N4** |
| F8 WARNING spam on auto demote | ✅ **Fixed** — `elog(LOG, …)` (`impala_fdw.c:1141-1146`) |
| F9 batch of minors | Partial: forced-error `kerr` now pstrdup'd before `ereport` ✅; GUCs registered in `_PG_init` ✅. Still open (all minor): duplicated `resolve_col`, `atol` for the limit string, ReScan-without-fallback asymmetry, broken relative links in the `kudu_scan.md` header |

The K3/K4 work itself:

- **Selector (`path_select.c`)** — implements KD15 exactly: full-PK equality (checked against the six frozen Atlas PK sets) → `gov.pk_lookup`; allowlist columns (`src,dst,guid,qn_digest,entity_guid`) → `gov.filtered_scan` with promotion; incomplete PK is never labeled pk_lookup; auto promotion requires `enable_kudu` and residual-NIL; forced access honored both directions. KD16 enforced at Begin: forced `kudu_scan` + local residual → ERROR (`impala_fdw.c:1059-1064`).
- **GUCs** — `impala_fdw.enable_kudu_scan` (honored at both plan and Begin — kill-switch works even on already-planned statements), `log_path_choice`, `sample_max`.
- **Atlas FT flip** — `config/atlas/kudu_projections_fdw.sql` sets server `default_access 'auto'` + per-table `access 'auto'` + `kudu_masters`, matching the PR-K4 plan (resolved open question 1).
- **Bench** — `--compare / --force-access / --measure exec`; gates on EXPLAIN ANALYZE Execution Time. Results (nodes=100, fanout=2, depth=4): hop1 kudu ~29–34 ms (< 50 gate), B=32 hop ~30 ms (< 100 gate), ~2.1–2.4× vs HS2. EXPLAIN under auto shows `gov.filtered_scan` / `kudu_scan` with resolved table + masters. The 10× gate is honestly reported N/A because the HS2 exec floor on this machine is now ~65–70 ms, not the original ~2.5 s session tax.

---

## New findings

### N1 (high, wrong results): LIMIT still pushed beneath sorts, aggregates, DISTINCT, windows, and SRFs

`extract_pushable_limit` (`impala_fdw.c:793-826`) now refuses OFFSET and the plan refuses local quals — but the LIMIT in `query->limitCount` applies **above** every other upper plan node, and none of those are checked:

- `SELECT count(*) FROM ft LIMIT 1` → remote `LIMIT 1` → the Agg node counts one row → **returns count = 1** regardless of table size.
- `SELECT dst FROM atlas_edge_out WHERE src = … ORDER BY dst LIMIT 5` → remote truncates to an arbitrary 5 rows **before** the Sort → wrong 5 rows. This is a highly plausible governance query shape.
- `SELECT DISTINCT … LIMIT n`, `GROUP BY` / `HAVING`, window functions, and set-returning functions in the tlist all mis-truncate the same way.

Affects both executors (HS2 `LIMIT n` and Kudu `SetLimit`). Fix in one place: also return -1 when `query->sortClause || query->distinctClause || query->groupClause || query->groupingSets || query->havingQual || query->hasAggs || query->hasWindowFuncs || query->hasTargetSRFs` — the postgres_fdw preconditions. Since `has_limit` feeds `gov.column_sample` promotion, this same edit fixes the promotion side.

**Sub-point:** the WITH TIES guard at `impala_fdw.c:809-813` is dead code — `LIMIT_OPTION_COUNT` is an **enum constant** (`nodes.h` `typedef enum LimitOption`), not a macro, so `#ifdef LIMIT_OPTION_COUNT` never compiles the check in. Refusing `sortClause` subsumes WITH TIES (it requires ORDER BY), but delete the `#ifdef` anyway — it reads as protection that isn't there.

### N2 (medium-high, gate integrity): the equivalence gate compares counts, not row multisets

The bench's "visited multiset match: PASS" is `h["visited"] == k["visited"]` where `visited` is `len(visited)` — an **integer count** (`atlas_frontier_bench.py:326, 400`). Two paths that visit the same *number* of distinct nodes pass even if the nodes differ; per-row duplicates are additionally collapsed by the `set` accumulation (`:212, 239`). The design's K4 semantic gate is "100% row multiset match vs HS2 on frozen seed," and the Atlas FT auto-flip was conditioned on it. The K3 scratch note's manual smoke ("eq/IN multiset diff 0") is good evidence but isn't enforced by the harness.

Fix: have `frontier_hop` also return the raw row list; compare per-hop `Counter(rows)` between HS2 and kudu legs, and the final visited **sets**, in `summarize_compare`. Cheap, and it upgrades the gate from "same cardinality" to what the design says.

### N3 (medium, build break): `make hs2-smoke` no longer links

`exec_impala.cpp:393` calls `ImpalaFdwInterruptPending()`, defined only in `impala_fdw.c`. The smoke tool links `exec_impala.o` + thrift stubs **without** `impala_fdw.o` (`Makefile:121-126`) → undefined reference. `impala_fdw.o` can't be added (it needs the PG backend). Fix options: default-false weak definition in `exec_impala.cpp` (`__attribute__((weak))`), a stub in `hs2_smoke.cpp`, or a registered function pointer (set from `_PG_init`, defaulting to "no interrupt"). The function-pointer form is the most portable.

### N4 (medium, measurement realism): every bench probe is a cold backend — the client cache is never exercised

Each hop/EXPLAIN runs via a fresh `psql` subprocess → new PG backend → empty per-backend Kudu client cache. The measured Execution Time therefore **includes** `KuduClientBuilder::Build` + OpenTable on every probe (BeginForeignScan runs inside EXPLAIN ANALYZE's timed window). Two consequences:

1. The ~30 ms figures are conservative (cold-path) — good for gate credibility; warm-backend hops should be substantially faster. Worth measuring once with a single long-lived session (multi-statement psql script or DO block) to (a) quantify the cache win and (b) actually exercise the client/table cache-hit code path, which currently has no coverage anywhere.
2. Under PR-K5 Kerberos, cold client build will get more expensive — the per-backend-cold pattern is the worst case to watch there.

### N5 (low, selector nits — none block lab-ready)

- Allowlist promotion checks column **names** only, not operators: a range pred (`src > 'abc…'`) on an allowlist column promotes to kudu_scan. Semantically safe (Kudu evaluates it), but KD15's letter is eq/IN — a broad range on a HASH-partitioned lead column degenerates toward a full scan on the kudu path where Impala might plan better. Consider requiring eq/IN ops for allowlist promotion, or note the deviation in the doc.
- `<>` on an allowlist column promotes, then pred compile fails, then falls back per execution (LOG + HS2). No wasted RPC, but a permanent per-query demotion cycle; the selector could refuse NE up front (it knows nothing of ops today — same fix as above).
- `unique_lookup` recognition keys on a column literally named `qn_digest` without checking the table (`impala_fdw.c:919-921`) — a non-Atlas table with a `qn_digest` column gets the `gov.unique_lookup` label. Promotion outcome is the same as allowlist, so label-only; fine for v1.
- In the `gov.column_sample` condition (`path_select.c:42-44`), the `allowlist_filtered || full_pk_eq || unique_lookup` disjuncts are unreachable (those shapes are caught by earlier branches) — effectively `column_sample = pushable LIMIT ≤ sample_max ∧ no remote quals`. That is the correct behavior; the dead disjuncts just obscure it.

### N6 (low): remaining robustness notes

- `impala_kudu_scan_close` has no `catch (...)` and is now also invoked from the memory-context reset callback during **abort** — an escaping exception there is `std::terminate`. Wrap it like open/next (N8 from the F6 family).
- The kudu path itself has no interrupt polling; cancels wait on the 60 s scanner timeout worst-case. Acceptable and bounded; worth one line in the doc's timeout table.
- HS2 sessions have no abort-path cleanup analog to the kudu callback: on `ereport` mid-HS2-scan, the session/result objects (and server-side operation) leak until process exit — the same F3 pattern (extend the existing callback to close `festate->hs2`/`result`) would close it. Pre-existing, newly noted.
- `MarkGUCPrefixReserved("impala_fdw")` after the `DefineCustom*` calls would reject typo'd `impala_fdw.*` settings (PG15+).

---

## Lab-ready assessment (the three criteria)

| Criterion | Status |
|-----------|--------|
| **Correct** | ⚠️ Close. All checkpoint-01 wrong-results bugs fixed and verified; **N1** (LIMIT under agg/sort/distinct) is the one remaining wrong-results hole, and **N2** means equivalence evidence is count-level, not row-level. Both are small, contained fixes. |
| **Auto-promoted for Atlas adjacency** | ✅ Verified in code (KD15 selector, KD16 enforcement, GUC kill-switch) and in bench EXPLAIN output (`gov.filtered_scan` / `kudu_scan` under `access=auto`, FTs flipped in `kudu_projections_fdw.sql`). |
| **Under absolute latency targets, measured inside the backend** | ✅ hop1 ~29–34 ms (< 50 ms), B=32 hop ~30 ms (< 100 ms) via EXPLAIN ANALYZE Execution Time, with ~40% headroom — and the numbers are cold-backend conservative (N4). The 10× gate's honest N/A (HS2 floor now ~65–70 ms) is well-documented. |

## Recommended order of work

1. **N1** — extend `extract_pushable_limit` with the upper-plan-shape guards and drop the dead `#ifdef` (one function; fixes both executors and the column_sample promotion at once).
2. **N2** — row-multiset comparison in the bench harness, then re-run `--compare` to re-certify the K4 gate with the stronger check.
3. **N3** — unbreak `hs2-smoke` (function-pointer or weak-symbol default for the interrupt hook).
4. **N4** — one warm-session bench variant to cover the client-cache hit path and record the warm number alongside the cold one.
5. N5/N6 opportunistically or alongside PR-K5.
