"""Convert DCGM Prometheus text to OTLP JSON on demand.

No scrape loop. No queue. No file. Each GET fetches live DCGM /metrics
and returns OTLP resourceMetrics. Empty consumer → no work beyond the
idle DCGM exporter process.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

PROM_LINE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"
    r"(?:\{(?P<labels>[^}]*)\})?\s+"
    r"(?P<value>[-+0-9.eE]+)\s*$"
)
LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"])*)"')

# Prefer OTel-ish names for the fields Gaius will chart first.
FIELD_MAP = {
    "DCGM_FI_DEV_POWER_USAGE": ("gpu.power.draw", "W", "gauge"),
    "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION": (
        "gpu.energy.consumption",
        "mJ",
        "counter",
    ),
    "DCGM_FI_DEV_GPU_TEMP": ("gpu.temperature", "Cel", "gauge"),
    "DCGM_FI_DEV_MEMORY_TEMP": ("gpu.memory.temperature", "Cel", "gauge"),
    "DCGM_FI_DEV_GPU_UTIL": ("gpu.utilization", "1", "gauge"),
    "DCGM_FI_DEV_MEM_COPY_UTIL": ("gpu.memory.bandwidth.utilization", "1", "gauge"),
    "DCGM_FI_DEV_FB_USED": ("gpu.memory.used", "MiBy", "gauge"),
    "DCGM_FI_DEV_FB_FREE": ("gpu.memory.free", "MiBy", "gauge"),
    "DCGM_FI_DEV_SM_CLOCK": ("gpu.frequency.sm", "MHz", "gauge"),
    "DCGM_FI_DEV_MEM_CLOCK": ("gpu.frequency.memory", "MHz", "gauge"),
    "DCGM_FI_DEV_XID_ERRORS": ("gpu.xid.errors", "1", "gauge"),
}

DEFAULT_PROM_URL = "http://127.0.0.1:9400/metrics"


def fetch_prom(url: str, timeout_s: float = 4.0) -> str:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_prom(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = PROM_LINE.match(line)
        if not m:
            continue
        labels: dict[str, str] = {}
        blob = m.group("labels") or ""
        for k, v in LABEL.findall(blob):
            labels[k] = v.replace(r"\"", '"')
        try:
            value = float(m.group("value"))
        except ValueError:
            continue
        rows.append({"name": m.group("name"), "labels": labels, "value": value})
    return rows


def _attr(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def to_otlp(
    rows: list[dict[str, Any]],
    *,
    service: str = "signals-dcgm",
    host: str = "",
    now_ns: int | None = None,
) -> dict[str, Any]:
    ts = str(now_ns if now_ns is not None else time.time_ns())
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        field = row["name"]
        otel_name, unit, kind = FIELD_MAP.get(field, (field.lower(), "1", "gauge"))
        key = (otel_name, unit, kind)
        attrs = [_attr("dcgm.field", field)]
        for lk, lv in sorted(row["labels"].items()):
            if lk in {"gpu", "device", "UUID", "pci_bus_id", "modelName", "Hostname"}:
                attrs.append(_attr(f"gpu.{lk.lower()}" if lk != "gpu" else "gpu.index", lv))
            else:
                attrs.append(_attr(lk, lv))
        grouped.setdefault(key, []).append(
            {"asDouble": row["value"], "timeUnixNano": ts, "attributes": attrs}
        )
    metrics: list[dict[str, Any]] = []
    for (name, unit, kind), points in grouped.items():
        if kind == "counter":
            body: dict[str, Any] = {"sum": {"dataPoints": points, "aggregationTemporality": 2, "isMonotonic": True}}
        else:
            body = {"gauge": {"dataPoints": points}}
        metrics.append({"name": name, "unit": unit, **body})
    resource_attrs = [_attr("service.name", service)]
    if host:
        resource_attrs.append(_attr("host.name", host))
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": resource_attrs},
                "scopeMetrics": [
                    {
                        "scope": {"name": "signals.telemetry.dcgm", "version": "1"},
                        "metrics": metrics,
                    }
                ],
            }
        ]
    }


def live_otlp(prom_url: str | None = None) -> dict[str, Any]:
    url = (prom_url or os.environ.get("SIGNALS_DCGM_PROM_URL") or DEFAULT_PROM_URL).strip()
    host = (os.environ.get("SIGNALS_ADVERTISE_HOST") or os.environ.get("SIGNALS_KRB_HOST") or "").strip()
    return to_otlp(parse_prom(fetch_prom(url)), host=host)


class _Handler(BaseHTTPRequestHandler):
    server_version = "signals-dcgm-otel/1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/healthz", "/"):
            self._send(200, b'{"ok":true,"retain":false}\n', "application/json")
            return
        if path in ("/v1/metrics", "/otlp/v1/metrics"):
            try:
                doc = live_otlp()
            except urllib.error.URLError as e:
                self._send(
                    503,
                    json.dumps({"error": f"dcgm-exporter unreachable: {e}"}).encode(),
                    "application/json",
                )
                return
            self._send(200, json.dumps(doc).encode(), "application/json")
            return
        if path == "/metrics":
            url = (os.environ.get("SIGNALS_DCGM_PROM_URL") or DEFAULT_PROM_URL).strip()
            try:
                text = fetch_prom(url)
            except urllib.error.URLError as e:
                self._send(503, f"dcgm-exporter unreachable: {e}\n".encode(), "text/plain")
                return
            self._send(200, text.encode(), "text/plain; version=0.0.4")
            return
        self._send(404, b'{"error":"not found"}\n', "application/json")


def serve(host: str = "0.0.0.0", port: int = 9410) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), _Handler)
    return httpd


def main() -> None:
    host = os.environ.get("SIGNALS_DCGM_OTEL_HOST", "0.0.0.0")
    port = int(os.environ.get("SIGNALS_DCGM_OTEL_PORT", "9410"))
    httpd = serve(host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
