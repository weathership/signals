"""GpuMetricsSettle — analog closed hours, Iceberg verify, Kudu DROP RANGE.

Airflow and pg_cron are the clock. This flow is the work.
"""

from __future__ import annotations

from signals.ops.gpu_metrics_settle import walk

try:
    from metaflow import FlowSpec, current, project, step
except ImportError:
    FlowSpec = object  # type: ignore[misc,assignment]

    def step(fn):  # type: ignore[no-redef]
        return fn

    def project(**_kw):  # type: ignore[no-redef]
        def wrap(cls):
            return cls

        return wrap

    current = None  # type: ignore[assignment]


@project(name="signals")
class GpuMetricsSettle(FlowSpec):
    """Hourly gpu_metrics honesty: Iceberg verify then DROP RANGE."""

    @step
    def start(self):
        self.next(self.settle)

    @step
    def settle(self):
        self.doc = walk(apply=True, analog=True)
        self.next(self.end)

    @step
    def end(self):
        self.dropped = list(self.doc.get("dropped") or [])
        self.analoged = list(self.doc.get("analoged") or [])


if __name__ == "__main__":
    GpuMetricsSettle()
