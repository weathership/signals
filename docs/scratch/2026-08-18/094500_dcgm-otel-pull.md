# DCGM watts, pull-only OTel

DaemonSet `federation-system/dcgm-exporter` (hostPort 9400) is always on
when the federation package is deployed. It does **not** take a GPU token
and does **not** store series.

Signals engine yields OTLP JSON on `GET :9410/v1/metrics` by scraping
that live endpoint **once per request**. No scrape loop, no batch queue,
no file. 503 if the exporter is down.

Gaius pulls. Status.surfaces `kind=telemetry` advertises the LAN URL.
