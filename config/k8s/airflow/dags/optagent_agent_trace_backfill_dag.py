# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0
"""Airflow execution of the agent-trace enrichment on Kubernetes.

The scheduler is the platform Airflow (LocalExecutor on RKE2). The task is a
KubernetesPodOperator in the metaflow namespace. The pod uses the host network
so Aegir's SDG aperture can reach Qdrant on localhost, and host mounts so the
lab Python, snapshot, and NVIDIA devices are the ones on this machine. A
scheduled day does not re-admit the snapshot. A manual run with conf
``full=true`` admits every readable agent passage, classifies it with
TypeSafe, and publishes the next snapshot version.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s

DAG_ID = "optagent_agent_trace_backfill"
HOST_SCRIPT = "/home/rch/local/src/zndx/optagent/scripts/airflow/enrich_snapshot_host.sh"


# conf.full selects the enrichment. A scheduled tick does not re-admit.
_BODY = (
    "{{ 'bash "
    + HOST_SCRIPT
    + "' if (dag_run.conf or {}).get('full') else 'echo optagent daily tick skips full enrichment' }}"
)


def _host_mount(name: str, path: str, *, ro: bool = False) -> tuple[k8s.V1Volume, k8s.V1VolumeMount]:
    volume = k8s.V1Volume(
        name=name,
        host_path=k8s.V1HostPathVolumeSource(path=path, type="Directory"),
    )
    mount = k8s.V1VolumeMount(name=name, mount_path=path, read_only=ro)
    return volume, mount


_MOUNTS = [
    _host_mount("nix", "/nix/store", ro=True),
    _host_mount("home", "/home/rch"),
    _host_mount("raid", "/raid/build/optagent"),
]
for _device in (
    "nvidia0",
    "nvidia1",
    "nvidia2",
    "nvidia3",
    "nvidia4",
    "nvidia5",
    "nvidiactl",
    "nvidia-modeset",
    "nvidia-uvm",
    "nvidia-uvm-tools",
):
    _path = f"/dev/{_device}"
    _MOUNTS.append(
        (
            k8s.V1Volume(name=_device.replace("-", ""), host_path=k8s.V1HostPathVolumeSource(path=_path, type="CharDevice")),
            k8s.V1VolumeMount(name=_device.replace("-", ""), mount_path=_path),
        )
    )


with DAG(
    dag_id=DAG_ID,
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 0, "execution_timeout": timedelta(hours=18)},
    params={"full": False},
    tags=["optagent", "backfill", "kubernetes"],
) as dag:
    KubernetesPodOperator(
        task_id="enrich_snapshot",
        name="optagent-trace-enrich",
        namespace="metaflow",
        service_account_name="metaflow-task",
        image="apache/airflow:3.1.7",
        image_pull_policy="IfNotPresent",
        cmds=["bash", "-lc", _BODY],
        hostnetwork=True,
        dnspolicy="ClusterFirstWithHostNet",
        get_logs=True,
        log_events_on_failure=True,
        in_cluster=True,
        startup_timeout_seconds=600,
        annotations={
            "yunikorn.apache.org/app-id": "optagent-trace-enrich",
            "yunikorn.apache.org/queue": "root.platform",
            "zarf.dev/agent": "ignore",
        },
        security_context=k8s.V1PodSecurityContext(run_as_user=0),
        volumes=[item[0] for item in _MOUNTS],
        volume_mounts=[item[1] for item in _MOUNTS],
        on_finish_action="delete_pod",
    )
