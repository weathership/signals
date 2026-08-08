# PR-K0 complete: link libkudu_client + stub exec_kudu

**Date:** 2026-08-07  
**Design:** `components/impala_fdw/docs/kudu_scan.md` rev 0.2.1

## Landed

- `src/exec_kudu.h` / `src/exec_kudu.cpp` — C ABI stub; `open` returns not-implemented; touches `KuduClientBuilder` so link requires libkudu_client
- `Makefile` — `KUDU_CLIENT_LIBDIR` + `KUDU_CLIENT_INCDIR` (split; headers not under `.devenv/impala`); auto `IMPALA_FDW_WITH_KUDU=1` when both present
- `devenv.nix` `impala-fdw:build` — resolves lib/inc, exports flags, `ldd` greps kudu_client when ON; Darwin/missing → HS2-only no hard fail

## Exit verified

- `devenv tasks run impala-fdw:build` succeeds
- `impala_fdw.so` links `libkudu_client`
- Runtime behavior unchanged (Begin still demotes kudu_scan → HS2)

## Next

PR-K1: OpenTable + projection + safety gate (refuse kudu when remote_exprs non-empty) + OpenTable success cache
