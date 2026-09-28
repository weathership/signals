# Nautilus FSM and Brier ledger appendix

One Mermaid flowchart at `docs/current/src/appendix/nautilus-fsm-brier.md`,
same GitHub `flowchart` constraints as the DCGM appendix. Parsed with
Mermaid 11.4.1; Chromium rendered a ~5226×3264 SVG with the phase-gate,
health, directive, journal, and Fibonacci labels present.

The picture is `zndx.supervision.v1`, not `signals.ops` /
`ops-observations.jsonl`. Those stay the IT-ops method catalog
(`ops-fsm.md` now points here).

Score cell is observer × call_site × momentum bucket inside
`spec_version` + `engine_build`. Phase forecasts resolve only at that
phase's gate. Rows go protobuf-first to nisshi, then `kudu_scan` into
`nautilus_*_tier0`. Iceberg tier1 for these tables is still pending, so
the logical views are tier0-only. Signals instance is read-only:
every restart in `config/supervision/signals.textproto` is `NONE`,
epoch `2026-09-20.1` + `trunk`.
