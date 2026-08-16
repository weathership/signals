"""DataProductTierUpkeep — Metaflow flow for data-product.tier-upkeep.

Airflow schedules this (`airflow create` or API trigger). YK:

- Flow-level **proxy sentinel** ``signals-dataproduct-tier-upkeep`` on
  ``root.platform`` (stamp: ``config/platform/tier-upkeep-sentinel.yaml``).
- If a step is ``@kubernetes``, that pod **is** a YK Application — stamp the
  same queue / workload_id. Do not invent a second app-id per step unless
  the step is a distinct claim.
"""

from __future__ import annotations

from signals.ops.tier_upkeep import YK_APP_ID, YK_QUEUE, walk

try:
    from metaflow import FlowSpec, current, environment, project, step
except ImportError:  # hermetic / no platform client
    FlowSpec = object  # type: ignore[misc,assignment]

    def step(fn):  # type: ignore[no-redef]
        return fn

    def environment(**_kw):  # type: ignore[no-redef]
        def wrap(fn):
            return fn

        return wrap

    def project(**_kw):  # type: ignore[no-redef]
        def wrap(cls):
            return cls

        return wrap

    current = None  # type: ignore[assignment]


@project(name="signals")
class DataProductTierUpkeep(FlowSpec):
    """Weekly ADD + 4-week settle. Fail closed before DROP."""

    @step
    def start(self):
        self.yk_app_id = YK_APP_ID
        self.yk_queue = YK_QUEUE
        self.next(self.plan)

    @step
    def plan(self):
        self.doc = walk(apply_sql=False)
        self.next(self.add_week)

    @environment(vars={"YK_QUEUE": YK_QUEUE, "YK_APP_ID": YK_APP_ID})
    @step
    def add_week(self):
        # Impala ALTER ADD RANGE PARTITION — flow step, not host cron.
        self.add_sql = self.doc["add_sql"]
        self.next(self.settle)

    @environment(vars={"YK_QUEUE": YK_QUEUE, "YK_APP_ID": YK_APP_ID})
    @step
    def settle(self):
        # copy → verify → drop. DROP only after verify (method holding).
        self.settle = self.doc.get("settle")
        self.drop_sql = self.doc.get("drop_sql") or []
        self.next(self.end)

    @step
    def end(self):
        from signals.ops.metaflow_store import record_from_current

        ev, brief = record_from_current(
            current,
            extra={
                "yk_app_id": self.yk_app_id,
                "yk_queue": self.yk_queue,
                "steps": "start,plan,add_week,settle,end",
                "successful": "true",
                "upkeep": getattr(self, "doc", None),
            },
        )
        self.snapshot_tx_id = ev["tx_id"]
        self.snapshot_brief = str(brief)
        self.snapshot_summary = ev.get("summary") or ""
        self.assessment = ev.get("assessment") or ""


if __name__ == "__main__":
    DataProductTierUpkeep()
