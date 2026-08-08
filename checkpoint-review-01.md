# Checkpoint Review 01 — impala_fdw direct-to-Kudu path (`kudu_scan`)

- **Date:** 2026-08-07
- **Scope:** Uncommitted work in `components/impala_fdw/` (submodule `trunk` @ `d1d6b95` + working tree), focused on the direct-to-Kudu scan path (PR-K0–K2 per `docs/kudu_scan.md` rev 0.2.3). HS2-path changes in the same diff are covered briefly where they affect equivalence testing. Superproject changes (`Justfile`, `devenv.nix`, `config/atlas/*`) are out of scope here.
- **Files reviewed:** `src/exec_kudu.{cpp,h}` (new), `src/kudu_pred.{c,h}` (new), `src/deparse.{c,h}` (new), `src/impala_fdw.c`, `src/path_select.c`, `src/exec_impala.cpp`, `Makefile`, `docs/kudu_scan.md`, `docs/SPEC.md`, `docs/design.md`.
- **Verdict:** The Kudu executor and predicate compiler are in good shape and closely follow the design doc's binding contracts (FFI deep-copy, cache rules, safety gating, fallback policy). The serious problems are not in the new Kudu code itself but in the **planner-side glue shared by both paths**: column retrieval and LIMIT pushdown have three wrong-results bugs that will corrupt the K2/K4 equivalence gates if not fixed first. Error-path resource cleanup mandated by the design's memory contract is also not yet implemented.

---

## What's solid

The implementation honors the design doc's binding decisions to an unusual degree; these were all verified against the code, not just the doc's status table:

- **FFI memory contract (KD9, doc §Memory & lifetime):** pred IR is palloc'd, borrowed only for the duration of `impala_kudu_scan_open`, and deep-copied into `KuduValue`/`KuduPredicate` objects (`CopyString`, `FromInt`, …). Ownership transfer to `AddConjunctPredicate` is respected, including the IN-list cleanup-on-partial-failure loop (`exec_kudu.cpp:515-531`).
- **Client/table cache (KD5, resolved OQ3):** process-global client map keyed by canonicalized masters (split/trim/sort/rejoin), OpenTable success cache with stale-entry invalidation and no permanent negative cache (`exec_kudu.cpp:98-129, 317-346`).
- **Safety gating:** parallel workers refuse kudu (KD19; path also marked `parallel_safe=false` at `impala_fdw.c:364`), forced `kudu_scan` errors instead of silently demoting, auto gets exactly one HS2 fallback with `fell_back_to_hs2` tracked and surfaced in EXPLAIN ANALYZE as `kudu_scan→impala_sql` (K7 plan-vs-runtime distinction implemented correctly at `impala_fdw.c:1029-1045`).
- **Empty-IN semantics:** empty/NULL arrays short-circuit to a no-RPC empty scan handle (`npreds=-1` sentinel), matching SQL semantics; NULL elements in IN lists are conservatively refused rather than mis-translated.
- **Type discipline in predicates:** typed payloads by PG Oid, range checks for INT8/16/32 narrowing, refusal of bytea↔STRING and text↔BINARY cross-binding, `<>` refused at both the compiler (`kudu_pred.c:289-292`) and executor (`exec_kudu.cpp:568-570`) since Kudu has no NOT_EQUAL.
- **Timeouts/consistency (KD13/KD14):** `READ_LATEST`, scanner 60 s, admin 60 s / RPC 30 s — exactly as specified.
- **Build wiring:** split `KUDU_CLIENT_LIBDIR`/`KUDU_CLIENT_INCDIR` with debug→release→submodule fallbacks, rpath, HS2-only build when the client is absent (R7 mitigated).
- **Doc hygiene:** `kudu_scan.md` status table (rev 0.2.2/0.2.3) accurately reflects what's in the tree.

---

## Findings — must fix before the K2/K4 equivalence + bench gates

### F1 (high, wrong results): columns referenced only by local quals are never fetched

`attrs_from_tlist` (`src/impala_fdw.c:263-294`) pulls attnos from the plan tlist only. Columns referenced **only** by unpushable (local) quals are not in the tlist — for a base rel, the planner puts qual-only Vars in `baserestrictinfo`, not `reltarget`. Those quals are handed to `make_foreignscan` as scan-level quals (`impala_fdw.c:670-677`) and evaluated against the scan tuple, where the un-retrieved column is NULL.

Failure scenario: `SELECT a FROM ft WHERE some_unpushable_fn(b)` → `b` is never retrieved → qual evaluates over NULL → rows silently disappear. Affects **both** the kudu_scan and HS2 paths.

Related edge in the same function: a whole-row Var (`varattno == 0`, e.g. `SELECT ft, a FROM ft`) is ignored by `pull_varattnos_cb`, so mixed whole-row + column references retrieve only the named column and build the row with NULLs elsewhere.

