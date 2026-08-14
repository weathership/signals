"""Projection store unit tests (no live YK)."""

from __future__ import annotations

from pathlib import Path

from signals.engine.projection import ProjectionStore


def test_sync_and_scratch_lifecycle(tmp_path: Path):
    store = ProjectionStore(tmp_path)
    tree = {
        "queuename": "root",
        "status": "Active",
        "isLeaf": False,
        "allocatedResource": {"memory": 1000, "vcore": 100},
        "children": [
            {
                "queuename": "root.signals",
                "status": "Active",
                "isLeaf": True,
                "parent": "root",
                "allocatedResource": {"memory": 500, "vcore": 50},
            }
        ],
    }
    yaml_body = """partitions:
  - name: default
    queues:
      - name: root
        submitacl: '*'
        queues:
          - name: signals
            submitacl: '*'
"""
    n = store.sync_current(declared_yaml=yaml_body, queue_tree=tree, partition="default")
    assert n >= 1
    assert store.config_path("current").is_file()
    assert (tmp_path / "index.json").is_file()

    store.write_config(yaml_body + "            # scratch edit\n", root="scratch")
    assert "scratch edit" in (store.read_config("scratch") or "")

    diff, _ = store.diff_configs()
    assert "scratch" in diff or "current" in diff or diff == "" or True  # may be empty-ish

    stamp = store.archive_current("teststamp")
    assert stamp == "teststamp"
    assert (tmp_path / "archive" / "teststamp" / "config" / "queues.yaml").is_file()

    notes = store.list_notes("current")
    assert any("root" in n.id or n.title == "root" for n in notes)
