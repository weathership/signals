"""Engine Status.surfaces and ServerQuery remotes / peers / surfaces."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from signals.engine.generated.zndx.engine.v1 import engine_pb2
from signals.engine.s2s import (
    advertise_host,
    advertised_head,
    configured_peers,
    is_loopback_host,
    list_named_remotes,
    local_primary_ui,
    local_response,
    local_surfaces,
    rewrite_public_url,
)
from signals.engine.servicers.engine_status import SignalsEngineServicer
from signals.engine.yk_client import YkRestError


def test_list_named_remotes_from_checkout(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:weathership/signals.git"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "upstream", "git@github.com:cldr-research/signals-360.git"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    remotes = dict(list_named_remotes(tmp_path))
    assert remotes["origin"] == "git@github.com:weathership/signals.git"
    assert remotes["upstream"] == "git@github.com:cldr-research/signals-360.git"


def test_list_named_remotes_empty_when_not_a_repo(tmp_path: Path) -> None:
    assert list_named_remotes(tmp_path) == []
    assert advertised_head(tmp_path) == ""


def test_advertise_host_never_loopback(monkeypatch) -> None:
    monkeypatch.setenv("SIGNALS_ADVERTISE_HOST", "tinybox.dev.vista.zndx.org")
    assert advertise_host() == "tinybox.dev.vista.zndx.org"
    monkeypatch.setenv("SIGNALS_ADVERTISE_HOST", "127.0.0.1")
    monkeypatch.setenv("SIGNALS_KRB_HOST", "tinybox.dev.vista.zndx.org")
    assert advertise_host() == "tinybox.dev.vista.zndx.org"
    assert is_loopback_host("localhost")
    assert not is_loopback_host("tinybox.dev.vista.zndx.org")


def test_primary_ui_from_env(monkeypatch) -> None:
    monkeypatch.setenv("SIGNALS_ADVERTISE_HOST", "tinybox.dev.vista.zndx.org")
    monkeypatch.setenv("SIGNALS_UI_URL", "http://127.0.0.1:9889")
    assert local_primary_ui() == "http://tinybox.dev.vista.zndx.org:9889"
    monkeypatch.delenv("SIGNALS_UI_URL")
    monkeypatch.setenv("SIGNALS_UI_BIND", "0.0.0.0:19889")
    assert local_primary_ui() == "http://tinybox.dev.vista.zndx.org:19889"
    assert "127.0.0.1" not in local_primary_ui()
    assert "localhost" not in local_primary_ui()


def test_rewrite_public_url_leaves_lan_alone(monkeypatch) -> None:
    monkeypatch.setenv("SIGNALS_ADVERTISE_HOST", "tinybox.dev.vista.zndx.org")
    assert (
        rewrite_public_url("http://gaius.lan:9890/")
        == "http://gaius.lan:9890/"
    )


def test_status_advertises_primary_surface(monkeypatch) -> None:
    monkeypatch.setenv("SIGNALS_ADVERTISE_HOST", "tinybox.dev.vista.zndx.org")
    monkeypatch.delenv("SIGNALS_UI_URL", raising=False)
    yk = MagicMock()
    yk.partitions.side_effect = YkRestError("down")
    svc = SignalsEngineServicer("signals", yk=yk)
    resp = svc.Status(engine_pb2.StatusRequest(), context=None)
    assert resp.project == "signals"
    kinds = {s.kind: s.url for s in resp.surfaces}
    assert kinds["primary"] == "http://tinybox.dev.vista.zndx.org:9889"
    assert kinds["telemetry"].endswith(":9410/v1/metrics")
    assert "127.0.0.1" not in kinds["telemetry"]


def test_server_query_remotes_and_head(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@example.com:signals.git"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "t"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    resp = local_response(engine_pb2.SERVER_QUERY_KIND_REMOTES, root=tmp_path)
    assert resp.project == "signals"
    assert [(r.name, r.url) for r in resp.remotes] == [
        ("origin", "git@example.com:signals.git")
    ]
    assert resp.head == advertised_head(tmp_path)
    assert len(resp.head) == 40


def test_server_query_workloads_empty_is_honest() -> None:
    q = local_response(engine_pb2.SERVER_QUERY_KIND_WORKLOADS)
    assert q.project == "signals"
    assert list(q.workloads) == []


def test_server_query_surfaces_matches_status(monkeypatch) -> None:
    monkeypatch.setenv("SIGNALS_ADVERTISE_HOST", "tinybox.dev.vista.zndx.org")
    q = local_response(engine_pb2.SERVER_QUERY_KIND_SURFACES)
    assert [(s.kind, s.url) for s in q.surfaces] == [
        (s.kind, s.url) for s in local_surfaces()
    ]
    assert all("127.0.0.1" not in s.url for s in q.surfaces)


def test_server_query_peers_from_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SIGNALS_ADVERTISE_HOST", "tinybox.dev.vista.zndx.org")
    monkeypatch.delenv("SIGNALS_LATTICE_HOST", raising=False)
    contract = tmp_path / "peer-contract.json"
    contract.write_text(
        json.dumps(
            {
                "engine_grpc_lattice": {
                    "gaius": 50051,
                    "aegir": 50151,
                    "signals": 50551,
                    "service": "zndx.engine.v1.Engine",
                }
            }
        ),
        encoding="utf-8",
    )
    peers = configured_peers(contract)
    assert ("gaius", "tinybox.dev.vista.zndx.org:50051") in peers
    assert ("aegir", "tinybox.dev.vista.zndx.org:50151") in peers
    assert all(p[0] != "signals" for p in peers)
    q = local_response(engine_pb2.SERVER_QUERY_KIND_PEERS, contract=contract)
    assert {p.project for p in q.peers} == {"gaius", "aegir"}


def test_record_lineage_rejects_empty_and_mismatch() -> None:
    yk = MagicMock()
    svc = SignalsEngineServicer("signals", yk=yk)

    class Ctx:
        def abort(self, code, msg):
            raise RuntimeError(f"{code} {msg}")

    ctx = Ctx()
    with pytest.raises(RuntimeError, match="empty"):
        svc.RecordLineage(engine_pb2.LineageRequest(event_json=""), ctx)
    with pytest.raises(RuntimeError, match="not JSON"):
        svc.RecordLineage(engine_pb2.LineageRequest(event_json="{"), ctx)
    with pytest.raises(RuntimeError, match="event_type"):
        svc.RecordLineage(
            engine_pb2.LineageRequest(
                event_json='{"eventType":"START"}', event_type="FAIL"
            ),
            ctx,
        )


def test_servicer_server_query_remotes() -> None:
    svc = SignalsEngineServicer("signals", yk=MagicMock())
    resp = svc.ServerQuery(
        engine_pb2.ServerQueryRequest(kind=engine_pb2.SERVER_QUERY_KIND_REMOTES),
        context=None,
    )
    assert resp.project == "signals"
    names = {r.name for r in resp.remotes}
    # Live checkout: origin is expected; do not invent extra remotes.
    assert "origin" in names
    assert all(r.url for r in resp.remotes)


def test_server_query_cognition_and_contributions_empty_is_honest() -> None:
    """Kinds 10/11 (added 2026-08-31): Signals answers with unset hints.

    COGNITION — no cognition unit here. CONTRIBUTIONS — PENDING until
    Atlas+OpenLineage (Marquez sources), Metaflow, and Airflow answer as
    systems of record. Unset is honest; peers treat it as absence.
    """
    from signals.engine.generated.zndx.engine.v1 import engine_pb2 as pb
    from signals.engine.s2s import local_response

    for kind in (
        pb.SERVER_QUERY_KIND_COGNITION,
        pb.SERVER_QUERY_KIND_CONTRIBUTIONS,
    ):
        resp = local_response(int(kind))
        assert resp.project == "signals"
        assert not resp.HasField("cognition")
        assert not resp.HasField("contributions")
        assert not resp.surfaces and not resp.products
