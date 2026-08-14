"""normalize_declared_config strips runtime-only YK GET /config fields."""

from signals.engine.yk_client import normalize_declared_config


def test_strips_checksum_extra_deadlock():
    raw = """partitions:
  - name: default
    queues:
      - name: root
        submitacl: '*'
checksum: ABC
extra:
  admissionController.filtering.enable: "true"
deadlockdetectionenabled: false
deadlocktimeoutseconds: 60
"""
    out = normalize_declared_config(raw)
    assert "partitions:" in out
    assert "checksum" not in out
    assert "extra" not in out
    assert "deadlock" not in out
    assert "root" in out


def test_passthrough_non_yaml():
    assert normalize_declared_config("not: [yaml") == "not: [yaml"
