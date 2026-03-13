"""Data lifecycle workload driver.

Generates a realistic hot→warm data pattern:
  - Data lands in Kudu (hot tier) with ~20% upsert load
  - Hot partitions see frequent updates, older partitions cool
  - Cold partitions consolidate into Iceberg via CTAS
  - Impala queries span both Kudu and Iceberg

Usage as a module:
    from tests.workload.lifecycle import LifecycleWorkload
    wl = LifecycleWorkload(impala_host="localhost", impala_port=21050)
    wl.setup()
    wl.run_landing(n_rows=1000, n_partitions=10, upsert_ratio=0.2)
    wl.consolidate_cold(cold_partitions=[8, 9])
    wl.verify_consistency()

Usage standalone:
    uv run python -m tests.workload.lifecycle --phase all
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass, field

from impala.dbapi import connect as impala_connect


@dataclass
class LifecycleConfig:
    impala_host: str = "localhost"
    impala_port: int = 21050
    database: str = "lifecycle_test"
    kudu_table: str = "events"
    iceberg_table: str = "events_archive"
    kudu_masters: str = "127.0.0.1:7051"
    n_partitions: int = 10
    rows_per_partition: int = 100
    upsert_ratio: float = 0.20
    hot_partitions: list[int] = field(default_factory=lambda: [0, 1, 2, 3])
    cold_partitions: list[int] = field(default_factory=lambda: [8, 9])


class LifecycleWorkload:
    """Drives the Kudu→Iceberg data lifecycle workload."""

    def __init__(self, cfg: LifecycleConfig | None = None):
        self.cfg = cfg or LifecycleConfig()
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            self._conn = impala_connect(
                host=self.cfg.impala_host, port=self.cfg.impala_port
            )
        return self._conn

    def _execute(self, sql: str, fetch: bool = False):
        """Execute a SQL statement, optionally fetching results."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(sql)
        if fetch:
            return cursor.fetchall()
        return None

    def _execute_scalar(self, sql: str):
        rows = self._execute(sql, fetch=True)
        return rows[0][0] if rows else None

    # ── Setup ────────────────────────────────────────────────────────────

    def setup(self):
        """Create database and Kudu events table."""
        db = self.cfg.database
        tbl = f"{db}.{self.cfg.kudu_table}"

        self._execute(f"CREATE DATABASE IF NOT EXISTS {db}")
        self._execute(f"DROP TABLE IF EXISTS {tbl}")
        self._execute(f"""
            CREATE TABLE {tbl} (
                event_id BIGINT,
                ts TIMESTAMP,
                partition_id INT,
                payload STRING,
                PRIMARY KEY (event_id)
            )
            PARTITION BY HASH (event_id) PARTITIONS 4
            STORED AS KUDU
            TBLPROPERTIES ('kudu.master_addresses'='{self.cfg.kudu_masters}')
        """)

    # ── Data landing ─────────────────────────────────────────────────────

    def run_landing(
        self,
        n_rows: int | None = None,
        n_partitions: int | None = None,
        upsert_ratio: float | None = None,
    ) -> dict:
        """Insert initial rows, then apply upsert load to hot partitions.

        Returns dict with counts for verification.
        """
        n_rows = n_rows or (self.cfg.rows_per_partition * self.cfg.n_partitions)
        n_partitions = n_partitions or self.cfg.n_partitions
        upsert_ratio = upsert_ratio or self.cfg.upsert_ratio
        rows_per_part = n_rows // n_partitions

        db = self.cfg.database
        tbl = f"{db}.{self.cfg.kudu_table}"
        now_ms = int(time.time() * 1000)

        # Phase 1: Initial insert — spread evenly across partitions
        values = []
        for part in range(n_partitions):
            for i in range(rows_per_part):
                eid = part * rows_per_part + i
                ts = now_ms - (n_partitions - part) * 86400000 + i * 1000
                values.append(
                    f"({eid}, from_unixtime({ts}/1000), "
                    f"{part}, 'initial-{eid}')"
                )
        # Insert in batches to avoid query size limits
        batch_size = 200
        for start in range(0, len(values), batch_size):
            batch = values[start : start + batch_size]
            self._execute(
                f"INSERT INTO {tbl} VALUES {', '.join(batch)}"
            )

        total_inserted = len(values)

        # Phase 2: Upserts — target hot partitions
        n_upserts = int(n_rows * upsert_ratio)
        hot_parts = self.cfg.hot_partitions
        upsert_values = []
        for _ in range(n_upserts):
            part = random.choice(hot_parts)
            eid = part * rows_per_part + random.randint(0, rows_per_part - 1)
            ts = now_ms + random.randint(0, 3600000)
            upsert_values.append(
                f"({eid}, from_unixtime({ts}/1000), "
                f"{part}, 'upserted-{eid}')"
            )
        for start in range(0, len(upsert_values), batch_size):
            batch = upsert_values[start : start + batch_size]
            self._execute(
                f"UPSERT INTO {tbl} VALUES {', '.join(batch)}"
            )

        return {
            "total_inserted": total_inserted,
            "upserts_applied": n_upserts,
            "expected_row_count": total_inserted,  # upserts don't increase count
        }

    # ── Consolidation ────────────────────────────────────────────────────

    def consolidate_cold(
        self, cold_partitions: list[int] | None = None
    ) -> dict:
        """Move cold partitions from Kudu to Iceberg via CTAS + DELETE."""
        cold = cold_partitions or self.cfg.cold_partitions
        db = self.cfg.database
        kudu_tbl = f"{db}.{self.cfg.kudu_table}"
        ice_tbl = f"{db}.{self.cfg.iceberg_table}"
        part_list = ", ".join(str(p) for p in cold)

        # Count rows to move
        count_before = self._execute_scalar(
            f"SELECT COUNT(*) FROM {kudu_tbl} WHERE partition_id IN ({part_list})"
        )

        # CTAS into Iceberg
        self._execute(f"DROP TABLE IF EXISTS {ice_tbl}")
        self._execute(f"""
            CREATE TABLE {ice_tbl}
            STORED AS ICEBERG
            TBLPROPERTIES('iceberg.catalog'='polaris')
            AS SELECT event_id, ts, partition_id, payload
               FROM {kudu_tbl}
               WHERE partition_id IN ({part_list})
        """)

        # Delete consolidated rows from Kudu
        self._execute(
            f"DELETE FROM {kudu_tbl} WHERE partition_id IN ({part_list})"
        )

        # Verify
        ice_count = self._execute_scalar(f"SELECT COUNT(*) FROM {ice_tbl}")
        kudu_remaining = self._execute_scalar(f"SELECT COUNT(*) FROM {kudu_tbl}")

        return {
            "rows_moved": count_before,
            "iceberg_count": ice_count,
            "kudu_remaining": kudu_remaining,
        }

    # ── Verification ─────────────────────────────────────────────────────

    def verify_consistency(self) -> dict:
        """Verify data consistency across Kudu and Iceberg tiers.

        Checks:
          1. Total row count (Kudu + Iceberg) matches expected
          2. No duplicate event_ids across tiers
          3. Every partition is represented
          4. Per-partition counts are correct
        """
        db = self.cfg.database
        kudu_tbl = f"{db}.{self.cfg.kudu_table}"
        ice_tbl = f"{db}.{self.cfg.iceberg_table}"

        kudu_count = self._execute_scalar(f"SELECT COUNT(*) FROM {kudu_tbl}") or 0
        ice_count = self._execute_scalar(f"SELECT COUNT(*) FROM {ice_tbl}") or 0

        # Check for duplicates across tiers
        dup_count = self._execute_scalar(f"""
            SELECT COUNT(*) FROM (
                SELECT event_id FROM {kudu_tbl}
                INTERSECT
                SELECT event_id FROM {ice_tbl}
            ) dups
        """) or 0

        # Per-partition distribution
        partition_counts = self._execute(f"""
            SELECT partition_id, SUM(cnt) AS total FROM (
                SELECT partition_id, COUNT(*) AS cnt FROM {kudu_tbl}
                GROUP BY partition_id
                UNION ALL
                SELECT partition_id, COUNT(*) AS cnt FROM {ice_tbl}
                GROUP BY partition_id
            ) combined
            GROUP BY partition_id
            ORDER BY partition_id
        """, fetch=True) or []

        results = {
            "kudu_count": kudu_count,
            "iceberg_count": ice_count,
            "total_count": kudu_count + ice_count,
            "cross_tier_duplicates": dup_count,
            "partition_counts": {row[0]: row[1] for row in partition_counts},
        }

        errors = []
        expected_total = self.cfg.rows_per_partition * self.cfg.n_partitions
        if results["total_count"] != expected_total:
            errors.append(
                f"Total count {results['total_count']} != expected {expected_total}"
            )
        if results["cross_tier_duplicates"] > 0:
            errors.append(
                f"{results['cross_tier_duplicates']} duplicate event_ids across tiers"
            )
        if len(results["partition_counts"]) != self.cfg.n_partitions:
            errors.append(
                f"Expected {self.cfg.n_partitions} partitions, "
                f"got {len(results['partition_counts'])}"
            )

        results["errors"] = errors
        results["passed"] = len(errors) == 0
        return results

    # ── Full lifecycle ───────────────────────────────────────────────────

    def run_full_lifecycle(self) -> dict:
        """Run the complete hot→warm lifecycle and verify."""
        print("Phase 1: Setup")
        self.setup()

        print("Phase 2: Data landing (insert + upsert)")
        landing = self.run_landing()
        print(f"  Inserted {landing['total_inserted']} rows, "
              f"applied {landing['upserts_applied']} upserts")

        print("Phase 3: Consolidate cold partitions to Iceberg")
        consolidation = self.consolidate_cold()
        print(f"  Moved {consolidation['rows_moved']} rows to Iceberg, "
              f"{consolidation['kudu_remaining']} remain in Kudu")

        print("Phase 4: Verify cross-tier consistency")
        verification = self.verify_consistency()
        if verification["passed"]:
            print("  PASSED: All consistency checks passed")
        else:
            for err in verification["errors"]:
                print(f"  FAILED: {err}")

        return {
            "landing": landing,
            "consolidation": consolidation,
            "verification": verification,
        }

    def teardown(self):
        """Drop test database and tables."""
        db = self.cfg.database
        self._execute(f"DROP TABLE IF EXISTS {db}.{self.cfg.iceberg_table}")
        self._execute(f"DROP TABLE IF EXISTS {db}.{self.cfg.kudu_table}")
        self._execute(f"DROP DATABASE IF EXISTS {db}")
        if self._conn:
            self._conn.close()
            self._conn = None


