#!/usr/bin/env python3
"""Settle a closed UTC hour of gpu_metrics_tier0 → Iceberg+HDF5 analog.

Reads jsonl (always) and optional HS2 Kudu rows, writes SysML analog HDF5,
uploads to s3://signals-dataproducts/iceberg/gpu_metrics_tier1/. Impala
CREATE/SELECT of the Iceberg table needs FileFormat.HDF5 (rebuilt HS2).

Guru: #SL.00000025.TIERUP
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

GURU = "#SL.00000025.TIERUP"
JSONL = Path(os.environ.get("GPU_METRICS_JSONL", "/tmp/gpu-metrics-hour.jsonl"))
ANALOG_DIR = Path(os.environ.get("GPU_METRICS_ANALOG_DIR", "/tmp/gpu-metrics-analog"))
S3_PREFIX = os.environ.get(
    "GPU_METRICS_S3_PREFIX",
    "s3://signals-dataproducts/iceberg/gpu_metrics_tier1",
)


def epoch_hour_of(ts: datetime) -> int:
    return int(ts.timestamp()) // 3600


def load_jsonl(hour: int) -> list[dict]:
    if not JSONL.exists():
        raise SystemExit(f"{GURU} missing {JSONL}")
    rows: list[dict] = []
    with JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            ts = datetime.fromisoformat(rec["ts"])
            if epoch_hour_of(ts) != hour:
                continue
            ts_ns = int(ts.timestamp() * 1_000_000_000)
            for g in rec["gpus"]:
                rows.append(
                    {
                        "ts_ns": ts_ns,
                        "gpu_index": int(g["i"]),
                        "power_w": float(g["w"]),
                        "util_pct": float(g["u"]),
                        "mem_used_mb": float(g["m"]),
                        "temp_c": float(g["t"]),
                    }
                )
    return rows


def write_h5(hour: int, rows: list[dict]) -> Path:
    analog = Path(
        os.environ.get(
            "SEMANTICS_ANALOG",
            str(
                Path(__file__).resolve().parents[3]
                / "zndx/gaius/external/semantics/analog"
            ),
        )
    )
    if not analog.exists():
        analog = Path("/home/rch/local/src/zndx/gaius/external/semantics/analog")
    sys.path.insert(0, str(analog))
    from generate_sdg_hdf5 import write_warehouse_analog

    ANALOG_DIR.mkdir(parents=True, exist_ok=True)
    out = ANALOG_DIR / f"gpu_metrics_hour_{hour}.h5"
    write_warehouse_analog(out, rows)
    return out


def upload_s3(path: Path, hour: int) -> str:
    try:
        import boto3
    except ImportError as e:
        raise SystemExit(
            f"{GURU} boto3 required to upload {path} → {S3_PREFIX}"
        ) from e
    endpoint = os.environ.get("AWS_ENDPOINT_URL_S3", "http://127.0.0.1:9010")
    key_id = os.environ.get("AWS_ACCESS_KEY_ID", "rustfsadmin")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "rustfsadmin")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name="us-east-1",
    )
    # s3://bucket/prefix
    rest = S3_PREFIX[len("s3://") :]
    bucket, _, prefix = rest.partition("/")
    key = f"{prefix.rstrip('/')}/epoch_hour={hour}/{path.name}"
    client.upload_file(str(path), bucket, key)
    return f"s3://{bucket}/{key}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hour", type=int, help="UTC epoch hour (default: previous hour)")
    p.add_argument("--no-upload", action="store_true")
    args = p.parse_args()
    hour = args.hour
    if hour is None:
        hour = int(datetime.now(timezone.utc).timestamp()) // 3600 - 1
    rows = load_jsonl(hour)
    if not rows:
        raise SystemExit(f"{GURU} no jsonl rows for epoch_hour={hour}")
    path = write_h5(hour, rows)
    print(f"analog {path} rows={len(rows)} hour={hour}")
    if args.no_upload:
        return 0
    uri = upload_s3(path, hour)
    print(f"uploaded {uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
