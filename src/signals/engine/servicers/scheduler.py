"""zndx.scheduler.v1.Scheduler servicer (lab backend: YuniKorn)."""

from __future__ import annotations

import logging
import threading
from typing import Any

import grpc

from signals.engine.activities import (
    ActivityError,
    ActivityService,
    LeaseStore,
    watch_event,
)
from signals.engine.airflow_api import AirflowClient, AirflowError
from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2, scheduler_pb2_grpc
from signals.engine.k8s_apply import ApplyConfig, ApplyError, apply_queues_yaml
from signals.engine.projection import ProjectionStore
from signals.engine.queue_share import (
    QueueShareService,
    QueueShareStore,
    SharePersistError,
)
from signals.engine.yk_client import (
    YkRestClient,
    YkRestError,
    normalize_declared_config,
)

log = logging.getLogger("signals.engine.scheduler")


def _share_state(name: str) -> int:
    return {
        "RECORDED": scheduler_pb2.QUEUE_SHARE_RECORDED,
        "SUPERSEDED": scheduler_pb2.QUEUE_SHARE_SUPERSEDED,
        "APPLIED": scheduler_pb2.QUEUE_SHARE_APPLIED,
        "REJECTED": scheduler_pb2.QUEUE_SHARE_REJECTED,
        "APPLYING": getattr(scheduler_pb2, "QUEUE_SHARE_APPLYING", 5),
    }.get(name, scheduler_pb2.QUEUE_SHARE_STATE_UNSPECIFIED)


