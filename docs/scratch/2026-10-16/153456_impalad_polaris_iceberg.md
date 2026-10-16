# Impala dropped Iceberg because Polaris was not listening yet

Gaius Discover at `:9890` stayed on "connecting…". The engine was up.
`/api/gaius/v1/discover` returned 503 `#COG.00000031.NOWHFDW`: the
`signal` view could not resolve `signals_dataproducts.signal_tier1`.

`signal_tier1` is in Polaris. It was absent from the Impala coordinator
because `IcebergMetaProvider` connects once during Frontend init. On
2026-10-12 00:48:44 that POST to `:8181` was connection refused (Polaris
was still starting). `LocalImpl` logs the error and does not add the
provider. Every later query plans without tier1 until the process starts
again.

Restarted `impala-impalad` after Polaris was healthy. `signal_tier1`
answers, and Discover returns 200 (cold fill ~24s, then cache ~2ms,
inside the page's 4s fetch).

`impala-impalad` now waits for Polaris `:8182/q/health/ready` and
depends on `polaris` being healthy, and exits if that wait fails.
A half-started coordinator is what left the UI dark for four days.
