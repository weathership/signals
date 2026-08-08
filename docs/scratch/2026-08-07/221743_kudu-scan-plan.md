# Plan: impala_fdw direct Kudu (`kudu_scan`) — solidified

**Binding design:** `components/impala_fdw/docs/kudu_scan.md` (Approved rev 0.2.1 — implement K0+)  
**Full copy:** this directory `*_kudu-scan-design-solid.md`  
**Trigger:** Frontier harness ~2.5s/hop HS2 floor with correct IN pushdown.

## Why now

Batch size does not help; deparse works. Pull `libkudu_client` before more HS2 pooling for Atlas adjacency. **Implementation starts at PR-K0** (OQs 1–3 resolved 2026-08-07).

## PR sequence

| PR | Scope | Exit |
|----|--------|------|
| **K0** | Link `libkudu_client` (`LIBDIR`+`INCDIR`); stub `exec_kudu` | `.so` loads when WITH_KUDU |
| **K1** | OpenTable + **table cache** + projection + **safety gate** (no preds if remote_exprs) | Projection SELECT via kudu_scan; cache hit on re-open |
| **K2** | Typed eq/IN/null preds; Atlas types; regression SQL | Equivalence vs HS2 frozen seed |
| **K3** | Strict promote + fallback + LIMIT + parallel_unsafe | Edge hop promotable to kudu_scan |
| **K4** | Frontier bench before/after; **flip Atlas FTs → `access=auto`** | hop1 **&lt; 50ms**; ≥10×; FT defaults auto |
| **K5** | Kerberos (later) | S3 identity |

## Normative promotion (rev 0.2)

- Full PK equality → `gov.pk_lookup` → auto kudu_scan  
- HASH/IN on allowlist `{src,dst,guid,qn_digest,entity_guid}` → `gov.filtered_scan` → auto  
- Incomplete PK must **not** be labeled pk_lookup  
- K1: refuse kudu when `remote_exprs != NIL`

## Acceptance

1. EXPLAIN plan-time AccessMethod kudu_scan; ANALYZE shows effective path  
2. Bench hop_ms ≥10× vs HS2 baseline  
3. Row multisets match HS2 on frozen seed (READ_LATEST)
