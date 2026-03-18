"""Value sampling from Impala tables."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from sigint.config import TaggingConfig

# Disable thrift C accelerator before importing impyla.
sys.modules.setdefault("thrift.protocol.fastbinary", None)
sys.modules.setdefault("thrift.protocol.fastproto", None)

from impala.dbapi import connect as impala_connect  # noqa: E402


@dataclass
class ColumnSample:
    """Sampled values for a single column."""

    column_name: str
    column_type: str
    values: list[str] = field(default_factory=list)
    null_count: int = 0
    total_count: int = 0


@dataclass
class TableSample:
    """All column samples for a single table."""

    database: str
    table_name: str
    columns: list[ColumnSample] = field(default_factory=list)

    @property
    def fqn(self) -> str:
        return f"{self.database}.{self.table_name}"


class ImpalaSampler:
    """Sample column values from Impala tables via SQL."""

    def __init__(self, cfg: TaggingConfig) -> None:
        self._cfg = cfg
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            self._conn = impala_connect(
                host=self._cfg.impala_host,
                port=self._cfg.impala_port,
                auth_mechanism="NOSASL",
            )
        return self._conn

    def _execute(self, sql: str, fetch: bool = False):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(sql)
        if fetch:
            return cursor.fetchall()
        return None

    def describe_table(self, table_fqn: str) -> list[tuple[str, str]]:
        """Return (column_name, column_type) pairs from DESCRIBE."""
        rows = self._execute(f"DESCRIBE {table_fqn}", fetch=True)
        return [(row[0], row[1]) for row in rows] if rows else []

    def sample_column(
        self, table_fqn: str, column_name: str, column_type: str
    ) -> ColumnSample:
        """Sample distinct non-null values for a single column."""
        n = self._cfg.sample_size
        strategy = self._cfg.sample_strategy

        if strategy == "random":
            sql = (
                f"SELECT CAST({column_name} AS STRING) "
                f"FROM {table_fqn} "
                f"WHERE {column_name} IS NOT NULL "
                f"ORDER BY rand() LIMIT {n}"
            )
        elif strategy == "frequent":
            sql = (
                f"SELECT CAST({column_name} AS STRING), COUNT(*) AS c "
                f"FROM {table_fqn} "
                f"WHERE {column_name} IS NOT NULL "
                f"GROUP BY {column_name} ORDER BY c DESC LIMIT {n}"
            )
        else:  # head (default)
            sql = (
                f"SELECT DISTINCT CAST({column_name} AS STRING) "
                f"FROM {table_fqn} "
                f"WHERE {column_name} IS NOT NULL "
                f"LIMIT {n}"
            )

        rows = self._execute(sql, fetch=True) or []
        values = [str(row[0]) for row in rows if row[0] is not None]

        return ColumnSample(
            column_name=column_name,
            column_type=column_type,
            values=values,
        )

    def sample_table(self, table_fqn: str) -> TableSample:
        """Describe and sample all columns of a table."""
        parts = table_fqn.split(".", 1)
        db = parts[0] if len(parts) == 2 else "default"
        table = parts[1] if len(parts) == 2 else parts[0]

        columns_meta = self.describe_table(table_fqn)
        samples = []
        for col_name, col_type in columns_meta:
            sample = self.sample_column(table_fqn, col_name, col_type)
            samples.append(sample)

        return TableSample(database=db, table_name=table, columns=samples)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
