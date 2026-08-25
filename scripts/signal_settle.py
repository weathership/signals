#!/usr/bin/env python3
"""Settle closed hours of signal_tier0 (Kudu) into signal_tier1 (Iceberg+HDF5).

Guru: #SL.00000025.TIERUP

Per closed UTC hour H:
  1. read   signal_tier0 WHERE epoch_hour = H   (Postgres kudu_scan FT, :5455)
  2. write  signal_hour_H.h5                     (schema_version 2, exact ints/decimals)
  3. upload s3://signals-dataproducts/iceberg/signals_dataproducts/signal_tier1/data/epoch_hour=H/
  4. append to Iceberg signal_tier1 via Polaris with manifest bounds (IcebergHdf5Register)
  5. verify Impala count(signal_tier1 WHERE epoch_hour = H) == rows written

Kudu keeps whole days; once every hour of a day is verified in tier1,
``--drop-days`` retires that day with DROP RANGE PARTITION (never a row DELETE),
which is the only expiry valve the hot tier has. The union view masks tier1
rows for any epoch_hour still present in Kudu, so a settled-but-not-yet-dropped
hour never double-counts.

State lives in signal_settle_state (Postgres :5455), one row per hour.

Run under a Python with h5py + boto3 (the gaius venv): `just signal-settle`.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

GURU = "#SL.00000025.TIERUP"
ROOT = Path(__file__).resolve().parents[1]
ANALOG_DIR = Path(os.environ.get("SIGNAL_ANALOG_DIR", "/tmp/signal-analog"))
S3_BUCKET = "signals-dataproducts"
S3_PREFIX = "iceberg/signals_dataproducts/signal_tier1/data"
PG = dict(
    host=os.environ.get("SIGNALS_PGHOST", "127.0.0.1"),
    port=os.environ.get("SIGNALS_PGPORT", "5455"),
    user=os.environ.get("SIGNALS_PGUSER", "signals"),
    db=os.environ.get("SIGNALS_PGDATABASE", "signals"),
)
HOURS_PER_DAY = 24


def psql(sql: str, *, tuples: bool = True) -> str:
    env = os.environ.copy()
    env.setdefault("PGPASSWORD", "signals")
    cmd = ["psql", "-h", PG["host"], "-p", PG["port"], "-U", PG["user"], "-d", PG["db"],
           "-X", "-v", "ON_ERROR_STOP=1", "-c", sql]
    if tuples:
        cmd[1:1] = ["-At", "-F", "\t"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    if proc.returncode != 0:
        raise SystemExit(f"{GURU} psql: {proc.stderr.strip()}\n  sql: {sql[:200]}")
    return proc.stdout


def ensure_state() -> None:
    psql(
        """
        CREATE TABLE IF NOT EXISTS signal_settle_state (
          epoch_hour  integer PRIMARY KEY,
          rows        bigint NOT NULL,
          h5_bytes    bigint NOT NULL,
          s3_uri      text   NOT NULL,
          registered  timestamptz,
          verified    timestamptz,
          dropped     timestamptz
        )
        """,
        tuples=False,
    )


def read_hour(hour: int) -> list[dict]:
    out = psql(
        "SELECT ts_ns, series_id, src, gpu, inst, val_i, val_d "
        f"FROM signal_tier0 WHERE epoch_hour = {int(hour)}"
    )
    rows: list[dict] = []
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) < 7:
            continue
        rows.append(
            {
                "ts_ns": int(p[0]),
                "series_id": int(p[1]),
                "src": int(p[2]),
                "gpu": int(p[3]) if p[3] != "" else None,
                "inst": int(p[4]) if p[4] != "" else None,
                "val_i": int(p[5]) if p[5] != "" else None,
                "val_d": Decimal(p[6]) if p[6] != "" else None,
            }
        )
    return rows


def write_h5(hour: int, rows: list[dict]) -> Path:
    sys.path.insert(0, str(semantics_py()))
    from hdf5_iceberg.signal_layout import write_signal_hdf5

    ANALOG_DIR.mkdir(parents=True, exist_ok=True)
    return write_signal_hdf5(ANALOG_DIR / f"signal_hour_{hour}.h5", rows, epoch_hour=hour)


def semantics_py() -> Path:
    env = os.environ.get("SEMANTICS_HOME")
    base = Path(env) if env else Path.home() / "local/src/zndx/gaius/external/semantics"
    return base / "python/hdf5_iceberg/src"


def upload(path: Path, hour: int) -> tuple[str, str]:
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3", "http://127.0.0.1:9010"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "rustfsadmin"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "rustfsadmin"),
        region_name="us-east-1",
    )
    key = f"{S3_PREFIX}/epoch_hour={hour}/{path.name}"
    client.upload_file(str(path), S3_BUCKET, key)
    return f"s3://{S3_BUCKET}/{key}", f"s3a://{S3_BUCKET}/{key}"


def register(hour: int, s3a: str, size: int, records: int, local: Path) -> None:
    runner = ROOT / "scripts" / "iceberg_hdf5_register.sh"
    proc = subprocess.run(
        [str(runner), "signal_tier1", str(hour), s3a, str(size), str(records), str(local)],
        capture_output=True, text=True, timeout=900,
    )
    if proc.returncode != 0:
        raise SystemExit(f"{GURU} register: {proc.stderr.strip()[-800:]}")
    print(proc.stdout.strip())


def impala_count(hour: int) -> int:
    # impala_query.py needs the signals venv (impyla); this script runs under
    # the gaius venv (h5py, boto3). Bridge with `uv run` in the signals tree,
    # with the env vars a gaius-launched shell leaks removed.
    env = {k: v for k, v in os.environ.items()
           if k not in ("JAVA_HOME", "DEVENV_RUNTIME", "VIRTUAL_ENV")}
    proc = subprocess.run(
        ["uv", "run", "--quiet", "python", "scripts/impala_query.py", "-q",
         f"SELECT count(*) FROM signals_dataproducts.signal_tier1 WHERE epoch_hour = {int(hour)}"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=600, env=env,
    )
    if proc.returncode != 0:
        raise SystemExit(f"{GURU} impala verify: {proc.stderr.strip()[-400:]}")
    last = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
    return int(last.strip().split()[-1])


def settle(hour: int, *, no_upload: bool) -> int:
    ensure_state()
    done = psql(f"SELECT verified FROM signal_settle_state WHERE epoch_hour = {hour}").strip()
    if done:
        print(f"hour {hour} already verified at {done}")
        return 0
    rows = read_hour(hour)
    if not rows:
        raise SystemExit(f"{GURU} signal_tier0 has no rows for epoch_hour={hour}")
    path = write_h5(hour, rows)
    size = path.stat().st_size
    print(f"analog {path} rows={len(rows)} bytes={size} hour={hour}")
    if no_upload:
        return 0
    s3, s3a = upload(path, hour)
    psql(
        "INSERT INTO signal_settle_state (epoch_hour, rows, h5_bytes, s3_uri) "
        f"VALUES ({hour}, {len(rows)}, {size}, '{s3}') "
        "ON CONFLICT (epoch_hour) DO UPDATE SET rows = EXCLUDED.rows, "
        "h5_bytes = EXCLUDED.h5_bytes, s3_uri = EXCLUDED.s3_uri",
        tuples=False,
    )
    register(hour, s3a, size, len(rows), path)
    psql(f"UPDATE signal_settle_state SET registered = now() WHERE epoch_hour = {hour}",
         tuples=False)
    n = impala_count(hour)
    if n != len(rows):
        raise SystemExit(
            f"{GURU} verify: Impala signal_tier1 epoch_hour={hour} has {n} rows, "
            f"wrote {len(rows)}. Not marking verified; Kudu day is NOT dropped."
        )
    psql(f"UPDATE signal_settle_state SET verified = now() WHERE epoch_hour = {hour}",
         tuples=False)
    print(f"verified hour {hour}: {n} rows in tier1")
    return 0


def drop_days() -> int:
    """DROP RANGE PARTITION for every closed day whose 24 hours are verified."""
    ensure_state()
    today0 = (int(datetime.now(timezone.utc).timestamp()) // 3600 // HOURS_PER_DAY) * HOURS_PER_DAY
    out = psql(
        "SELECT (epoch_hour / 24) * 24 AS day0, count(*) FILTER (WHERE verified IS NOT NULL), "
        "count(*) FILTER (WHERE dropped IS NOT NULL) "
        "FROM signal_settle_state GROUP BY 1 ORDER BY 1"
    )
    rc = 0
    for line in out.splitlines():
        day0, n_ver, n_drop = (int(x) for x in line.split("\t"))
        if day0 >= today0:
            continue  # still the hot window
        if n_ver < HOURS_PER_DAY:
            print(f"day {day0}: {n_ver}/24 verified — keeping Kudu")
            continue
        if n_drop == HOURS_PER_DAY:
            continue
        ddl = (
            "ALTER TABLE signals_dataproducts.signal_tier0 "
            f"DROP RANGE PARTITION {day0} <= VALUES < {day0 + HOURS_PER_DAY}"
        )
        psql(f"SELECT impala_fdw_exec('impala_kudu_srv', $q${ddl}$q$)")
        psql(
            "UPDATE signal_settle_state SET dropped = now() "
            f"WHERE epoch_hour >= {day0} AND epoch_hour < {day0 + HOURS_PER_DAY}",
            tuples=False,
        )
        print(f"day {day0}: 24/24 verified → dropped Kudu range")
    return rc


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hour", type=int, help="UTC epoch hour (default: previous hour)")
    p.add_argument("--backfill", type=int, default=0,
                   help="also settle this many earlier closed hours if unverified")
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--drop-days", action="store_true",
                   help="retire fully-verified closed days from Kudu")
    a = p.parse_args()
    if a.drop_days:
        return drop_days()
    hour = a.hour if a.hour is not None else int(datetime.now(timezone.utc).timestamp()) // 3600 - 1
    rc = 0
    for h in range(hour - a.backfill, hour + 1):
        rc |= settle(h, no_upload=a.no_upload)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
