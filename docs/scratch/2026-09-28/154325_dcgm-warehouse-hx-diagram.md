# DCGM warehouse and HX appendix

One Mermaid flowchart at `docs/current/src/appendix/dcgm-warehouse-hx.md`.
GitHub `flowchart` only: quoted labels, `<br>` line breaks, no init directive.
Parsed and rendered with Mermaid 11.4.1 (SVG viewBox about 4222×4668). The
book loads that same Mermaid from jsDelivr; if the CDN is down the fence
stays as source.

Drawn as the cluster, with this node called out as the narrow case (one
scrape URL, one Kudu master, replication 1, RustFS). Two exits from
dcgm-exporter: pull-only OTLP on `:9410` (not stored) and `kudu_scan` INSERT
into `signal_tier0`. Tier-1 rows in the picture are Parquet; Protobuf is the
OTLP and `zndx.agent.v1` objects. Iceberg manifests stay Avro. The lab settle
scripts still write HDF5 — said in the page, not drawn as the blueprint.

Association is a read-time join on `tx_id`, `epoch_hour`, and the hx `ts_ns`
span. `signal.gpu` / `signal.inst` are the device and instance. Hostname and
GPU UUID stay on the live OTLP point. External queues claim no GPU, so they
have hx and no `src = 0` rows.

Local `mdbook` is 0.4.40 and the installed `mdbook-d2` fails the render
context with "Unable to parse the input" (that binary expects mdbook 0.5).
Not caused by this page. CI uses latest mdbook.
