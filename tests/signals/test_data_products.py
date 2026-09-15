"""Federation data-product catalog, Iceberg SoR, and history-review method."""

from pathlib import Path

import pytest

from signals.ops.history import agent_brief, load_catalog, product_by_id, review, seed_details
from signals.ops.procedures import DATA_PRODUCT_HISTORY_REVIEW, get_method
from signals.ops.warehouse import (
    MemoryWarehouse,
    WarehouseError,
    default_warehouse,
    refuse_postgres,
)


def test_catalog_has_federation_peers() -> None:
    doc = load_catalog()
    assert "RustFS" in doc.get("description", "") or "Iceberg" in doc.get("description", "")
    cats = {p["id"]: p for p in doc["products"]}
    assert doc["products"][0]["id"] == "signals.metaflow.snapshots"
    assert cats["signals.metaflow.snapshots"]["peer"] == "signals"
    assert cats["signals.metaflow.snapshots"]["kind"] == "snapshot"
    assert cats["signals.metaflow.snapshots"]["leaf"] == "root.platform"
    assert "nominally" in cats["signals.metaflow.snapshots"]["agent_focus"]
    assert "nominal" in doc["agent"]["review"]
    assert "gaius.cognition.outputs" in cats
    assert cats["gaius.cognition.outputs"]["peer"] == "gaius"
    assert "gaius.prospects.corpus" in cats
    assert cats["gaius.prospects.corpus"]["peer"] == "gaius"
    assert cats["gaius.prospects.corpus"]["kind"] == "corpus"
    assert cats["gaius.prospects.corpus"]["leaf"] == "root.internal.inference.extract"
    assert "gaius.curation.cot_reasoning" in cats
    assert cats["gaius.curation.cot_reasoning"]["kind"] == "reasoning"
    assert cats["gaius.curation.cot_reasoning"]["leaf"] == "root.internal.inference.extract"
    assert cats["gaius.curation.cot_reasoning"]["table_identifier"] == "hx.cot_reasoning"
    assert "aegir.usd-corpora" in cats
    assert "aegir.models.bespoke" in cats
    assert "atelier.classification.embeddings" in cats


def test_iceberg_schema_is_sole_sor_not_pglite() -> None:
    root = Path(__file__).resolve().parents[2] / "config" / "platform"
    kudu = (root / "data-products-kudu.sql").read_text(encoding="utf-8")
    views = (root / "data-products-views.sql").read_text(encoding="utf-8")
    # Impala Iceberg DDL is retired — tier1 is created through Polaris
    # (signals.ops.iceberg_register); the MultiMetaProvider cannot load back
    # Impala-created Iceberg metadata on this fork.
    assert not (root / "data-products-iceberg.sql").exists()
    assert "details_tier0" in kudu and "STORED AS KUDU" in kudu
    assert "DROP RANGE PARTITION" in kudu
    assert "Never DELETE FROM" in kudu
    assert "RANGE (epoch_hour)" in kudu
    assert "HASH (e)" in kudu
    assert "168" in kudu
    assert "settle_weeks" in kudu
    assert "pglite" in kudu.lower()
    assert "UNION ALL" in views
    assert "signals_dataproducts.details AS" in views
    # role is an Impala reserved word; the exchange voice column is actor.
    assert "actor" in kudu and "actor" in views
    assert " role " not in kudu.lower() and " role " not in views.lower()
    # Every view masks tier1 weeks that still live in tier0 (no double-count).
    assert views.count("NOT IN") == 4


def test_tier1_registrar_matches_tier0_shape() -> None:
    from signals.ops.iceberg_register import (
        NAMESPACE,
        TIER1_TABLES,
        tier1_partition_column,
        tier1_schema,
    )

    assert NAMESPACE == "signals_dataproducts"
    assert TIER1_TABLES == (
        "tx_tier1",
        "details_tier1",
        "hx_exchange_tier1",
        "hx_reasoning_tier1",
    )
    assert tier1_partition_column("details_tier1") == "e"
    assert tier1_partition_column("tx_tier1") == "product_id"
    names = {t: [f.name for f in tier1_schema(t).fields] for t in TIER1_TABLES}
    assert names["tx_tier1"] == [
        "epoch_hour", "product_id", "tx_id", "ts_ns",
        "kind", "summary", "source", "ce_type",
    ]
    assert names["details_tier1"] == ["epoch_hour", "e", "a", "t", "v", "op", "ts_ns"]
    assert names["hx_exchange_tier1"] == [
        "epoch_hour", "product_id", "tx_id", "ts_ns", "agent", "actor", "message",
    ]
    assert names["hx_reasoning_tier1"] == [
        "epoch_hour", "product_id", "tx_id", "agent", "ts_ns",
        "quality", "lineage", "delta", "trace",
    ]


