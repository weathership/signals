"""Pull-only DCGM → OTLP. No retained series."""

from __future__ import annotations

from signals.telemetry.dcgm_otel import parse_prom, to_otlp


SAMPLE = """
# HELP DCGM_FI_DEV_POWER_USAGE Power draw (in W).
# TYPE DCGM_FI_DEV_POWER_USAGE gauge
DCGM_FI_DEV_POWER_USAGE{gpu="0",UUID="GPU-aaa",device="nvidia0"} 112.5
DCGM_FI_DEV_POWER_USAGE{gpu="1",UUID="GPU-bbb",device="nvidia1"} 14.2
DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION{gpu="0",UUID="GPU-aaa"} 9001000
DCGM_FI_PROF_GR_ENGINE_ACTIVE{gpu="0"} 0.5
"""


def test_parse_skips_comments() -> None:
    rows = parse_prom(SAMPLE)
    assert len(rows) == 4
    assert rows[0]["name"] == "DCGM_FI_DEV_POWER_USAGE"
    assert rows[0]["labels"]["gpu"] == "0"
    assert rows[0]["value"] == 112.5


def test_otlp_maps_watts_and_energy() -> None:
    doc = to_otlp(parse_prom(SAMPLE), host="tinybox", now_ns=1)
    metrics = doc["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    names = {m["name"] for m in metrics}
    assert "gpu.power.draw" in names
    assert "gpu.energy.consumption" in names
    power = next(m for m in metrics if m["name"] == "gpu.power.draw")
    assert power["unit"] == "W"
    assert "gauge" in power
    assert len(power["gauge"]["dataPoints"]) == 2
    energy = next(m for m in metrics if m["name"] == "gpu.energy.consumption")
    assert "sum" in energy
    host = {
        a["key"]: a["value"]["stringValue"]
        for a in doc["resourceMetrics"][0]["resource"]["attributes"]
    }
    assert host["service.name"] == "signals-dcgm"
    assert host["host.name"] == "tinybox"


def test_converter_is_stateless() -> None:
    a = to_otlp(parse_prom(SAMPLE), now_ns=1)
    b = to_otlp(parse_prom(SAMPLE), now_ns=2)
    assert a["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    # Different timestamps — no shared buffer mutated across calls.
    p1 = next(m for m in a["resourceMetrics"][0]["scopeMetrics"][0]["metrics"] if m["name"] == "gpu.power.draw")
    p2 = next(m for m in b["resourceMetrics"][0]["scopeMetrics"][0]["metrics"] if m["name"] == "gpu.power.draw")
    assert p1["gauge"]["dataPoints"][0]["timeUnixNano"] != p2["gauge"]["dataPoints"][0]["timeUnixNano"]