def _res_map(obj: Any) -> scheduler_pb2.ResourceMap:
    m = scheduler_pb2.ResourceMap()
    if not isinstance(obj, dict):
        return m
    for k, v in obj.items():
        try:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                m.quantities[str(k)] = int(v)
            elif isinstance(v, str) and v.isdigit():
                m.quantities[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return m


def _queue_node(data: Any) -> scheduler_pb2.QueueNode:
    if not isinstance(data, dict):
        return scheduler_pb2.QueueNode(name="?")
    name = data.get("queuename") or data.get("queueName") or "?"
    kids_raw = data.get("children") or data.get("queues") or []
    if not isinstance(kids_raw, list):
        kids_raw = []
    abs_used = data.get("absUsedCapacity") or {}
    abs_map: dict[str, float] = {}
    if isinstance(abs_used, dict):
        for k, v in abs_used.items():
            try:
                abs_map[str(k)] = float(v)
            except (TypeError, ValueError):
                pass
    node = scheduler_pb2.QueueNode(
        name=str(name),
        status=str(data.get("status") or ""),
        is_leaf=bool(data.get("isLeaf", data.get("isleaf", len(kids_raw) == 0))),
        is_managed=bool(data.get("isManaged", data.get("ismanaged", True))),
        parent=str(data.get("parent") or ""),
        max=_res_map(data.get("maxResource") or data.get("max")),
        guaranteed=_res_map(data.get("guaranteedResource") or data.get("guaranteed")),
        allocated=_res_map(
            data.get("allocatedResource") or data.get("allocated") or data.get("occupied")
        ),
        pending=_res_map(data.get("pendingResource") or data.get("pending")),
        headroom=_res_map(data.get("headroom")),
        abs_used_capacity=abs_map,
        max_running_apps=int(data.get("maxRunningApps") or data.get("MaxRunningApps") or 0),
        running_apps=int(data.get("runningApps") or data.get("RunningApps") or 0),
        sorting_policy=str(data.get("sortingPolicy") or ""),
        preemption_enabled=bool(data.get("preemptionEnabled", True)),
    )
    props = data.get("properties") or {}
    if isinstance(props, dict):
        for k, v in props.items():
            node.properties[str(k)] = str(v)
    for c in kids_raw:
        if isinstance(c, dict):
            node.children.append(_queue_node(c))
    return node


def _root_from_tree(tree: Any) -> scheduler_pb2.QueueNode:
    if isinstance(tree, list):
        if not tree:
            return scheduler_pb2.QueueNode(name="root")
        return _queue_node(tree[0])
    return _queue_node(tree)


def _abort_yk(context, e: YkRestError) -> None:
    code = grpc.StatusCode.UNAVAILABLE
    if e.status_code == 404:
        code = grpc.StatusCode.NOT_FOUND
    elif e.status_code == 400:
        code = grpc.StatusCode.INVALID_ARGUMENT
    context.abort(code, str(e))


class SchedulerServicer(scheduler_pb2_grpc.SchedulerServicer):
    def __init__(
        self,
        yk: YkRestClient,
        store: ProjectionStore,
        apply_cfg: ApplyConfig | None = None,
        activities: ActivityService | None = None,
        leases: LeaseStore | None = None,
    ):
        self.yk = yk
        self.store = store
        self.apply_cfg = apply_cfg or ApplyConfig.from_env()
        self.shares = QueueShareService(QueueShareStore(store.root / "shares"))
        # Coordination Activities: the lease store is shared with the control
        # HTTP (the Airflow sensor observes it); the Airflow client is constructed
        # lazily so the engine boots with Airflow down — every RPC then surfaces
        # the Airflow error itself.
        self.leases = leases or LeaseStore(store.root / "activities")
        self._activities: ActivityService | None = activities
        self._activities_mu = threading.Lock()
        # 2026-09-06: records left RECORDED by the previous engine process never
        # reached the applier (its pending set is in-memory) until the next
        # ingest — gaius waited its 600 s net against a dark applier after every
        # Signals restart. Re-queue them now; the applier converges on its own.
        try:
            self.shares.resume(
                apply_fn=self._share_apply_fn,
                read_yaml=self._share_read_yaml,
                write_scratch=self._share_write_scratch,
            )
        except Exception as e:  # noqa: BLE001 — boot must not fail on the applier
            log.warning("queue share resume skipped: %s", e)

    # ── queue share I/O (shared by ingest and the boot-time resume) ────────
    def _share_read_yaml(self) -> str | None:
        return self.store.read_config("current") or self.store.read_config("scratch")

    def _share_write_scratch(self, body: str) -> None:
        self.store.write_config(body, root="scratch")

    def _share_apply_fn(self):
        # Runs on the applier thread after the RPC has returned — never hand it
        # a (dead) request context. Returns the promote response so the applier
        # can log what was applied (its success path was silent before 2026-09-04).
        r = self.PromoteScratch(scheduler_pb2.PromoteScratchRequest(dry_run=False), None)
        if not r.ok:
            raise RuntimeError(r.message or "PromoteScratch failed")
        return r

    def activities(self) -> ActivityService:
        with self._activities_mu:
            if self._activities is None:
                self._activities = ActivityService(AirflowClient(), self.leases)
            return self._activities

    def ListPartitions(self, request, context):  # noqa: N802
        try:
            data = self.yk.partitions()
        except YkRestError as e:
            _abort_yk(context, e)
            return scheduler_pb2.ListPartitionsResponse()
        out = scheduler_pb2.ListPartitionsResponse()
        rows = data if isinstance(data, list) else []
        for p in rows:
            if not isinstance(p, dict):
                continue
            cap = (p.get("capacity") or {}).get("capacity") or p.get("capacity") or {}
            used = (p.get("capacity") or {}).get("usedCapacity") or {}
            info = scheduler_pb2.PartitionInfo(
                name=str(p.get("name") or ""),
                state=str(p.get("state") or ""),
                site_id=str(p.get("clusterId") or ""),
                total_nodes=int(p.get("totalNodes") or 0),
                preemption_enabled=bool(p.get("preemptionEnabled", False)),
            )
            if isinstance(cap, dict):
                for k, v in cap.items():
                    try:
                        info.capacity[str(k)] = int(v)
                    except (TypeError, ValueError):
                        pass
            if isinstance(used, dict):
                for k, v in used.items():
                    try:
                        info.used_capacity[str(k)] = int(v)
                    except (TypeError, ValueError):
                        pass
            out.partitions.append(info)
        return out

    def GetQueueTree(self, request, context):  # noqa: N802
        part = request.partition or "default"
        try:
            tree = self.yk.queue_tree(part)
        except YkRestError as e:
            _abort_yk(context, e)
            return scheduler_pb2.GetQueueTreeResponse()
        return scheduler_pb2.GetQueueTreeResponse(
            partition=part, root=_root_from_tree(tree)
        )

    def GetQueue(self, request, context):  # noqa: N802
        part = request.partition or "default"
        try:
            q = self.yk.queue(part, request.queue, subtree=request.include_subtree)
        except YkRestError as e:
            _abort_yk(context, e)
            return scheduler_pb2.GetQueueResponse()
        return scheduler_pb2.GetQueueResponse(partition=part, queue=_queue_node(q))

    def ListQueueApplications(self, request, context):  # noqa: N802
        part = request.partition or "default"
        try:
            data = self.yk.queue_applications(part, request.queue)
        except YkRestError as e:
            _abort_yk(context, e)
            return scheduler_pb2.ListQueueApplicationsResponse()
        out = scheduler_pb2.ListQueueApplicationsResponse()
        rows = data if isinstance(data, list) else (data or {}).get("applications") or []
        for a in rows:
            if not isinstance(a, dict):
                continue
            out.applications.append(
                scheduler_pb2.ApplicationInfo(
                    application_id=str(
                        a.get("applicationID") or a.get("applicationId") or ""
                    ),
                    state=str(a.get("applicationState") or a.get("state") or ""),
                    queue_name=str(a.get("queueName") or ""),
                    user=str(a.get("user") or ""),
                    used=_res_map(a.get("usedResource") or a.get("used")),
                    submission_time_ns=int(a.get("submissionTime") or 0),
                )
            )
        return out

    def ListNodes(self, request, context):  # noqa: N802
        part = request.partition or "default"
        try:
            data = self.yk.nodes(part)
        except YkRestError as e:
            _abort_yk(context, e)
            return scheduler_pb2.ListNodesResponse()
        out = scheduler_pb2.ListNodesResponse()
        rows = data if isinstance(data, list) else []
        for n in rows:
            if not isinstance(n, dict):
                continue
            attrs = n.get("attributes") or {}
            host = str(
                n.get("hostName")
                or (attrs.get("si.io/hostname") if isinstance(attrs, dict) else "")
                or ""
            )
            rack = str(
                n.get("rackName")
                or (attrs.get("si.io/rackname") if isinstance(attrs, dict) else "")
                or ""
            )
            out.nodes.append(
                scheduler_pb2.NodeInfo(
                    node_id=str(n.get("nodeID") or n.get("nodeId") or ""),
                    host_name=host,
                    rack_name=rack,
                    capacity=_res_map(n.get("capacity")),
                    allocated=_res_map(
                        n.get("allocated") or n.get("occupied") or n.get("allocatedResource")
                    ),
                    available=_res_map(n.get("available") or n.get("availableResource")),
                    schedulable=bool(n.get("schedulable", True)),
                )
            )
        return out

    def GetPlacementPolicy(self, request, context):  # noqa: N802
        part = request.partition or "default"
        try:
            data = self.yk.placement_rules(part)
        except YkRestError as e:
            _abort_yk(context, e)
            return scheduler_pb2.GetPlacementPolicyResponse()
        out = scheduler_pb2.GetPlacementPolicyResponse()
        rows = data if isinstance(data, list) else []
        for r in rows:
            if not isinstance(r, dict):
                continue
            pr = scheduler_pb2.PlacementRule(name=str(r.get("name") or ""))
            params = r.get("parameters") or {}
            if isinstance(params, dict):
                for k, v in params.items():
                    pr.parameters[str(k)] = str(v)
            out.rules.append(pr)
        return out

    def GetDeclaredConfig(self, request, context):  # noqa: N802
        try:
            yaml_body = self.yk.config()
        except YkRestError as e:
            _abort_yk(context, e)
            return scheduler_pb2.GetDeclaredConfigResponse()
        return scheduler_pb2.GetDeclaredConfigResponse(
            document=scheduler_pb2.PolicyDocument(
                media_type="text/yaml", body=yaml_body
            )
        )

    def ValidateConfig(self, request, context):  # noqa: N802
        yaml_body = (request.document.body if request.document else "") or ""
        try:
            ok, msg = self.yk.validate_conf(yaml_body)
        except YkRestError as e:
            return scheduler_pb2.ValidateConfigResponse(
                ok=False, message=str(e), errors=[str(e)]
            )
        errors = [] if ok else [msg]
        return scheduler_pb2.ValidateConfigResponse(ok=ok, message=msg, errors=errors)

    def Health(self, request, context):  # noqa: N802
        try:
            data = self.yk.healthcheck()
        except YkRestError as e:
            return scheduler_pb2.HealthResponse(
                healthy=False,
                backend="yunikorn",
                checks=[
                    scheduler_pb2.HealthCheck(
                        name="backend-rest",
                        succeeded=False,
                        description="scheduler backend healthcheck",
                        diagnosis=str(e)[:300],
                    )
                ],
            )
        if not isinstance(data, dict):
            return scheduler_pb2.HealthResponse(healthy=True, backend="yunikorn")
        checks = []
        for c in data.get("HealthChecks") or data.get("healthChecks") or []:
            if not isinstance(c, dict):
                continue
            checks.append(
                scheduler_pb2.HealthCheck(
                    name=str(c.get("Name") or c.get("name") or ""),
                    succeeded=bool(c.get("Succeeded", c.get("succeeded", False))),
                    description=str(c.get("Description") or c.get("description") or ""),
                    diagnosis=str(
                        c.get("DiagnosisMessage") or c.get("diagnosis") or ""
                    ),
                )
            )
        return scheduler_pb2.HealthResponse(
            healthy=bool(data.get("Healthy", data.get("healthy", True))),
            backend="yunikorn",
            checks=checks,
        )

    def GetDashboard(self, request, context):  # noqa: N802
        """yk-web /dashboard fan-in — structured for landing Scheduler band."""
        part = (request.partition or "").strip() or "default"
        healthy = True
        try:
            hc = self.yk.healthcheck()
            if isinstance(hc, dict):
                healthy = bool(hc.get("Healthy", hc.get("healthy", True)))
        except YkRestError:
            healthy = False

        partitions_raw: list[Any] = []
        try:
            pr = self.yk.partitions()
            if isinstance(pr, list):
                partitions_raw = pr
            elif isinstance(pr, dict):
                partitions_raw = pr.get("partitions") or []
        except YkRestError as e:
            _abort_yk(context, e)
            return scheduler_pb2.GetDashboardResponse()

        part_names = [
            str(p.get("name") or p.get("Name") or "")
            for p in partitions_raw
            if isinstance(p, dict)
        ]
        part_names = [n for n in part_names if n]
        if part not in part_names and part_names:
            part = part_names[0]

        pinfo = next(
            (
                p
                for p in partitions_raw
                if isinstance(p, dict)
                and str(p.get("name") or p.get("Name") or "") == part
            ),
            partitions_raw[0] if partitions_raw else {},
        )
        if not isinstance(pinfo, dict):
            pinfo = {}

        apps_map = pinfo.get("applications") or pinfo.get("Applications") or {}
        if not isinstance(apps_map, dict):
            apps_map = {}
        total_apps = int(
            apps_map.get("total")
            or apps_map.get("Total")
            or sum(
                int(v)
                for k, v in apps_map.items()
                if str(k).lower() != "total" and str(v).isdigit()
            )
            or 0
        )
        total_ctn = int(
            pinfo.get("totalContainers")
            or pinfo.get("TotalContainers")
            or pinfo.get("totalcontainers")
            or 0
        )
        sort_pol = ""
        nsp = pinfo.get("nodeSortingPolicy") or pinfo.get("nodesortingpolicy") or {}
        if isinstance(nsp, dict):
            sort_pol = str(nsp.get("type") or nsp.get("Type") or "")
        elif isinstance(nsp, str):
            sort_pol = nsp

        cluster_name = "—"
        cluster_id = str(pinfo.get("clusterId") or pinfo.get("clusterID") or "")
        try:
            clusters = self.yk.clusters()
            if isinstance(clusters, list) and clusters:
                c0 = clusters[0] if isinstance(clusters[0], dict) else {}
                cluster_name = str(
                    c0.get("clusterName") or c0.get("clustername") or "kubernetes"
                )
                if not cluster_id:
                    cluster_id = str(c0.get("rmId") or "")
                if c0.get("partition"):
                    # keep selected partition
                    pass
        except YkRestError:
            pass

        summary = scheduler_pb2.SchedulerSummary(
            name=cluster_name,
            backend="yunikorn",
            status=str(pinfo.get("state") or pinfo.get("State") or ""),
            total_nodes=int(pinfo.get("totalNodes") or pinfo.get("totalnodes") or 0),
            node_sort_policy=sort_pol or "fair",
            total_applications=total_apps,
            total_tasks=total_ctn,
            partition=part,
            site_id=cluster_id,
        )

        app_status = []
        for k, v in apps_map.items():
            if str(k).lower() == "total":
                continue
            try:
                cnt = int(v)
            except (TypeError, ValueError):
                continue
            app_status.append(scheduler_pb2.StatusSlice(label=str(k), count=cnt))
        # containers: YK partition often only has total; approximate running = total
        ctn_status = [
            scheduler_pb2.StatusSlice(label="Running", count=total_ctn),
        ]

        def _hist(points: Any, value_key: str) -> list:
            out = []
            if not isinstance(points, list):
                return out
            for pt in points:
                if not isinstance(pt, dict):
                    continue
                ts = pt.get("timestamp") or pt.get("Timestamp") or 0
                raw = pt.get(value_key) or pt.get(value_key[0].upper() + value_key[1:]) or 0
                try:
                    val = int(raw)
                except (TypeError, ValueError):
                    try:
                        val = int(str(raw))
                    except ValueError:
                        val = 0
                try:
                    ts_i = int(ts)
                except (TypeError, ValueError):
                    ts_i = 0
                out.append(scheduler_pb2.HistoryPoint(timestamp_ns=ts_i, value=val))
            return out

        app_hist: list = []
        ctn_hist: list = []
        try:
            app_hist = _hist(self.yk.history_apps(), "totalApplications")
        except YkRestError:
            pass
        try:
            ctn_hist = _hist(self.yk.history_containers(), "totalContainers")
        except YkRestError:
            pass

        utils: list = []
        try:
            util_raw = self.yk.node_utilizations()
            # list of { clusterId, partition, utilizations: [ { type, utilization: [...] } ] }
            rows = util_raw if isinstance(util_raw, list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("partition") or "") not in ("", part):
                    # prefer matching partition; still accept if only one
                    if len(rows) > 1 and str(row.get("partition") or "") != part:
                        continue
                for u in row.get("utilizations") or []:
                    if not isinstance(u, dict):
                        continue
                    rtype = str(u.get("type") or u.get("Type") or "")
                    buckets = []
                    for b in u.get("utilization") or []:
                        if not isinstance(b, dict):
                            continue
                        buckets.append(
                            scheduler_pb2.UtilBucket(
                                bucket_name=str(
                                    b.get("bucketName") or b.get("bucketname") or ""
                                ),
                                num_nodes=int(b.get("numOfNodes") or b.get("numofnodes") or 0),
                            )
                        )
                    utils.append(
                        scheduler_pb2.ResourceUtilization(
                            resource_type=rtype, buckets=buckets
                        )
                    )
        except YkRestError:
            pass

        return scheduler_pb2.GetDashboardResponse(
            summary=summary,
            application_status=app_status,
            task_status=ctn_status,
            application_history=app_hist,
            task_history=ctn_hist,
            node_utilizations=utils,
            healthy=healthy,
            partition=part,
            partitions=part_names,
        )

    def SyncProjection(self, request, context):  # noqa: N802
        part = request.partition or "default"
        try:
            yaml_body = self.yk.config()
            tree = self.yk.queue_tree(part)
        except YkRestError as e:
            _abort_yk(context, e)
            return scheduler_pb2.SyncProjectionResponse()
        n = self.store.sync_current(
            declared_yaml=yaml_body, queue_tree=tree, partition=part
        )
        return scheduler_pb2.SyncProjectionResponse(
            notes_written=n,
            config_path="current/config/queues.yaml",
        )

    def GetProjectionIndex(self, request, context):  # noqa: N802
        root = _root_name(request.root)
        archive_id = request.archive_id or None
        notes = self.store.list_notes(root, archive_id=archive_id)
        out = scheduler_pb2.GetProjectionIndexResponse(total=len(notes))
        for n in notes:
            out.notes.append(
                scheduler_pb2.ProjectionNoteMeta(
                    id=n.id,
                    title=n.title,
                    kind=n.kind,
                    root=_root_enum(n.root),
                    relpath=n.relpath,
                    links=n.links,
                )
            )
        return out

    def GetProjectionNote(self, request, context):  # noqa: N802
        root = _root_name(request.root)
        got = self.store.get_note(
            root, request.note_id, archive_id=request.archive_id or None
        )
        if not got:
            context.abort(grpc.StatusCode.NOT_FOUND, f"note not found: {request.note_id}")
            return scheduler_pb2.GetProjectionNoteResponse()
        fm, body = got
        import json

        return scheduler_pb2.GetProjectionNoteResponse(
            id=str(fm.get("id") or request.note_id),
            title=str(fm.get("title") or request.note_id),
            kind=str(fm.get("kind") or "note"),
            body=body,
            frontmatter_json=json.dumps(fm),
            links=list(fm.get("links") or []),
        )

    def WriteScratchConfig(self, request, context):  # noqa: N802
        try:
            body = (request.document.body if request.document else "") or ""
            self.store.write_config(body, root="scratch")
            if request.rebuild_notes:
                # write_config already rebuilds notes from yaml
                pass
            return scheduler_pb2.WriteScratchConfigResponse(ok=True, message="scratch updated")
        except Exception as e:  # noqa: BLE001
            return scheduler_pb2.WriteScratchConfigResponse(ok=False, message=str(e))

    def DiffConfig(self, request, context):  # noqa: N802
        live = None
        if request.include_live:
            try:
                live = self.yk.config()
            except YkRestError as e:
                live = f"# live fetch failed: {e}\n"
        u, live_d = self.store.diff_configs(include_live=live)
        return scheduler_pb2.DiffConfigResponse(unified_diff=u, live_diff=live_d)

    def PromoteScratch(self, request, context):  # noqa: N802
        scratch = self.store.read_config("scratch")
        if not scratch:
            return scheduler_pb2.PromoteScratchResponse(
                ok=False, message="no scratch config", applied=False
            )
        # Always apply declared-shape normalization before validate/apply so
        # scratch seeded from live GET (with checksum/extra/…) still promotes.
        scratch = normalize_declared_config(scratch)
        try:
            ok, msg = self.yk.validate_conf(scratch)
        except YkRestError as e:
            return scheduler_pb2.PromoteScratchResponse(
                ok=False,
                message=str(e),
                applied=False,
                validation=scheduler_pb2.ValidateConfigResponse(
                    ok=False, message=str(e), errors=[str(e)]
                ),
            )
        validation = scheduler_pb2.ValidateConfigResponse(
            ok=ok, message=msg, errors=[] if ok else [msg]
        )
        if not ok:
            return scheduler_pb2.PromoteScratchResponse(
                ok=False, message="validation failed", applied=False, validation=validation
            )

        # dry_run: validate + optional server-side kubectl dry-run; no projection write
        if request.dry_run:
            apply_msg = "apply skipped (dry_run)"
            if self.apply_cfg.enabled:
                try:
                    ar = apply_queues_yaml(
                        scratch, self.apply_cfg, dry_run=True
                    )
                    apply_msg = ar.message
                except ApplyError as e:
                    return scheduler_pb2.PromoteScratchResponse(
                        ok=False,
                        message=f"dry_run apply plan failed: {e}",
                        applied=False,
                        validation=validation,
                    )
            return scheduler_pb2.PromoteScratchResponse(
                ok=True,
                message=f"dry_run: validation ok; {apply_msg}",
                applied=False,
                validation=validation,
            )

        # Live promote: ConfigMap apply → archive current → write current → sync
        applied = False
        apply_msg = "apply disabled; local projection only"
        try:
            if self.apply_cfg.enabled:
                ar = apply_queues_yaml(scratch, self.apply_cfg, dry_run=False)
                applied = ar.ok
                apply_msg = ar.message
            archive_id = self.store.archive_current(request.archive_stamp or None)
            self.store.write_config(scratch, root="current")
            try:
                tree = self.yk.queue_tree("default")
                self.store.sync_current(
                    declared_yaml=scratch, queue_tree=tree, partition="default"
                )
            except YkRestError as e:
                log.warning("post-promote sync: %s", e)
            return scheduler_pb2.PromoteScratchResponse(
                ok=True,
                message=f"promoted scratch → current; {apply_msg}",
                archive_id=archive_id,
                applied=applied,
                validation=validation,
            )
        except ApplyError as e:
            return scheduler_pb2.PromoteScratchResponse(
                ok=False,
                message=f"ConfigMap apply failed (projection unchanged): {e}",
                applied=False,
                validation=validation,
            )
        except Exception as e:  # noqa: BLE001
            return scheduler_pb2.PromoteScratchResponse(
                ok=False, message=str(e), applied=False, validation=validation
            )

    def ListArchives(self, request, context):  # noqa: N802
        out = scheduler_pb2.ListArchivesResponse()
        for a in self.store.list_archives():
            out.archives.append(
                scheduler_pb2.ArchiveInfo(
                    id=a["id"], created_at=a.get("created_at", ""), note=a.get("note", "")
                )
            )
        return out

    def RequestQueueShare(self, request, context):  # noqa: N802
        """Persist WRK occupancy intent; apply merged floors via PromoteScratch."""
        try:
            return self.shares.ingest(
                request,
                apply_fn=self._share_apply_fn,
                read_yaml=self._share_read_yaml,
                write_scratch=self._share_write_scratch,
            )
        except SharePersistError as e:
            context.abort(grpc.StatusCode.INTERNAL, str(e))
            return scheduler_pb2.QueueShareResponse(
                accepted=False,
                error=str(e),
            )

    def ListQueueShareRequests(self, request, context):  # noqa: N802
        rows = self.shares.list(
            peer=request.peer or "",
            queue=request.queue or "",
            since_ns=int(request.since_ns or 0),
            limit=int(request.limit or 0) or 100,
        )
        out = scheduler_pb2.ListQueueShareRequestsResponse()
        for rec in rows:
            item = scheduler_pb2.QueueShareRecord(
                request=rec.request,
                recorded_at_ns=rec.recorded_at_ns,
                state=_share_state(rec.state),
                applied_at_ns=int(getattr(rec, "applied_at_ns", 0) or 0),
                apply_ms=int(getattr(rec, "apply_ms", 0) or 0),
                apply_error=str(getattr(rec, "apply_error", "") or ""),
            )
            out.records.append(item)
        return out

    def RestoreArchiveToScratch(self, request, context):  # noqa: N802
        try:
            self.store.restore_archive_to_scratch(request.archive_id)
            return scheduler_pb2.RestoreArchiveToScratchResponse(
                ok=True, message=f"restored {request.archive_id} → scratch"
            )
        except FileNotFoundError:
            return scheduler_pb2.RestoreArchiveToScratchResponse(
                ok=False, message="archive not found"
            )
        except Exception as e:  # noqa: BLE001
            return scheduler_pb2.RestoreArchiveToScratchResponse(ok=False, message=str(e))

    # ── Coordination Activities (intent with a lifetime; Airflow runs) ──────
    # Refusals (unknown peer, bad horizon, ended activity) come back in-band as
    # accepted=false + guru error; Airflow unavailability aborts UNAVAILABLE
    # with the guru text (fail-fast — never a locally invented activity).

    def DeclareActivity(self, request, context):  # noqa: N802
        try:
            rec = self.activities().declare(request)
            return scheduler_pb2.ActivityResponse(accepted=True, activity=rec.to_proto())
        except ActivityError as e:
            log.warning("DeclareActivity refused peer=%s kind=%s: %s", request.peer, request.kind, e)
            return scheduler_pb2.ActivityResponse(accepted=False, error=str(e))
        except AirflowError as e:
            log.error("DeclareActivity airflow: %s", e)
            context.abort(grpc.StatusCode.UNAVAILABLE, str(e))
            return scheduler_pb2.ActivityResponse(accepted=False, error=str(e))

    def RenewActivity(self, request, context):  # noqa: N802
        try:
            rec = self.activities().renew(request.peer, request.activity_id, int(request.horizon_ns))
            return scheduler_pb2.ActivityResponse(accepted=True, activity=rec.to_proto())
        except ActivityError as e:
            log.warning("RenewActivity refused %s: %s", request.activity_id, e)
            return scheduler_pb2.ActivityResponse(accepted=False, error=str(e))
        except AirflowError as e:
            log.error("RenewActivity airflow: %s", e)
            context.abort(grpc.StatusCode.UNAVAILABLE, str(e))
            return scheduler_pb2.ActivityResponse(accepted=False, error=str(e))

    def ReleaseActivity(self, request, context):  # noqa: N802
        try:
            rec = self.activities().release(request.peer, request.activity_id, request.outcome)
            return scheduler_pb2.ActivityResponse(accepted=True, activity=rec.to_proto())
        except ActivityError as e:
            log.warning("ReleaseActivity refused %s: %s", request.activity_id, e)
            return scheduler_pb2.ActivityResponse(accepted=False, error=str(e))
        except AirflowError as e:
            log.error("ReleaseActivity airflow: %s", e)
            context.abort(grpc.StatusCode.UNAVAILABLE, str(e))
            return scheduler_pb2.ActivityResponse(accepted=False, error=str(e))

    def ListActivities(self, request, context):  # noqa: N802
        try:
            recs = self.activities().list(
                peer=request.peer or "",
                kind=request.kind or "",
                active_only=bool(request.active_only),
                since_ns=int(request.since_ns or 0),
                limit=int(request.limit or 0),
            )
        except AirflowError as e:
            log.error("ListActivities airflow: %s", e)
            context.abort(grpc.StatusCode.UNAVAILABLE, str(e))
            return scheduler_pb2.ListActivitiesResponse()
        out = scheduler_pb2.ListActivitiesResponse(observed_ns=self.activities()._clock())
        for r in recs:
            out.activities.append(r.to_proto())
        return out

    def WatchActivities(self, request, context):  # noqa: N802
        """Server stream: the full in-force set (+ recently ended) on change and
        every heartbeat; ends when the peer disconnects or Airflow fails."""
        peer = request.peer or "?"
        log.info("WatchActivities: peer=%s subscribed", peer)
        try:
            for recs, observed in self.activities().watch(is_active=context.is_active):
                yield watch_event(recs, observed)
        except AirflowError as e:
            log.error("WatchActivities peer=%s airflow: %s", peer, e)
            context.abort(grpc.StatusCode.UNAVAILABLE, str(e))
        finally:
            log.info("WatchActivities: peer=%s stream closed", peer)


def _root_name(enum_val: int) -> str:
    return {
        scheduler_pb2.CURRENT: "current",
        scheduler_pb2.SCRATCH: "scratch",
        scheduler_pb2.ARCHIVE: "archive",
    }.get(enum_val, "current")


def _root_enum(name: str) -> int:
    return {
        "current": scheduler_pb2.CURRENT,
        "scratch": scheduler_pb2.SCRATCH,
        "archive": scheduler_pb2.ARCHIVE,
    }.get(name, scheduler_pb2.CURRENT)
