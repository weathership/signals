#!/usr/bin/env python3
"""Frontier batch harness for atlas_edge_out / atlas_edge_in.

Measures chunk size × hop latency × EXPLAIN remote SQL for the procedural
frontier loop (freeze: not WITH RECURSIVE over FDW).

stdlib only (subprocess psql + HS2 client) — no torch/uv project sync.

  python3 scripts/atlas_frontier_bench.py --write-scratch
  python3 scripts/atlas_frontier_bench.py --nodes 100 --batches 16,64,256
  python3 scripts/atlas_frontier_bench.py --skip-seed --force-access kudu_scan
  python3 scripts/atlas_frontier_bench.py --skip-seed --compare  # HS2 vs kudu
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EDGE_FTS = ("atlas_edge_out", "atlas_edge_in")
VALID_ACCESS = ("impala_sql", "kudu_scan", "auto")


def node_guid(n: int) -> bytes:
    return b"\x00" * 8 + struct.pack(">Q", n)


def guid_hex(b: bytes) -> str:
    return b.hex().upper()


def hs2(hs2_bin: str, sql: str, timeout: float = 180.0) -> str:
    r = subprocess.run(
        [hs2_bin, sql],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise RuntimeError(f"HS2 failed ({r.returncode}): {out}\nSQL={sql[:240]}")
    return out


def psql(sql: str, pg: dict, timeout: float = 120.0) -> str:
    env = os.environ.copy()
    env["PGHOST"] = pg["host"]
    env["PGPORT"] = str(pg["port"])
    env["PGDATABASE"] = pg["db"]
    r = subprocess.run(
        ["psql", "-h", pg["host"], "-p", str(pg["port"]), "-d", pg["db"],
         "-v", "ON_ERROR_STOP=1", "-At", "-c", sql],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr or r.stdout}\nSQL={sql[:240]}")
    return r.stdout


def psql_tuples(sql: str, pg: dict) -> list[list[str]]:
    out = psql(sql, pg)
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        rows.append(line.split("|"))
    return rows


def seed_graph(hs2_bin: str, n_nodes: int, fanout: int, elabel: str = "LINKS") -> int:
    """Seed edges with hex32 STRING keys (Impala Kudu cannot predicate BINARY)."""
    for t in ("atlas.edge_out", "atlas.edge_in"):
        try:
            hs2(hs2_bin, f"DELETE FROM {t}")
        except RuntimeError as e:
            print(f"WARN delete {t}: {e}", file=sys.stderr)

    edges: list[tuple[int, int]] = []
    for i in range(n_nodes - 1):
        edges.append((i, i + 1))
        for k in range(1, fanout + 1):
            j = (i + 1 + k * 7) % n_nodes
            if j != i:
                edges.append((i, j))

    batch = 50
    n_written = 0
    for off in range(0, len(edges), batch):
        chunk = edges[off : off + batch]
        outs, ins = [], []
        for s, d in chunk:
            sh, dh = guid_hex(node_guid(s)).lower(), guid_hex(node_guid(d)).lower()
            outs.append(f"('{sh}', '{elabel}', '{dh}', 'vertex')")
            ins.append(f"('{dh}', '{elabel}', '{sh}', 'vertex')")
        hs2(hs2_bin, f"UPSERT INTO atlas.edge_out VALUES {', '.join(outs)}")
        hs2(hs2_bin, f"UPSERT INTO atlas.edge_in VALUES {', '.join(ins)}")
        n_written += len(chunk)
        if (off // batch) % 10 == 0:
            print(f"  … seeded {n_written}/{len(edges)} edges", flush=True)
    return n_written


def explain(pg: dict, sql: str) -> str:
    # EXPLAIN returns one column; use -At
    env = os.environ.copy()
    r = subprocess.run(
        ["psql", "-h", pg["host"], "-p", str(pg["port"]), "-d", pg["db"],
         "-v", "ON_ERROR_STOP=1", "-c", f"EXPLAIN (VERBOSE, COSTS OFF) {sql}"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    if r.returncode != 0:
        return f"EXPLAIN ERROR: {r.stderr}"
    return r.stdout


def parse_access_method(explain_text: str) -> str:
    """Extract Impala AccessMethod from EXPLAIN VERBOSE."""
    m = re.search(r"Impala AccessMethod:\s*(\S+)", explain_text or "")
    if m:
        return m.group(1)
    m = re.search(r"AccessMethod:\s*(\S+)", explain_text or "")
    return m.group(1) if m else "unknown"


def parse_shape_id(explain_text: str) -> str:
    m = re.search(r"Impala ShapeId:\s*(\S+)", explain_text or "")
    return m.group(1) if m else "unknown"


def set_edge_access(pg: dict, access: str) -> None:
    """Force foreign-table access option on both edge FTs (PR-K4)."""
    if access not in VALID_ACCESS:
        raise ValueError(f"access must be one of {VALID_ACCESS}, got {access!r}")
    for ft in EDGE_FTS:
        # SET if present, else ADD
        try:
            psql(
                f"ALTER FOREIGN TABLE {ft} OPTIONS (SET access '{access}')",
                pg,
            )
        except RuntimeError:
            psql(
                f"ALTER FOREIGN TABLE {ft} OPTIONS (ADD access '{access}')",
                pg,
            )
    print(f"Set {', '.join(EDGE_FTS)} access='{access}'", flush=True)


def explain_analyze_ms(pg: dict, sql: str) -> tuple[float | None, str]:
    """Backend Execution Time from EXPLAIN ANALYZE (excludes psql process spawn)."""
    env = os.environ.copy()
    r = subprocess.run(
        [
            "psql",
            "-h",
            pg["host"],
            "-p",
            str(pg["port"]),
            "-d",
            pg["db"],
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            f"EXPLAIN (ANALYZE, TIMING ON, COSTS OFF, SUMMARY ON) {sql}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    text = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return None, f"EXPLAIN ANALYZE ERROR: {text}"
    # Prefer "Execution Time: 1.234 ms"
    m = re.search(r"Execution Time:\s*([0-9.]+)\s*ms", text)
    if m:
        return float(m.group(1)), text
    return None, text


def frontier_hop(
    pg: dict,
    frontier: set[str],
    batch_size: int,
    direction: str = "out",
    measure: str = "wall",
) -> tuple[set[str], list[str], list[float], list[float], str | None]:
    """One hop over hex32 STRING keys.

    measure: "wall" | "exec" | "session" (session uses long-lived psql -f).
    Returns (next_set, raw_dst_rows, wall_ms_list, exec_ms_list, explain).
    raw_dst_rows preserves multiset for N2 equivalence (not set-collapsed).
    """
    table = "atlas_edge_out" if direction == "out" else "atlas_edge_in"
    src_col = "src" if direction == "out" else "dst"
    dst_col = "dst" if direction == "out" else "src"

    items = list(frontier)
    nxt: set[str] = set()
    raw_rows: list[str] = []
    chunk_ms: list[float] = []
    exec_ms: list[float] = []
    sample_explain: str | None = None

    for i in range(0, len(items), batch_size):
        chunk = items[i : i + batch_size]
        arr = ", ".join("'" + c + "'" for c in chunk)
        sql = (
            f"SELECT {dst_col} FROM {table} "
            f"WHERE {src_col} = ANY (ARRAY[{arr}]::text[])"
        )
        if i == 0:
            sample_explain = explain(pg, sql)
        if measure == "exec":
            ems, _ = explain_analyze_ms(pg, sql)
            if ems is not None:
                exec_ms.append(ems)
            t0 = time.perf_counter()
            rows = psql_tuples(sql, pg)
            chunk_ms.append((time.perf_counter() - t0) * 1000.0)
        else:
            t0 = time.perf_counter()
            rows = psql_tuples(sql, pg)
            chunk_ms.append((time.perf_counter() - t0) * 1000.0)
        for row in rows:
            if row and row[0]:
                v = row[0].lower()
                nxt.add(v)
                raw_rows.append(v)
    return nxt, raw_rows, chunk_ms, exec_ms, sample_explain


def session_warm_probe(pg: dict, g0: str) -> dict:
    """N4: three identical point hops in one backend — cold vs warm cache.

    Uses a single psql session; reports EXPLAIN ANALYZE Execution Time for
    probes 1 (cold) and 2–3 (warm client/table cache).
    """
    sql = (
        f"SELECT dst FROM atlas_edge_out WHERE src = ANY "
        f"(ARRAY['{g0}']::text[])"
    )
    script = f"""
