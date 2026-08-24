# gpu_metrics soak 496541 hot (05:23Z)

FDW lag ~0 on hour 496541. Iceberg `gpu_metrics_tier1` still four analog
hours through 496540 (19968). Ranges 496536–496544. Static
`/tmp/gpu_kudu_create` not replaced (dynamic toolchain client missing
`libsasl2.so.2`). Do not DROP Kudu 496540 until FDW can read the UNION
view.
