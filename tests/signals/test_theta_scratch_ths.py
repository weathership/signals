"""gaius.theta.cycle — scratch THS hypergraph (Kudu), not AGE graph SoR."""

from pathlib import Path

from signals.ops.history import load_catalog
from signals.ops.warehouse import SCHEMA_SQL


_ROOT = Path(__file__).resolve().parents[2]
_KUDU = _ROOT / "config" / "platform" / "theta-scratch-kudu.sql"
_FDW = _ROOT / "config" / "platform" / "theta-scratch-fdw.sql"


def test_catalog_product_is_cycle_over_scratch() -> None:
    cats = {p["id"]: p for p in load_catalog()["products"]}
    p = cats["gaius.theta.cycle"]
    assert p["peer"] == "gaius"
    assert p["kind"] == "corpus"
    assert p["leaf"] == "root.internal.inference.light"
    assert p["storage"] == "scratch"
    assert p["table_identifier"] == "signals_dataproducts.theta_scratch_incidence"
    assert "DROP RANGE PARTITION" in p["agent_focus"]
    assert "AGE is Atlas+OL only" in p["agent_focus"]


def test_schema_apply_includes_scratch_kudu() -> None:
    assert any(p.name == "theta-scratch-kudu.sql" for p in SCHEMA_SQL)


def test_kudu_hypergraph_expire_is_drop_range_not_row_delete() -> None:
    text = _KUDU.read_text(encoding="utf-8")
    assert "DROP RANGE PARTITION" in text
    assert "never row DELETE" in text
    assert "DELETE FROM" not in text
    assert "RANGE (epoch_hour)" in text
    assert "signals.expire' = 'drop_range_partition'" in text
    assert "signals.product' = 'gaius.theta.cycle'" in text
    assert "signals.storage' = 'scratch'" in text
    for rel in (
        "theta_scratch_vertex_tier0",
        "theta_scratch_edge_tier0",
        "theta_scratch_incidence_tier0",
    ):
        assert rel in text
    assert "PRIMARY KEY (epoch_hour, ts_ns, edge_id, vertex_id, vertex_role)" in text
    assert " vertex_role " in text
    assert " role " not in text.lower().replace("vertex_role", "")
    assert "atlas_graph" not in text
    assert "CREATE GRAPH" not in text.upper()
    assert "STORED AS ICEBERG" not in text


def test_fdw_twins_kudu_scan_tier0_and_sql_views() -> None:
    text = _FDW.read_text(encoding="utf-8")
    assert "access 'kudu_scan'" in text
    assert "access 'impala_sql'" in text
    assert text.count("theta_scratch_vertex") >= 2
    assert "vertex_role" in text
    assert "impala::signals_dataproducts.theta_scratch_incidence_tier0" in text
