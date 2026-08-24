#!/usr/bin/env python3
"""Live tinybox GPU metrics → jsonl + Kudu gpu_metrics_tier0.

Stdlib sampling always runs (nvidia-smi). HS2 INSERT starts once Impala
can see the Kudu table. Guru: #SL.00000024.GPUINGEST
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

GURU = "#SL.00000024.GPUINGEST"
JSONL = Path(os.environ.get("GPU_METRICS_JSONL", "/tmp/gpu-metrics-hour.jsonl"))
STATUS = Path(os.environ.get("GPU_METRICS_STATUS", "/tmp/gpu-metrics-ingest.status"))
INTERVAL_S = float(os.environ.get("GPU_METRICS_INTERVAL_S", "1"))
TABLE = "signals_dataproducts.gpu_metrics_tier0"
HOST = os.environ.get("SIGNALS_KRB_HOST", "tinybox.dev.vista.zndx.org")
NVIDIA_SMI = os.environ.get("NVIDIA_SMI", "nvidia-smi")
_ROOT = Path(os.environ.get("SIGNALS_ROOT", str(Path(__file__).resolve().parents[1])))
CPP_CREATE = os.environ.get("GPU_KUDU_CREATE", "/tmp/gpu_kudu_create")
CPP_INGEST = os.environ.get("GPU_KUDU_INGEST", "/tmp/gpu_kudu_ingest")
# HS2 CREATE TABLE STORED AS Kudu hits Java SASL (KUDU-2121). Retry slowly.
HS2_RETRY_S = float(os.environ.get("GPU_METRICS_HS2_RETRY_S", "60"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def epoch_hour(ts: datetime | None = None) -> int:
    t = ts or _utc_now()
    return int(t.timestamp()) // 3600


def sample_gpus() -> list[dict]:
    cmd = [
        NVIDIA_SMI,
        "--query-gpu=index,power.draw,utilization.gpu,memory.used,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    rows: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            raise RuntimeError(f"{GURU} nvidia-smi parse: {line!r}")
        rows.append(
            {
                "i": int(float(parts[0])),
                "w": float(parts[1]),
                "u": float(parts[2]),
                "m": float(parts[3]),
                "t": float(parts[4]),
            }
        )
    if not rows:
        raise RuntimeError(f"{GURU} nvidia-smi returned no GPUs")
    return rows


def append_jsonl(ts: datetime, gpus: list[dict]) -> None:
    rec = {"ts": ts.isoformat(), "gpus": gpus, "host": socket.gethostname()}
    with JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def write_status(**kw: object) -> None:
    payload = {"ts": _utc_now().isoformat(), **kw}
    STATUS.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _krb_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("KRB5_CONFIG", str(_ROOT / ".devenv/kdc/krb5.conf"))
    env.setdefault("KUDU_MASTERS", f"{HOST}:7051")
    if not env.get("KRB5CCNAME"):
        cc = Path("/tmp") / f"krb5cc_{os.getuid()}"
        env["KRB5CCNAME"] = str(cc if cc.exists() else _ROOT / ".devenv/kdc/krb5cc")
    return env


def _hs2():
    sys.modules.setdefault("thrift.protocol.fastbinary", None)
    sys.modules.setdefault("thrift.protocol.fastproto", None)
    root = str(_ROOT)
    if root not in sys.path:
        sys.path.insert(0, str(_ROOT / "src"))
    os.chdir(root)
    from signals.impala import impala_connect  # noqa: WPS433

    return impala_connect()


def cpp_ensure_table() -> None:
    exe = Path(CPP_CREATE)
    if not exe.is_file() or not os.access(exe, os.X_OK):
        raise RuntimeError(f"{GURU} missing C++ create helper {exe}")
    r = subprocess.run(
        [str(exe), str(epoch_hour())],
        env=_krb_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"{GURU} cpp create: {(r.stderr or r.stdout).strip()}")


def _rows_csv(ts: datetime, gpus: list[dict]) -> str:
    eh = epoch_hour(ts)
    ts_ns = int(ts.timestamp() * 1_000_000_000)
    lines = [
        f"{eh},{ts_ns},{g['i']},{g['w']},{g['u']},{g['m']},{g['t']}" for g in gpus
    ]
    return "\n".join(lines) + "\n"


def cpp_upsert_csv(csv_text: str) -> int:
    exe = Path(CPP_INGEST)
    if not exe.is_file() or not os.access(exe, os.X_OK):
        raise RuntimeError(f"{GURU} missing C++ ingest helper {exe}")
    r = subprocess.run(
        [str(exe)],
        input=csv_text,
        env=_krb_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"{GURU} cpp ingest: {(r.stderr or r.stdout).strip()}")
    out = (r.stdout or "").strip()
    if out.startswith("upserted "):
        return int(out.split()[1])
    return csv_text.count("\n")


def ensure_table(cur) -> None:
    h = epoch_hour()
    cur.execute("CREATE DATABASE IF NOT EXISTS signals_dataproducts")
    cur.execute(f"SHOW TABLES IN signals_dataproducts")
    names = {str(r[0]) for r in (cur.fetchall() or [])}
    if "gpu_metrics_tier0" not in names:
        # HASH+RANGE like details_tier0. Master addresses skip HMS table create
        # when catalog already talks to Kudu.
        parts = ",\n  ".join(
            [f"PARTITION VALUES < {h - 1}"]
            + [
                f"PARTITION {h + i} <= VALUES < {h + i + 1}"
                for i in range(-1, 4)
            ]
        )
        ddl = f"""