\\set ON_ERROR_STOP on
EXPLAIN (ANALYZE, TIMING ON, COSTS OFF, SUMMARY ON) {sql};
EXPLAIN (ANALYZE, TIMING ON, COSTS OFF, SUMMARY ON) {sql};
EXPLAIN (ANALYZE, TIMING ON, COSTS OFF, SUMMARY ON) {sql};
SELECT string_agg(dst, ',' ORDER BY dst) FROM atlas_edge_out
WHERE src = ANY (ARRAY['{g0}']::text[]);
"""
    env = os.environ.copy()
    env["PGHOST"] = pg["host"]
    env["PGPORT"] = str(pg["port"])
    env["PGDATABASE"] = pg["db"]
    r = subprocess.run(
        ["psql", "-h", pg["host"], "-p", str(pg["port"]), "-d", pg["db"],
         "-v", "ON_ERROR_STOP=1"],
        input=script,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    text = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise RuntimeError(f"warm probe failed: {text}")
    times = [float(x) for x in re.findall(r"Execution Time:\s*([0-9.]+)\s*ms", text)]
    # last non-empty line of -At would need -At; parse agg from output loosely
    m_rows = re.findall(r"string_agg\n[-+]+\n([^\n]+)", text)
    row_csv = m_rows[-1].strip() if m_rows else ""
    # fallback: lines that look like hex lists
    if not row_csv:
        for ln in reversed(text.splitlines()):
            if re.match(r"^[0-9a-f,]+$", ln.strip()):
                row_csv = ln.strip()
                break
    return {
        "session_warm": True,
        "exec_ms": times,
        "cold_exec_ms": times[0] if times else None,
        "warm_exec_ms": times[1] if len(times) > 1 else None,
        "warm2_exec_ms": times[2] if len(times) > 2 else None,
        "dst_multiset": dict(Counter(x for x in row_csv.split(",") if x)),
    }


def run_once(
    pg: dict,
    batch_size: int,
    depth: int,
    seed_nodes: int,
    access: str | None = None,
    measure: str = "wall",
) -> dict:
    g0 = guid_hex(node_guid(0)).lower()
    # Warm path (client cache / HS2 session) so hop1 is not pure cold-start
    try:
        psql_tuples(
            f"SELECT dst FROM atlas_edge_out WHERE src = ANY "
            f"(ARRAY['{g0}']::text[]) LIMIT 1",
            pg,
        )
    except RuntimeError as e:
        print(f"WARN warmup: {e}", file=sys.stderr)

    explain_any = explain(
        pg,
        f"SELECT dst FROM atlas_edge_out WHERE src = ANY "
        f"(ARRAY['{g0}']::text[])",
    )
    explain_in = explain(
        pg,
        f"SELECT dst FROM atlas_edge_out WHERE src IN ('{g0}')",
    )
    access_method = parse_access_method(explain_any)
    shape_id = parse_shape_id(explain_any)

    # Single-id exec-time baseline (design hop1 gate)
    hop1_sql = (
        f"SELECT dst FROM atlas_edge_out WHERE src = ANY "
        f"(ARRAY['{g0}']::text[])"
    )
    hop1_exec_ms, hop1_analyze = explain_analyze_ms(pg, hop1_sql)

    visited: set[str] = {g0}
    frontier: set[str] = {g0}
    hops: list[dict] = []
    all_raw_rows: list[str] = []  # multiset of hop outputs (N2)
    t0 = time.perf_counter()

    for d in range(1, depth + 1):
        if not frontier:
            break
        n_in = len(frontier)
        hop_t0 = time.perf_counter()
        nxt, raw_rows, chunk_ms, exec_ms, sample_ex = frontier_hop(
            pg, frontier, batch_size, measure=measure
        )
        hop_ms = (time.perf_counter() - hop_t0) * 1000.0
        new = nxt - visited
        visited |= new
        all_raw_rows.extend(raw_rows)
        hops.append(
            {
                "depth": d,
                "frontier_in": n_in,
                "frontier_out": len(new),
                "chunks": len(chunk_ms),
                "hop_ms": round(hop_ms, 3),
                "chunk_ms_sum": round(sum(chunk_ms), 3),
                "chunk_ms_max": round(max(chunk_ms), 3) if chunk_ms else 0,
                "exec_ms_sum": round(sum(exec_ms), 3) if exec_ms else None,
                "exec_ms_max": round(max(exec_ms), 3) if exec_ms else None,
                "ms_per_id_in": round(hop_ms / max(n_in, 1), 4),
                "row_multiset": dict(Counter(raw_rows)),
                "explain_sample": sample_ex,
            }
        )
        frontier = new

    total_ms = (time.perf_counter() - t0) * 1000.0
    hop1 = hops[0]["hop_ms"] if hops else None
    hop1_exec_from_hop = hops[0].get("exec_ms_sum") if hops else None
    return {
        "access": access,
        "access_method": access_method,
        "shape_id": shape_id,
        "batch_size": batch_size,
        "depth": depth,
        "seed_nodes": seed_nodes,
        "measure": measure,
        "total_ms": round(total_ms, 3),
        "visited": len(visited),
        "visited_set": sorted(visited),
        "row_multiset_all_hops": dict(Counter(all_raw_rows)),
        "final_frontier": len(frontier),
        "hop1_ms": hop1,
        "hop1_exec_ms": hop1_exec_ms,
        "hop1_exec_from_chunks": hop1_exec_from_hop,
        "hop1_analyze": hop1_analyze,
        "hops": hops,
        "explain_any": explain_any,
        "explain_in": explain_in,
        "pushdown_any_ok": "IN (" in explain_any or " IN " in explain_any,
        "pushdown_in_ok": "IN (" in explain_in or " IN " in explain_in,
        "kudu_path": "kudu_scan" in (access_method or ""),
    }


def run_suite(
    pg: dict,
    batches: list[int],
    depth: int,
    nodes: int,
    access: str | None,
    measure: str = "wall",
) -> list[dict]:
    if access:
        set_edge_access(pg, access)
    results = []
    for b in batches:
        print(
            f"Run access={access or 'current'} batch_size={b} depth={depth} "
            f"measure={measure} …",
            flush=True,
        )
        results.append(
            run_once(pg, b, depth, nodes, access=access, measure=measure)
        )
    return results


def summarize_compare(hs2: list[dict], kudu: list[dict]) -> dict:
    """Pair by batch_size; compute speedups and gate checks.

    Gates use backend Execution Time (hop1_exec_ms) when present — wall-clock
    includes psql process spawn and is not a fair kudu vs HS2 measure.
    """
    by_b_hs2 = {r["batch_size"]: r for r in hs2}
    by_b_kudu = {r["batch_size"]: r for r in kudu}
    pairs = []
    for b in sorted(set(by_b_hs2) & set(by_b_kudu)):
        h, k = by_b_hs2[b], by_b_kudu[b]
        # Prefer EXPLAIN ANALYZE execution time for hop1 single-id probe
        h1h = h.get("hop1_exec_ms") if h.get("hop1_exec_ms") is not None else h.get("hop1_ms") or 0
        h1k = k.get("hop1_exec_ms") if k.get("hop1_exec_ms") is not None else k.get("hop1_ms") or 0
        # B-sized hop wall for multi-id (chunk sum of exec if available)
        h_b = h["hops"][0] if h.get("hops") else {}
        k_b = k["hops"][0] if k.get("hops") else {}
        h_b_exec = h_b.get("exec_ms_sum") if h_b.get("exec_ms_sum") is not None else h_b.get("hop_ms")
        k_b_exec = k_b.get("exec_ms_sum") if k_b.get("exec_ms_sum") is not None else k_b.get("hop_ms")
        speed = (h1h / h1k) if h1k and h1k > 0 else None
        # N2: true set + multiset match (not mere counts)
        vset_h = set(h.get("visited_set") or [])
        vset_k = set(k.get("visited_set") or [])
        visited_set_match = vset_h == vset_k
        # per-hop row multisets
        hop_ms_match = True
        for hi, ki in zip(h.get("hops") or [], k.get("hops") or []):
            if hi.get("row_multiset") != ki.get("row_multiset"):
                hop_ms_match = False
                break
        if len(h.get("hops") or []) != len(k.get("hops") or []):
            hop_ms_match = False
        all_ms_match = (h.get("row_multiset_all_hops") or {}) == (
            k.get("row_multiset_all_hops") or {}
        )
        pairs.append(
            {
                "batch_size": b,
                "hs2_hop1_exec_ms": h.get("hop1_exec_ms"),
                "kudu_hop1_exec_ms": k.get("hop1_exec_ms"),
                "hs2_hop1_wall_ms": h.get("hop1_ms"),
                "kudu_hop1_wall_ms": k.get("hop1_ms"),
                "hs2_hop1_ms": h1h,
                "kudu_hop1_ms": h1k,
                "speedup_hop1": round(speed, 2) if speed else None,
                "hs2_b_hop_ms": h_b_exec,
                "kudu_b_hop_ms": k_b_exec,
                "hs2_total_ms": h["total_ms"],
                "kudu_total_ms": k["total_ms"],
                "hs2_visited": h["visited"],
                "kudu_visited": k["visited"],
                "visited_count_match": h["visited"] == k["visited"],
                "visited_set_match": visited_set_match,
                "hop_row_multiset_match": hop_ms_match,
                "all_hops_row_multiset_match": all_ms_match,
                "visited_match": visited_set_match and hop_ms_match and all_ms_match,
                "hs2_method": h.get("access_method"),
                "kudu_method": k.get("access_method"),
                "kudu_shape": k.get("shape_id"),
            }
        )

    # Design gates on backend exec time (first batch row is representative hop1 probe)
    first = pairs[0] if pairs else None
    b32 = next((p for p in pairs if p["batch_size"] == 32), None)
    hop1_k = first["kudu_hop1_ms"] if first else None
    b32_k = b32["kudu_b_hop_ms"] if b32 else None
    gates = {
        "metric": "EXPLAIN ANALYZE Execution Time (hop1_exec) + hop exec_ms_sum for B",
        "hop1_under_50ms": (hop1_k is not None and hop1_k < 50),
        "b32_under_100ms": (b32_k is not None and b32_k < 100),
        "visited_set_match": all(p["visited_set_match"] for p in pairs),
        "hop_row_multiset_match": all(p["hop_row_multiset_match"] for p in pairs),
        "all_hops_row_multiset_match": all(
            p["all_hops_row_multiset_match"] for p in pairs
        ),
        "visited_all_match": all(p["visited_match"] for p in pairs),
        "kudu_method_ok": all(
            p.get("kudu_method") and "kudu_scan" in str(p["kudu_method"])
            for p in pairs
        ),
        "min_speedup_hop1": min(
            (p["speedup_hop1"] for p in pairs if p["speedup_hop1"]),
            default=None,
        ),
        # ≥10× only when HS2 floor is high enough to measure (else N/A)
        "speedup_10x_when_hs2_gt_500ms": None,
    }
    high = [p for p in pairs if (p["hs2_hop1_ms"] or 0) >= 500]
    if high:
        gates["speedup_10x_when_hs2_gt_500ms"] = all(
            (p["speedup_hop1"] or 0) >= 10 for p in high
        )
    gates["pass"] = (
        gates["hop1_under_50ms"]
        and gates["b32_under_100ms"]
        and gates["visited_all_match"]
        and gates["kudu_method_ok"]
    )
    return {"pairs": pairs, "gates": gates}


def write_scratch(out: dict, batches: list[int], compare: bool) -> None:
    day = datetime.now().strftime("%Y-%m-%d")
    hhmmss = datetime.now().strftime("%H%M%S")
    d = Path("docs/scratch") / day
    d.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, indent=2)
    (d / f"{hhmmss}_atlas_frontier_bench.json").write_text(text)

    lines = [
        "# Atlas frontier batch harness (PR-K4)",
        "",
        f"nodes={out.get('nodes')} fanout={out.get('fanout')} depth={out.get('depth')}",
        f"force_access={out.get('force_access')} compare={compare}",
        "",
    ]
    if compare and "compare" in out:
        lines += [
            "## HS2 vs kudu_scan hop1",
            "",
            "| batch | hs2_exec_ms | kudu_exec_ms | speedup | B-hop kudu_ms | visited | method |",
            "|------:|------------:|-------------:|--------:|--------------:|:-------:|:-------|",
        ]
        for p in out["compare"]["pairs"]:
            lines.append(
                f"| {p['batch_size']} | {p['hs2_hop1_ms']} | {p['kudu_hop1_ms']} | "
                f"{p['speedup_hop1']} | {p.get('kudu_b_hop_ms')} | "
                f"{'Y' if p['visited_match'] else 'N'} | {p['kudu_method']} |"
            )
        g = out["compare"]["gates"]
        lines += [
            "",
            "## Gates (design K4 exit — backend Execution Time)",
            "",
            f"- metric: {g.get('metric')}",
            f"- hop1 exec &lt; 50 ms: **{g['hop1_under_50ms']}**",
            f"- B=32 hop exec &lt; 100 ms: **{g['b32_under_100ms']}**",
            f"- visited **set** match: **{g.get('visited_set_match')}**",
            f"- per-hop row multiset match: **{g.get('hop_row_multiset_match')}**",
            f"- all-hops row multiset match: **{g.get('all_hops_row_multiset_match')}**",
            f"- equivalence (set+multiset): **{g['visited_all_match']}**",
            f"- EXPLAIN kudu_scan: **{g['kudu_method_ok']}**",
            f"- min speedup hop1: **{g['min_speedup_hop1']}**",
            f"- 10× when HS2≥500ms: **{g.get('speedup_10x_when_hs2_gt_500ms')}**",
            f"- **PASS: {g['pass']}**",
            "",
        ]
        results = out.get("results_kudu") or out.get("results") or []
    else:
        results = out.get("results") or []
        lines += [
            "| batch | access | method | total_ms | visited | hop1_ms | hop1 in→out | pushdown |",
            "|------:|:-------|:-------|---------:|--------:|--------:|------------:|:--------:|",
        ]
        for r in results:
            h = r["hops"]
            h1 = h[0] if h else {}
            lines.append(
                f"| {r['batch_size']} | {r.get('access','')} | {r.get('access_method','')} | "
                f"{r['total_ms']} | {r['visited']} | {h1.get('hop_ms','')} | "
                f"{h1.get('frontier_in','')}→{h1.get('frontier_out','')} | "
                f"{'Y' if r['pushdown_any_ok'] else 'N'} |"
            )

    if results:
        lines += [
            "",
            f"## EXPLAIN (batch={results[0]['batch_size']}, ANY)",
            "```",
            results[0].get("explain_any", ""),
            "```",
        ]
    lines += [
        "",
        "## Notes",
        "- READ_LATEST; freeze seed (no concurrent UPSERT during compare).",
        "- Procedural frontier over FDW; AGE remains SoR for topology.",
    ]
    (d / f"{hhmmss}_atlas_frontier_bench.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote docs/scratch/{day}/{hhmmss}_atlas_frontier_bench.*", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5455)
    ap.add_argument("--db", default="signals")
    ap.add_argument("--hs2", default=os.environ.get("HS2_SQL", "/tmp/hs2_sql"))
    ap.add_argument("--nodes", type=int, default=100)
    ap.add_argument("--fanout", type=int, default=2)
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--batches", default="8,32,64,256")
    ap.add_argument("--skip-seed", action="store_true")
    ap.add_argument("--write-scratch", action="store_true")
    ap.add_argument(
        "--force-access",
        choices=VALID_ACCESS,
        default=None,
        help="ALTER edge FTs to this access before measuring",
    )
    ap.add_argument(
        "--compare",
        action="store_true",
        help="Run impala_sql then kudu_scan on the same seed; emit speedups + gates",
    )
    ap.add_argument(
        "--measure",
        choices=("wall", "exec"),
        default="exec",
        help="wall=psql spawn wall-clock; exec=also collect EXPLAIN ANALYZE times (default)",
    )
    ap.add_argument(
        "--warm-session",
        action="store_true",
        help="N4: also run multi-hop in one psql session (client cache hit path)",
    )
    args = ap.parse_args()

    pg = {"host": args.host, "port": args.port, "db": args.db}
    batches = [int(x) for x in args.batches.split(",") if x.strip()]

    if not args.skip_seed:
        if not os.path.isfile(args.hs2) or not os.access(args.hs2, os.X_OK):
            print(f"ERROR: HS2 client not executable: {args.hs2}", file=sys.stderr)
            return 1
        print(f"Seeding nodes={args.nodes} fanout={args.fanout} …", flush=True)
        n_e = seed_graph(args.hs2, args.nodes, args.fanout)
        print(f"Seeded {n_e} directed edges (×2 tables).", flush=True)

    out: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "nodes": args.nodes,
        "fanout": args.fanout,
        "depth": args.depth,
        "batches": batches,
        "force_access": args.force_access,
        "compare_mode": args.compare,
    }

    if args.compare:
        # Frozen seed: measure HS2 baseline then kudu (no reseed between)
        hs2_res = run_suite(
            pg, batches, args.depth, args.nodes, "impala_sql", measure=args.measure
        )
        kudu_res = run_suite(
            pg, batches, args.depth, args.nodes, "kudu_scan", measure=args.measure
        )
        out["results_hs2"] = hs2_res
        out["results_kudu"] = kudu_res
        out["compare"] = summarize_compare(hs2_res, kudu_res)
        out["measure"] = args.measure
        if args.warm_session:
            g0 = guid_hex(node_guid(0)).lower()
            warm = {}
            for access in ("impala_sql", "kudu_scan"):
                set_edge_access(pg, access)
                print(f"Warm-session probe access={access} …", flush=True)
                warm[access] = session_warm_probe(pg, g0)
            out["warm_session"] = warm
            wh, wk = warm.get("impala_sql"), warm.get("kudu_scan")
            if wh and wk:
                out["warm_session"]["dst_multiset_match"] = (
                    wh.get("dst_multiset") == wk.get("dst_multiset")
                )
                if wh.get("warm_exec_ms") and wk.get("warm_exec_ms"):
                    out["warm_session"]["warm_speedup"] = round(
                        wh["warm_exec_ms"] / wk["warm_exec_ms"], 2
                    )
                if wk.get("cold_exec_ms") and wk.get("warm_exec_ms"):
                    out["warm_session"]["kudu_cache_speedup"] = round(
                        wk["cold_exec_ms"] / wk["warm_exec_ms"], 2
                    )
        # leave FTs on kudu_scan for post-inspect; caller may flip to auto
    else:
        out["results"] = run_suite(
            pg,
            batches,
            args.depth,
            args.nodes,
            args.force_access,
            measure=args.measure,
        )
        out["measure"] = args.measure

    text = json.dumps(out, indent=2)
    print(text)

    if args.write_scratch:
        write_scratch(out, batches, args.compare)

    if args.compare:
        g = out["compare"]["gates"]
        print(
            f"\nK4 gates: hop1<50ms={g['hop1_under_50ms']} "
            f"b32<100ms={g['b32_under_100ms']} "
            f"visited={g['visited_all_match']} "
            f"method={g['kudu_method_ok']} "
            f"min_speedup={g['min_speedup_hop1']} "
            f"PASS={g['pass']}",
            file=sys.stderr,
        )
        return 0 if g["pass"] else 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
