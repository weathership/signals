"""gpu_metrics hour settle — analog (if missing), Iceberg verify, Kudu DROP RANGE.

Closed UTC hours stay on Kudu until Iceberg COUNT >= Kudu COUNT. Then
``ALTER TABLE … DROP RANGE PARTITION VALUE = <hour>``. Live hour is never
dropped. Sidecar soak is not the clock: pg_cron + Airflow/Metaflow are.

Guru: #SL.00000026.SETTLE
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from typing import Any

GURU = "#SL.00000026.SETTLE"
KUDU = "signals_dataproducts.gpu_metrics_tier0"
ICE = "signals_dataproducts.gpu_metrics_tier1"
FDW_SERVER = "impala_kudu_srv"


def epoch_hour(now: float | None = None) -> int:
    return int(now if now is not None else time.time()) // 3600


def _psql(sql: str, *, tuples: bool = True) -> str:
    env = os.environ.copy()
    env.setdefault("PGPASSWORD", "signals")
    cmd = [
        "psql",
        "-h",
        os.environ.get("SIGNALS_PGHOST", "127.0.0.1"),
        "-p",
        os.environ.get("SIGNALS_PGPORT", "5455"),
        "-U",
        os.environ.get("SIGNALS_PGUSER", "signals"),
        "-d",
        os.environ.get("SIGNALS_PGDATABASE", "signals"),
        "-v",
        "ON_ERROR_STOP=1",
    ]
    if tuples:
        cmd.extend(["-At", "-F", "\t"])
    cmd.extend(["-c", sql])
    proc = subprocess.run(
        cmd, check=True, capture_output=True, text=True, env=env, timeout=180
    )
    return proc.stdout


def hour_counts() -> dict[str, dict[int, int]]:
    sql = """
    SELECT src, epoch_hour, n FROM (
      SELECT 'iceberg'::text AS src, epoch_hour, count(*)::bigint AS n
        FROM gpu_metrics_tier1 GROUP BY epoch_hour
      UNION ALL
      SELECT 'kudu', epoch_hour, count(*)
        FROM gpu_metrics_tier0 GROUP BY epoch_hour
    ) t
    """
    ice: dict[int, int] = {}
    kudu: dict[int, int] = {}
    for line in _psql(sql).splitlines():
        src, hour_s, n_s = line.split("\t")
        hour, n = int(hour_s), int(n_s)
        (ice if src == "iceberg" else kudu)[hour] = n
    return {"iceberg": ice, "kudu": kudu}


def analog_hour(hour: int) -> None:
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "gpu_metrics_tier_up.py"
    if not script.is_file():
        raise RuntimeError(f"{GURU} missing {script}")
    subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(script), "--hour", str(int(hour))],
        check=True,
        timeout=600,
    )
    _psql(
        "SELECT impala_fdw_exec("
        f"'{FDW_SERVER}', "
        f"'REFRESH {ICE}')"
    )


def drop_range(hour: int) -> None:
    sql = (
        "SELECT impala_fdw_exec("
        f"'{FDW_SERVER}', "
        f"'ALTER TABLE {KUDU} DROP RANGE PARTITION VALUE = {int(hour)}')"
    )
    _psql(sql)


def walk(
    *,
    apply: bool = False,
    analog: bool = True,
    now_hour: int | None = None,
) -> dict[str, Any]:
    """Plan (and optionally apply) analog → Iceberg verify → Kudu DROP RANGE."""
    now = int(now_hour if now_hour is not None else epoch_hour())
    counts = hour_counts()
    ice, kudu = counts["iceberg"], counts["kudu"]
    closed = sorted(h for h in kudu if h < now)
    planned: list[dict[str, Any]] = []
    dropped: list[int] = []
    analoged: list[int] = []
    for hour in closed:
        kudu_n = int(kudu[hour])
        ice_n = int(ice.get(hour, 0))
        item = {
            "hour": hour,
            "kudu_n": kudu_n,
            "ice_n": ice_n,
            "drop_sql": (
                f"ALTER TABLE {KUDU} DROP RANGE PARTITION VALUE = {hour}"
            ),
        }
        if ice_n == 0:
            item["needs_analog"] = True
            if not apply:
                planned.append(item)
                continue
            if not analog:
                raise RuntimeError(
                    f"{GURU} iceberg missing hour {hour} "
                    "(run analog / Metaflow GpuMetricsSettle first)"
                )
            analog_hour(hour)
            analoged.append(hour)
            ice_n = int(hour_counts()["iceberg"].get(hour, 0))
            item["ice_n"] = ice_n
            if ice_n == 0:
                raise RuntimeError(
                    f"{GURU} analog hour {hour} did not appear in Iceberg"
                )
        if ice_n < kudu_n:
            raise RuntimeError(
                f"{GURU} refuse DROP hour={hour} ice={ice_n} < kudu={kudu_n}"
            )
        planned.append(item)
        if apply:
            drop_range(hour)
            leftover = int(hour_counts()["kudu"].get(hour, 0))
            if leftover:
                raise RuntimeError(
                    f"{GURU} DROP RANGE {hour} left {leftover} Kudu rows"
                )
            dropped.append(hour)
    return {
        "now_hour": now,
        "closed": closed,
        "planned": planned,
        "analoged": analoged,
        "dropped": dropped,
        "apply": apply,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="analog if needed, then DROP")
    p.add_argument("--no-analog", action="store_true")
    args = p.parse_args(argv)
    doc = walk(apply=args.apply, analog=not args.no_analog)
    import json

    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