CREATE TABLE signals_dataproducts.gpu_metrics_tier0 (
  epoch_hour INT,
  ts_ns BIGINT,
  gpu_index INT,
  power_w FLOAT,
  util_pct FLOAT,
  mem_used_mb FLOAT,
  temp_c FLOAT,
  PRIMARY KEY (epoch_hour, ts_ns, gpu_index)
)
PARTITION BY HASH (gpu_index) PARTITIONS 2,
RANGE (epoch_hour) (
  {parts}
)
STORED AS KUDU
TBLPROPERTIES (
  'kudu.master_addresses' = '{HOST}:7051',
  'kudu.num_tablet_replicas' = '1',
  'signals.tier' = '0',
  'signals.expire' = 'drop_range_partition',
  'signals.range_unit' = 'hour',
  'signals.product' = 'gaius.machine.gpu_metrics'
)
"""
        cur.execute(ddl)
    # Keep a live hour range so inserts do not fail at the hour boundary.
    for i in range(-1, 4):
        lo, hi = h + i, h + i + 1
        try:
            cur.execute(
                f"ALTER TABLE {TABLE} ADD IF NOT EXISTS RANGE PARTITION "
                f"{lo} <= VALUES < {hi}"
            )
        except Exception as e:
            msg = str(e)
            if "already exists" in msg.lower() or "duplicate" in msg.lower():
                continue
            # Impala dialect may lack IF NOT EXISTS — ignore overlap.
            if "overlap" in msg.lower() or "RANGE" in msg:
                continue
            raise


def insert_rows(cur, ts: datetime, gpus: list[dict]) -> int:
    eh = epoch_hour(ts)
    ts_ns = int(ts.timestamp() * 1_000_000_000)
    values = ", ".join(
        f"({eh}, {ts_ns}, {g['i']}, {g['w']}, {g['u']}, {g['m']}, {g['t']})"
        for g in gpus
    )
    cur.execute(f"INSERT INTO {TABLE} VALUES {values}")
    return len(gpus)


def backfill_jsonl(cur, after_ns: int = 0) -> int:
    if not JSONL.exists():
        return 0
    n = 0
    batch: list[str] = []
    with JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            ts = datetime.fromisoformat(rec["ts"])
            ts_ns = int(ts.timestamp() * 1_000_000_000)
            if ts_ns <= after_ns:
                continue
            eh = epoch_hour(ts)
            for g in rec["gpus"]:
                batch.append(
                    f"({eh}, {ts_ns}, {g['i']}, {g['w']}, {g['u']}, {g['m']}, {g['t']})"
                )
            if len(batch) >= 120:
                cur.execute(f"INSERT INTO {TABLE} VALUES " + ", ".join(batch))
                n += len(batch)
                batch = []
    if batch:
        cur.execute(f"INSERT INTO {TABLE} VALUES " + ", ".join(batch))
        n += len(batch)
    return n


def kudu_max_ts(cur) -> int:
    try:
        cur.execute(f"SELECT max(ts_ns) FROM {TABLE}")
        row = cur.fetchone()
        if not row or row[0] is None:
            return 0
        return int(row[0])
    except Exception:
        return 0


def main() -> int:
    JSONL.parent.mkdir(parents=True, exist_ok=True)
    kudu_ok = False
    kudu_via = ""
    kudu_err = ""
    inserted = 0
    ticks = 0
    cur = None
    cpp_buf: list[str] = []
    last_hs2_try = 0.0
    started = _utc_now()
    write_status(phase="start", jsonl=str(JSONL), interval_s=INTERVAL_S)

    while True:
        t0 = time.monotonic()
        ts = _utc_now()
        try:
            gpus = sample_gpus()
        except Exception as e:
            write_status(phase="sample_fail", error=f"{GURU} {e}")
            time.sleep(max(1.0, INTERVAL_S))
            continue
        append_jsonl(ts, gpus)
        ticks += 1

        now_m = time.monotonic()
        if not kudu_ok and (now_m - last_hs2_try) >= HS2_RETRY_S:
            last_hs2_try = now_m
            try:
                conn = _hs2()
                cur = conn.cursor()
                ensure_table(cur)
                nbf = backfill_jsonl(cur, after_ns=kudu_max_ts(cur))
                kudu_ok = True
                kudu_via = "hs2"
                kudu_err = ""
                inserted += nbf
            except Exception as e:
                kudu_err = f"{GURU} {type(e).__name__}: {e}"
                cur = None
                try:
                    cpp_ensure_table()
                    kudu_via = "cpp"
                    kudu_err = f"{kudu_err} (cpp table ok)"
                except Exception as ce:
                    kudu_err = f"{kudu_err}; cpp: {ce}"

        if kudu_ok and cur is not None:
            try:
                inserted += insert_rows(cur, ts, gpus)
            except Exception as e:
                kudu_ok = False
                kudu_via = ""
                kudu_err = f"{GURU} insert {type(e).__name__}: {e}"
                cur = None

        if not kudu_ok or kudu_via == "cpp":
            cpp_buf.append(_rows_csv(ts, gpus).rstrip("\n"))
            if len(cpp_buf) >= 30:
                try:
                    cpp_ensure_table()
                    n = cpp_upsert_csv("\n".join(cpp_buf) + "\n")
                    inserted += n
                    kudu_via = "cpp"
                    kudu_err = ""
                    cpp_buf = []
                except Exception as e:
                    kudu_err = f"{GURU} cpp {type(e).__name__}: {e}"

        if ticks == 1 or ticks % 30 == 0:
            write_status(
                phase="run",
                ticks=ticks,
                inserted=inserted,
                kudu_ok=kudu_ok or kudu_via == "cpp",
                kudu_via=kudu_via,
                kudu_err=kudu_err,
                gpus=len(gpus),
                last_w=[g["w"] for g in gpus],
                jsonl_bytes=JSONL.stat().st_size if JSONL.exists() else 0,
                started=started.isoformat(),
                elapsed_s=int((_utc_now() - started).total_seconds()),
                epoch_hour=epoch_hour(ts),
            )
        dt = time.monotonic() - t0
        time.sleep(max(0.05, INTERVAL_S - dt))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        write_status(phase="stop")
        raise SystemExit(0)