Fix: mirror postgres_fdw — union Vars from `baserel->reltarget->exprs` (or the tlist) **and every local qual clause**, and treat `varattno == 0` as "all columns".

### F2 (high, wrong results): LIMIT pushdown ignores OFFSET and local quals

`extract_simple_limit` (`src/impala_fdw.c:553-579`) checks only `query->limitCount`, and `impalaGetForeignPlan` pushes the limit unconditionally (`impala_fdw.c:639`, then into HS2 `LIMIT n` and Kudu `SetLimit`). Two independent wrong-results cases:

1. **OFFSET:** `SELECT … LIMIT 10 OFFSET 5` → remote returns rows 1–10, PG's Limit node then skips 5 → 5 rows returned instead of rows 6–15.
2. **Local quals:** `SELECT … WHERE unpushable(x) LIMIT 10` → remote truncates to 10 rows *before* the local filter runs → fewer than 10 matching rows returned even when more exist. (Also reachable under `access=auto`, where `has_limit` promotes to kudu_scan via `gov.column_sample` regardless of residual quals — the design's promotion precondition 3 "residual is NIL" is K3 scope, but the wrong-results interaction is live now.)

Fix: only push LIMIT when `limitOffset == NULL` (or push `offset + count` and let PG re-apply), `limitOption` is plain `LIMIT_OPTION_COUNT`, and `local_exprs == NIL`. This also implements KD16's spirit for the forced-kudu + residual case.

### F3 (medium, resource safety): the design's error-path cleanup contract is not implemented

The memory contract in `kudu_scan.md` (§Memory & lifetime, KD11) is explicit: *"ERROR / longjmp — EndForeignScan may not run — Register MemoryContext callback or PG_TRY in Begin/Iterate."* Neither exists:

- `impalaIterateForeignScan` (`src/impala_fdw.c:892-928`): `OidInputFunctionCall` can `ereport` on bad input; the malloc'd `values`/`nulls` row leaks (malloc, so it survives transaction abort and accumulates per error).
- On any mid-scan `ereport`, the `ImpalaKuduScan` handle (C++ heap: scanner, batch, client-entry `open_scans` refcount) leaks for the life of the backend, and the server-side scanner lingers until its 60 s timeout.

Fix: free-before-call pattern (convert the row into palloc'd memory or Datums first, then free the malloc row, then run input functions), plus a `MemoryContextCallback` on the scan's context (or resowner callback) that calls `impala_kudu_scan_close`. Note the current `open_scans` refcount is written but never read — either wire it into a destroy policy or drop it.

---

## Findings — should fix, latent or quality

### F4 (medium, latent): `type_supported` is wider than the v1 type freeze, and the extra types are broken

The doc freezes v1 to STRING, BINARY, INT8, INT64, BOOL and says FLOAT/DOUBLE/VARCHAR should ERROR at open. `type_supported` (`src/exec_kudu.cpp:164-183`) accepts FLOAT, DOUBLE, and VARCHAR, and:

- **FLOAT/DOUBLE** are materialized with `std::to_string` (`exec_kudu.cpp:240-257`), which is fixed 6-decimal `%f`: `1e-10` becomes `"0.000000"`, precision silently truncated. If kept, use `%.9g` / `%.17g`; otherwise reject per the freeze.
- **VARCHAR** columns are decoded with `row.GetString()` (`exec_kudu.cpp:258-266`); the Kudu client type-checks getters, so `GetString` on a VARCHAR column returns InvalidArgument — every row of a projected VARCHAR column fails at decode. Needs `GetVarchar` or removal from `type_supported`.

Recommendation: shrink `type_supported` to the frozen five for v1 — that makes the doc, the code, and the equivalence gates agree.

### F5 (medium, HS2-side but gates equivalence): content-sniffing in `column_to_strings`

The new BINARY handling in `src/exec_impala.cpp` prefers `binaryVal` (good), but the `stringVal` fallback hex-encodes the **whole column batch** if *any* value in the batch contains an interior NUL. Consequences:

- A genuine STRING/text column where one row contains a NUL turns the entire batch into `\x…` hex text — silently wrong data, and inconsistent across fetch batches.
- Binary smuggled as `stringVal` *without* NULs passes through raw into `byteain`'s escape format, where backslash bytes mis-parse.

Since HS2 is the reference side of the K2/K4 multiset equivalence gate, a nondeterministic representation here can produce false failures (or worse, false passes). Recommendation: drive the conversion from result-set metadata (`TGetResultSetMetadata` column types) instead of content sniffing.

### F6 (low-medium): no exception firewall at the `extern "C"` boundary in exec_kudu

`exec_impala.cpp` wraps thrift calls in try/catch; `exec_kudu.cpp` has no catch anywhere. The Kudu client reports via `Status`, but `std::string`/vector allocations can throw `bad_alloc`, and any exception crossing into PG C code is `std::terminate` → backend crash. A `catch (...)` → error-string wrapper around the three entry points is cheap insurance.

### F7 (low): interrupt responsiveness

- `wait_operation_complete` (`exec_impala.cpp`) polls up to 120 s with 20 ms sleeps and no way to observe PG cancel interrupts (the C++ layer can't call `CHECK_FOR_INTERRUPTS`). A hung Impala query pins the backend against `pg_cancel_backend` for up to 2 minutes. Consider shorter poll windows returning control to C code that checks for interrupts, or accept and document. Same class of issue exists on Kudu RPCs but is bounded by the 30/60 s timeouts.
- Minor: the status poll now runs for every SELECT (adds one RTT); harmless at HS2's ~2.5 s floor, worth remembering if HS2 hop latency is ever re-benchmarked.

### F8 (low, noise): auto + LIMIT + uncompilable pred warns on every execution

Under `access=auto`, `has_limit` promotes to kudu_scan; if pred compile then fails (e.g. a `<>` qual), Begin emits `elog(WARNING …)` **per query** (`src/impala_fdw.c:819-828`). The design's error taxonomy calls this "demote to HS2 without opening Kudu" — a LOG (or the planned `log_path_choice` GUC) fits better than WARNING for an expected demotion. K3's strict selector will mostly eliminate the case; until then this is log spam on a hot path.

### F9 (minor, batched)

- `make_kudu_value` STRING branch (`src/exec_kudu.cpp:448-466`): the nested Oid check is dead logic (outer non-25 condition already implies the inner), and the BYTEA guard below it is unreachable since 17 fails the outer check. Works, but confusing — simplify to `pg_ty == 25` since `pack_const` normalizes all text types to TEXTOID.
- `resolve_col` (`kudu_pred.c:32-49`) duplicates `resolve_kudu_column_name` (`impala_fdw.c:371-388`) — export one.
- `kerr` from a forced-kudu open failure is malloc'd and leaks through `ereport(ERROR)` (`impala_fdw.c:814-818`); copy to palloc first or accept the one-shot leak knowingly.
- ReScan on the kudu path (`impala_fdw.c:940-960`) ERRORs on re-open failure even under `access=auto` — inconsistent with Begin's one-fallback policy. Rare (no params yet ⇒ rescan is a repeat), but worth a comment or a fallback.
- `atol` for the limit string (`impala_fdw.c:730`) — fine on LP64, `strtoll` is the portable spelling.
- `exec_kudu.cpp` uses `INT32_MIN/INT32_MAX` without including `<cstdint>` — currently works via transitive includes from Kudu headers.
- Doc drift: `ImpalaKuduPred` in `kudu_scan.md` still shows a `value_isnull` field the real struct doesn't have; the doc-header relative links (`../components/impala_fdw/...` from inside `components/impala_fdw/docs/`) don't resolve.
- `append_consts_from_array` takes an unused `col` parameter.

---

## Design-conformance snapshot (KD table)

| Decision | Status |
|----------|--------|
| KD2 one FDW / two executors, KD3 read-only, KD4 serial scanner | ✅ implemented |
| KD5 client cache + no fork reuse, KD19 parallel-unsafe | ✅ implemented |
| KD6 name resolution (`kudu_table` / `impala::db.table`), operator HINT on NotFound | ✅ implemented |
| KD8 fallback policy (forced ERROR / auto once) | ✅ implemented (taxonomy not differentiated by error class — acceptable for now) |
| KD9 typed pred IR + deep copy | ✅ implemented |
| KD11 slot conversion + **PG_TRY/free-before-call** | ⚠️ conversion yes; error-path contract **missing** (F3) |
| KD13/KD14 READ_LATEST + timeouts | ✅ implemented |
| KD15/KD16 strict promotion, residual → ERROR when forced | ⏳ K3 scope by plan — but see F1/F2 for live wrong-results interactions |
| KD17 K1 gate | ✅ superseded correctly by real preds (K2) |
| KD18 no `guid_encoding` | ✅ |
| GUCs (`enable_kudu_scan`, `log_path_choice`, …) | ⏳ K3 — `_PG_init` still empty |

---

## Recommended order of work

1. **F1 + F2 before anything else** — both produce silent wrong results on queries that will appear in the K2/K4 equivalence and bench runs, and both are small, planner-side fixes (attrs union; LIMIT preconditions).
2. **F4** (shrink `type_supported` to the freeze) — one switch statement, eliminates two latent bugs and aligns code with the doc.
3. **F3** (error-path cleanup) — required by the design's own binding contract; do it before K4 measurement so leak behavior doesn't pollute long bench runs.
4. **F5** (metadata-driven HS2 conversion) — before trusting the multiset equivalence gate.
5. F6–F9 opportunistically, or fold into PR-K3 since the selector rework touches the same files.