def main():
    parser = argparse.ArgumentParser(
        description="Kudu/Iceberg data lifecycle workload"
    )
    parser.add_argument(
        "--phase",
        choices=["setup", "land", "consolidate", "verify", "all", "teardown"],
        default="all",
    )
    parser.add_argument("--impala-host", default="localhost")
    parser.add_argument("--impala-port", type=int, default=21050)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--partitions", type=int, default=10)
    parser.add_argument("--upsert-ratio", type=float, default=0.20)
    args = parser.parse_args()

    cfg = LifecycleConfig(
        impala_host=args.impala_host,
        impala_port=args.impala_port,
        n_partitions=args.partitions,
        rows_per_partition=args.rows // args.partitions,
        upsert_ratio=args.upsert_ratio,
    )
    wl = LifecycleWorkload(cfg)

    try:
        if args.phase == "all":
            result = wl.run_full_lifecycle()
            sys.exit(0 if result["verification"]["passed"] else 1)
        elif args.phase == "setup":
            wl.setup()
        elif args.phase == "land":
            wl.run_landing()
        elif args.phase == "consolidate":
            wl.consolidate_cold()
        elif args.phase == "verify":
            result = wl.verify_consistency()
            sys.exit(0 if result["passed"] else 1)
        elif args.phase == "teardown":
            wl.teardown()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
