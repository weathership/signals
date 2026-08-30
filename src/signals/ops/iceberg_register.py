"""Data-product tier1 tables — created through Polaris, never Impala DDL.

Impala ``CREATE TABLE … STORED AS ICEBERG`` on this HMS-free fork writes
metadata the MultiMetaProvider cannot load back (2026-08-30 phantom-table
incident: ``tx_tier1``/``details_tier1`` appeared in SHOW TABLES, failed
DESCRIBE, and vanished on INVALIDATE METADATA). The tier1 tables that work
(``signal_tier1``, ``gpu_dcgm_tier1``, ``hx.cot_reasoning``) were registered
through the Polaris REST catalog, which Impala discovers with zero
registration — so these four are created the same way, via PyIceberg.

Table locations derive from the Polaris catalog ``default-base-location``
(``s3://signals-dataproducts/iceberg``) — no explicit ``write.location``,
matching the working-table convention
``s3://signals-dataproducts/iceberg/signals_dataproducts/<table>``.

Guru: #SL.00000027.SCHEMA2 (no HS2 Iceberg DDL on this stack).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog
    from pyiceberg.partitioning import PartitionSpec
    from pyiceberg.schema import Schema
    from pyiceberg.table import Table

logger = logging.getLogger("signals.ops.iceberg_register")

NAMESPACE = "signals_dataproducts"
TIER1_TABLES = ("tx_tier1", "details_tier1", "hx_exchange_tier1", "hx_reasoning_tier1")

_TABLE_PROPERTIES = {
    "signals.tier": "1",
    "write.parquet.compression-codec": "zstd",
    "write.parquet.compression-level": "3",
    "write.metadata.delete-after-commit.enabled": "true",
    "write.metadata.previous-versions-max": "10",
}


def polaris_catalog_properties() -> dict[str, str]:
    """REST-catalog properties for the Signals Polaris (:8181) over RustFS."""
    uri = os.environ.get("SIGNALS_POLARIS_URI", "http://127.0.0.1:8181/api/catalog")
    warehouse = os.environ.get("POLARIS_CATALOG_NAME", "signals")
    credential = os.environ.get("SIGNALS_POLARIS_CREDENTIAL", "admin:admin")
    return {
        "type": "rest",
        "uri": uri.rstrip("/"),
        "warehouse": warehouse,
        "credential": credential,
        "scope": "PRINCIPAL_ROLE:ALL",
        # Polarisfork has no STS — client FileIO uses RustFS keys directly.
        "header.X-Iceberg-Access-Delegation": "",
        "s3.endpoint": os.environ.get("SIGNALS_RUSTFS_ENDPOINT", "http://127.0.0.1:9010"),
        "s3.access-key-id": os.environ.get("RUSTFS_ACCESS_KEY", "rustfsadmin"),
        "s3.secret-access-key": os.environ.get("RUSTFS_SECRET_KEY", "rustfsadmin"),
        "s3.path-style-access": "true",
        "s3.region": "us-east-1",
    }


def load_polaris_catalog() -> "Catalog":
    from pyiceberg.catalog import load_catalog

    props = polaris_catalog_properties()
    catalog = load_catalog(props["warehouse"], **props)
    if (NAMESPACE,) not in set(catalog.list_namespaces()):
        catalog.create_namespace((NAMESPACE,))
    return catalog


def _schema(fields: list[tuple[str, str, bool, str]]) -> "Schema":
    """Build a Schema from (name, type, required, doc); ids assigned in order."""
    from pyiceberg.schema import Schema
    from pyiceberg.types import BooleanType, IntegerType, LongType, StringType

    types: dict[str, Any] = {
        "int": IntegerType(),
        "long": LongType(),
        "string": StringType(),
        "boolean": BooleanType(),
    }
    return Schema(
        *(
            _nested_field(i + 1, name, types[t], required, doc)
            for i, (name, t, required, doc) in enumerate(fields)
        )
    )


def _nested_field(fid: int, name: str, ftype: Any, required: bool, doc: str):
    from pyiceberg.types import NestedField

    return NestedField(fid, name, ftype, required=required, doc=doc)


def _identity_spec(schema: "Schema", column: str) -> "PartitionSpec":
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import IdentityTransform

    source = schema.find_field(column)
    return PartitionSpec(
        PartitionField(
            source_id=source.field_id,
            field_id=1000,
            transform=IdentityTransform(),
            name=column,
        )
    )


def tier1_schema(table: str) -> "Schema":
    """Columns byte-match the *_tier0 twins (minus Kudu PRIMARY KEY)."""
    if table == "tx_tier1":
        return _schema(
            [
                ("epoch_hour", "int", True, "UTC hours since epoch; settle grain"),
                ("product_id", "string", True, "{peer}.{domain}.{name}"),
                ("tx_id", "string", True, "UUIDv7 — identity + datalog order"),
                ("ts_ns", "long", True, "event time, ns"),
                ("kind", "string", False, "created|updated|…"),
                ("summary", "string", False, ""),
                ("source", "string", False, ""),
                ("ce_type", "string", False, "CloudEvents type"),
            ]
        )
    if table == "details_tier1":
        return _schema(
            [
                ("epoch_hour", "int", True, "UTC hours since epoch; settle grain"),
                ("e", "string", True, "entity = product_id"),
                ("a", "string", True, "attribute"),
                ("t", "string", True, "tx_id (UUIDv7)"),
                ("v", "string", False, "value"),
                ("op", "boolean", False, "assert=true / retract=false"),
                ("ts_ns", "long", True, "event time, ns"),
            ]
        )
    if table == "hx_exchange_tier1":
        return _schema(
            [
                ("epoch_hour", "int", True, "UTC hours since epoch; settle grain"),
                ("product_id", "string", True, "{peer}.{domain}.{name}"),
                ("tx_id", "string", True, "UUIDv7"),
                ("ts_ns", "long", True, "event time, ns"),
                ("agent", "string", False, "reviewing agent"),
                ("actor", "string", False, "exchange voice, e.g. observer"),
                ("message", "string", False, ""),
            ]
        )
    if table == "hx_reasoning_tier1":
        return _schema(
            [
                ("epoch_hour", "int", True, "UTC hours since epoch; settle grain"),
                ("product_id", "string", True, "{peer}.{domain}.{name}"),
                ("tx_id", "string", True, "UUIDv7"),
                ("agent", "string", True, "reasoning agent"),
                ("ts_ns", "long", True, "event time, ns"),
                ("quality", "string", False, ""),
                ("lineage", "string", False, ""),
                ("delta", "string", False, ""),
                ("trace", "string", False, "reasoning trace / brief"),
            ]
        )
    raise ValueError(f"unknown tier1 table {table!r}")


def tier1_partition_column(table: str) -> str:
    """Iceberg partitions by identity — never epoch_hour (hour hotspots)."""
    return "e" if table == "details_tier1" else "product_id"


def create_tier1_table(catalog: "Catalog", table: str) -> "Table":
    """Idempotent create of one tier1 table in the Polaris catalog."""
    from pyiceberg.exceptions import NoSuchTableError, TableAlreadyExistsError

    table_id = f"{NAMESPACE}.{table}"
    try:
        return catalog.load_table(table_id)
    except NoSuchTableError:
        pass
    schema = tier1_schema(table)
    logger.info("Creating Polaris Iceberg table %s", table_id)
    try:
        return catalog.create_table(
            identifier=table_id,
            schema=schema,
            partition_spec=_identity_spec(schema, tier1_partition_column(table)),
            properties=dict(_TABLE_PROPERTIES),
        )
    except TableAlreadyExistsError:
        return catalog.load_table(table_id)


def register_tier1_tables(catalog: "Catalog | None" = None) -> list[str]:
    """Create all data-product tier1 tables; returns the identifiers touched."""
    cat = catalog or load_polaris_catalog()
    out: list[str] = []
    for table in TIER1_TABLES:
        create_tier1_table(cat, table)
        out.append(f"{NAMESPACE}.{table}")
    return out