def test_no_tmp_warehouse_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    for rel in (
        "config/impala/core-site.xml",
        "config/impala/hive-site.xml",
        "config/impala/catalog_schema.sql",
        "config/hms/metastore-site.xml",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        assert "file:///tmp/signals-warehouse" not in text
        assert "s3a://signals-dataproducts" in text


def test_epoch_hour_and_four_week_settle() -> None:
    from signals.ops.warehouse import (
        HOURS_PER_WEEK,
        NS_PER_HOUR,
        SETTLE_WEEKS,
        epoch_hour,
        settle_before_hour,
        week_start_hour,
    )

    assert epoch_hour(0) == 0
    assert epoch_hour(NS_PER_HOUR - 1) == 0
    assert epoch_hour(NS_PER_HOUR) == 1
    assert week_start_hour(496320) == (496320 // 168) * 168
    assert SETTLE_WEEKS == 4
    now = 2954 * HOURS_PER_WEEK + 10
    assert settle_before_hour(now) == (2950 * HOURS_PER_WEEK)


def test_refuse_postgres_dsn() -> None:
    with pytest.raises(WarehouseError):
        refuse_postgres("postgresql://signals@127.0.0.1:5455/polaris")
    with pytest.raises(WarehouseError):
        refuse_postgres("jdbc:postgresql://localhost:5455/signals")
    refuse_postgres("impala://tinybox.dev.vista.zndx.org:21050")


def test_warehouse_env_cannot_be_pglite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALS_WAREHOUSE", "pglite")
    with pytest.raises(WarehouseError):
        default_warehouse()
    monkeypatch.setenv("SIGNALS_WAREHOUSE", "memory")
    assert isinstance(default_warehouse(), MemoryWarehouse)


def test_history_and_warehouse_never_import_postgres() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "signals" / "ops"
    for name in ("history.py", "warehouse.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "psycopg" not in text
        assert "import postgres" not in text
        assert "asyncpg" not in text


def test_seed_and_review_write_warehouse_not_jsonl(tmp_path: Path) -> None:
    import signals.ops.history as hist

    wh = MemoryWarehouse()
    hist.BRIEF_DIR = tmp_path / "briefs"
    written = seed_details(warehouse=wh)
    assert "signals.metaflow.snapshots" in written
    assert "gaius.cognition.outputs" in written
    assert wh.get_product("gaius.cognition.outputs") is not None
    ev, path = review(
        "gaius.cognition.outputs",
        kind="updated",
        summary="article-curate run 18",
        warehouse=wh,
    )
    assert ev["product_id"] == "gaius.cognition.outputs"
    assert ev["tx_id"] and ev["event_id"] == ev["tx_id"]
    from signals.uuidv7 import is_uuidv7

    assert is_uuidv7(ev["tx_id"])
    assert wh.tx
    assert any(f["e"] == "gaius.cognition.outputs" and f["a"] == "peer" for f in wh.details)
    assert wh.hx_reasoning and wh.hx_reasoning[0]["tx_id"] == ev["tx_id"]
    assert not list(tmp_path.glob("*.jsonl"))
    text = path.read_text(encoding="utf-8")
    assert "Quality" in text and "Lineage" in text and "Delta" in text
    prod = product_by_id("gaius.cognition.outputs")
    assert prod is not None
    assert "quality" in agent_brief(prod, ev).lower()
    assert "postgres" in agent_brief(prod, ev).lower() or "age" in agent_brief(prod, ev).lower()


def test_history_review_method_holds_until_understood() -> None:
    fsm = get_method(DATA_PRODUCT_HISTORY_REVIEW)
    fsm.step("event_received")
    assert fsm.is_holding()
    fsm.step("reviewing")
    assert fsm.is_holding()
    fsm.step("understood")
    assert fsm.is_terminal()


def test_latest_retract_tombstones_attr() -> None:
    from signals.ops.warehouse import project_details

    facts = [
        {"e": "p", "a": "kind", "v": "cognition", "t": "t1", "op": True},
        {"e": "p", "a": "kind", "v": "", "t": "t2", "op": False},
        {"e": "p", "a": "peer", "v": "gaius", "t": "t1", "op": True},
    ]
    row = project_details(facts, "p")
    assert row is not None
    assert "kind" not in row
    assert row["peer"] == "gaius"


def test_uuidv7_mint_is_ordered_and_version_7() -> None:
    from signals.uuidv7 import is_uuidv7, mint, unix_ms_of

    a, b = mint(), mint()
    assert is_uuidv7(a) and is_uuidv7(b)
    assert a < b or unix_ms_of(a) <= unix_ms_of(b)


def test_non_v7_tx_id_is_refused_and_remediable() -> None:
    import uuid

    from signals.ops.tx_remediate import remediation_request, to_proto
    from signals.ops.warehouse import MemoryWarehouse
    from signals.uuidv7 import NonUuid7TxId

    wh = MemoryWarehouse()
    bad = str(uuid.uuid4())
    with pytest.raises(NonUuid7TxId) as ei:
        wh.insert_tx({"tx_id": bad, "product_id": "gaius.cognition.outputs", "source": "gaius"})
    err = ei.value
    sig = err.boundary_signal()
    assert sig["kind"] == "TX_ID_NOT_UUIDV7"
    assert sig["kind_number"] == 5
    assert sig["offending"] == bad
    req = remediation_request(err)
    assert req["capability"] == "reauthor"
    proto = to_proto(err)
    from signals.engine.generated.zndx.engine.v1 import engine_pb2

    assert proto.signal.kind == engine_pb2.TX_ID_NOT_UUIDV7
    assert proto.signal.offending == bad


def test_unknown_product() -> None:
    with pytest.raises(KeyError):
        review("not.a.product", warehouse=MemoryWarehouse())


def _rustfs_env() -> dict[str, str]:
    return {
        "METAFLOW_DEFAULT_DATASTORE": "s3",
        "METAFLOW_DATASTORE_SYSROOT_S3": "s3://metaflow/metaflow",
        "METAFLOW_S3_ENDPOINT_URL": "http://127.0.0.1:9010",
    }


def test_platform_profile_is_rustfs() -> None:
    from signals.ops.metaflow_store import require_rustfs

    store = require_rustfs(env={}, profile=None)
    assert store["datastore"] == "s3"
    assert store["datastore_root"].startswith("s3://metaflow/")
    assert "9010" in store["rustfs_endpoint"]
    assert store["object_store"] == "rustfs"


def test_require_rustfs_refuses_local_or_wrong_endpoint() -> None:
    from signals.ops.metaflow_store import require_rustfs

    with pytest.raises(WarehouseError, match="local"):
        require_rustfs(env={"METAFLOW_DEFAULT_DATASTORE": "local"}, profile={})
    with pytest.raises(WarehouseError, match="unset"):
        require_rustfs(env={}, profile={})
    with pytest.raises(WarehouseError, match="not s3"):
        require_rustfs(env={"METAFLOW_DEFAULT_DATASTORE": "azure"}, profile={})
    with pytest.raises(WarehouseError, match="RustFS bucket"):
        require_rustfs(
            env={
                "METAFLOW_DEFAULT_DATASTORE": "s3",
                "METAFLOW_DATASTORE_SYSROOT_S3": "s3://someone-else/metaflow",
                "METAFLOW_S3_ENDPOINT_URL": "http://127.0.0.1:9010",
            },
            profile={},
        )
    with pytest.raises(WarehouseError, match="not RustFS"):
        require_rustfs(
            env={
                "METAFLOW_DEFAULT_DATASTORE": "s3",
                "METAFLOW_DATASTORE_SYSROOT_S3": "s3://metaflow/metaflow",
                "METAFLOW_S3_ENDPOINT_URL": "https://s3.amazonaws.com",
            },
            profile={},
        )


def test_facts_from_run_maps_code_data_deps_onto_details() -> None:
    from signals.ops.metaflow_store import PRODUCT_ID, facts_from_run, retained_snapshots

    facts = facts_from_run(
        {
            "flow_name": "DataProductTierUpkeep",
            "run_id": "42",
            "code_package": "s3://metaflow/metaflow/DataProductTierUpkeep/data/abc.tgz",
            "code_package_sha": "abc",
            "deps": "conda:python=3.12",
            "yk_app_id": "signals-dataproduct-tier-upkeep",
            "yk_queue": "root.platform",
        },
        env=_rustfs_env(),
        profile={},
    )
    assert facts["id"] == PRODUCT_ID
    assert facts["snapshot_uri"] == "s3://metaflow/metaflow/DataProductTierUpkeep/42"
    assert facts["data_uri"] == "s3://metaflow/metaflow/DataProductTierUpkeep/data"
    assert facts["code_package_sha"] == "abc"
    assert facts["run.DataProductTierUpkeep/42.snapshot_uri"] == facts["snapshot_uri"]
    assert facts["run.DataProductTierUpkeep/42.code_package_sha"] == "abc"
    snaps = retained_snapshots(facts)
    assert len(snaps) == 1
    assert snaps[0]["pathspec"] == "DataProductTierUpkeep/42"


def test_facts_from_run_refuses_empty_run() -> None:
    from signals.ops.metaflow_store import facts_from_run

    with pytest.raises(WarehouseError, match="flow_name"):
        facts_from_run({"flow_name": "", "run_id": ""}, env=_rustfs_env(), profile={})


def test_record_snapshot_writes_tx_facts_and_snapshot_brief(tmp_path: Path) -> None:
    import signals.ops.history as hist
    from signals.ops.metaflow_store import PRODUCT_ID, record_snapshot, retained_snapshots
    from signals.ops.tier_upkeep import walk

    hist.BRIEF_DIR = tmp_path / "briefs"
    wh = MemoryWarehouse()
    ev, path = record_snapshot(
        {
            "flow_name": "DataProductTierUpkeep",
            "run_id": "7",
            "code_package": "s3://metaflow/metaflow/DataProductTierUpkeep/data/deadbeef",
            "code_package_sha": "deadbeef",
            "deps": "pypi:metaflow==2.18",
            "yk_app_id": "signals-dataproduct-tier-upkeep",
            "yk_queue": "root.platform",
            "upkeep": walk(apply_sql=False),
        },
        warehouse=wh,
        env=_rustfs_env(),
        profile={},
    )
    assert ev["product_id"] == PRODUCT_ID
    assert ev["kind"] == "snapshot"
    assert ev["source"] == "metaflow"
    assert ev["assessment"] == "nominal"
    assert ev["review"]["current"] == "understood"
    assert ev["agent"] == "acp-observer"
    prod = wh.get_product(PRODUCT_ID)
    assert prod is not None
    assert prod["latest_run_id"] == "7"
    assert prod["object_store"] == "rustfs"
    assert prod["assessment"] == "nominal"
    assert prod["upkeep_nominal"] == "true"
    assert prod["quality"]
    assert prod["lineage"]
    assert prod["delta"]
    assert any(
        f["e"] == PRODUCT_ID and f["a"] == "run.DataProductTierUpkeep/7.snapshot_uri"
        for f in wh.details
    )
    assert wh.hx_reasoning[0]["quality"]
    assert wh.hx_reasoning[0]["agent"] == "acp-observer"
    assert wh.hx_exchange and "nominal" in wh.hx_exchange[0]["message"]
    text = path.read_text(encoding="utf-8")
    assert "ACP assessment" in text
    assert "proceeding" in text
    assert "RustFS" in text
    assert "deadbeef" in text
    assert "DataProductTierUpkeep/7" in text
    assert retained_snapshots(prod)[0]["run_id"] == "7"


def test_two_runs_keep_both_snapshot_attrs(tmp_path: Path) -> None:
    import signals.ops.history as hist
    from signals.ops.metaflow_store import PRODUCT_ID, record_snapshot, retained_snapshots

    hist.BRIEF_DIR = tmp_path / "briefs"
    wh = MemoryWarehouse()
    for rid in ("1", "2"):
        record_snapshot(
            {"flow_name": "DemoFlow", "run_id": rid},
            warehouse=wh,
            env=_rustfs_env(),
            profile={},
        )
    prod = wh.get_product(PRODUCT_ID)
    assert prod is not None
    snaps = retained_snapshots(prod)
    assert {s["run_id"] for s in snaps} == {"1", "2"}
    assert prod["latest_run_id"] == "2"
    assert prod["assessment"] == "not_upkeep"


def test_assess_upkeep_nominal_on_walk() -> None:
    from signals.ops.metaflow_store import assess_upkeep
    from signals.ops.tier_upkeep import walk

    doc = walk(apply_sql=False)
    out = assess_upkeep(
        doc,
        {
            "object_store": "rustfs",
            "snapshot_uri": "s3://metaflow/metaflow/DataProductTierUpkeep/1",
            "pathspec": "DataProductTierUpkeep/1",
            "run_id": "1",
            "yk_app_id": "signals-dataproduct-tier-upkeep",
            "yk_queue": "root.platform",
        },
        expected=True,
    )
    assert out["assessment"] == "nominal"
    assert out["upkeep_nominal"] == "true"
    assert out["upkeep_fsm"] == "settled"
    assert "DROP RANGE PARTITION" in out["assessment_ok"] or "ADD-only" in out["assessment_ok"]


def test_assess_upkeep_off_nominal_failed_or_delete() -> None:
    from signals.ops.metaflow_store import assess_upkeep
    from signals.ops.tier_upkeep import walk

    doc = walk(apply_sql=False)
    doc["fsm"]["current"] = "failed"
    bad = assess_upkeep(
        doc,
        {"object_store": "rustfs", "snapshot_uri": "s3://metaflow/x/1", "yk_queue": "root.platform"},
        expected=True,
    )
    assert bad["assessment"] == "off_nominal"
    assert "failed" in bad["assessment_off"]

    doc2 = walk(apply_sql=False)
    if doc2.get("drop_sql"):
        doc2["drop_sql"] = ["DELETE FROM signals_dataproducts.details_tier0"]
        gone = assess_upkeep(
            doc2,
            {
                "object_store": "rustfs",
                "snapshot_uri": "s3://metaflow/x/1",
                "yk_queue": "root.platform",
            },
            expected=True,
        )
        assert gone["assessment"] == "off_nominal"
        assert "DELETE FROM" in gone["assessment_off"]


def test_holding_upkeep_is_nominal_in_progress() -> None:
    from signals.ops.metaflow_store import assess_upkeep
    from signals.ops.tier_upkeep import walk

    doc = walk(apply_sql=False)
    doc["fsm"]["current"] = "verifying"
    out = assess_upkeep(
        doc,
        {
            "object_store": "rustfs",
            "snapshot_uri": "s3://metaflow/metaflow/DataProductTierUpkeep/1",
            "yk_queue": "root.platform",
        },
        expected=True,
    )
    assert out["assessment"] == "nominal"
    assert out["assessment_phase"] == "in_progress"
    assert out["upkeep_nominal"] == "true"


def test_upkeep_run_without_walk_is_off_nominal(tmp_path: Path) -> None:
    import signals.ops.history as hist
    from signals.ops.metaflow_store import record_snapshot

    hist.BRIEF_DIR = tmp_path / "briefs"
    wh = MemoryWarehouse()
    with pytest.raises(WarehouseError, match="off-nominal"):
        record_snapshot(
            {
                "flow_name": "DataProductTierUpkeep",
                "run_id": "9",
                "yk_app_id": "signals-dataproduct-tier-upkeep",
                "yk_queue": "root.platform",
            },
            warehouse=wh,
            env=_rustfs_env(),
            profile={},
        )
    # Observation is still in the warehouse.
    prod = wh.get_product("signals.metaflow.snapshots")
    assert prod is not None
    assert prod["assessment"] == "off_nominal"
    assert wh.hx_reasoning[0]["quality"]
