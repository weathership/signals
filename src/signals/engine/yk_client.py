"""Private YuniKorn REST client (engine-only; thin clients never import this)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests
import yaml

log = logging.getLogger("signals.engine.yk_client")

# Keys accepted in declared queues.yaml for validate-conf / ConfigMap.
# Live GET /ws/v1/config often includes runtime-only fields that fail unmarshal.
_DECLARED_TOP_LEVEL = frozenset({"partitions"})


def normalize_declared_config(yaml_body: str) -> str:
    """Reduce a live or mixed config document to declared policy YAML.

    Drops runtime fields (checksum, extra, deadlock*, …) that
    ``POST /ws/v1/validate-conf`` rejects. If the body is not YAML or has no
    ``partitions``, returns the original string unchanged.
    """
    if not yaml_body or not yaml_body.strip():
        return yaml_body
    try:
        data = yaml.safe_load(yaml_body)
    except yaml.YAMLError:
        return yaml_body
    if not isinstance(data, dict):
        return yaml_body
    if "partitions" not in data:
        return yaml_body
    cleaned = {k: data[k] for k in data if k in _DECLARED_TOP_LEVEL}
    # Prefer stable, readable dump
    out = yaml.safe_dump(
        cleaned,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return out if out.endswith("\n") else out + "\n"


class YkRestError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class YkRestClient:
    def __init__(self, base_url: str, timeout_s: float = 15.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout_s
        self._session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    def get_json(self, path: str) -> Any:
        url = self._url(path)
        try:
            r = self._session.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            raise YkRestError(f"YK GET {path}: {e}") from e
        if r.status_code >= 400:
            raise YkRestError(
                f"YK GET {path} → HTTP {r.status_code}: {r.text[:300]}",
                status_code=r.status_code,
            )
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    def get_text(self, path: str) -> str:
        url = self._url(path)
        try:
            r = self._session.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            raise YkRestError(f"YK GET {path}: {e}") from e
        if r.status_code >= 400:
            raise YkRestError(
                f"YK GET {path} → HTTP {r.status_code}: {r.text[:300]}",
                status_code=r.status_code,
            )
        return r.text

    def post_text(self, path: str, body: str, content_type: str = "text/plain") -> tuple[int, str]:
        url = self._url(path)
        try:
            r = self._session.post(
                url,
                data=body.encode("utf-8"),
                headers={"Content-Type": content_type},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise YkRestError(f"YK POST {path}: {e}") from e
        return r.status_code, r.text

    def partitions(self) -> Any:
        return self.get_json("ws/v1/partitions")

    def queue_tree(self, partition: str = "default") -> Any:
        p = quote(partition or "default", safe="")
        return self.get_json(f"ws/v1/partition/{p}/queues")

    def queue(self, partition: str, queue: str, subtree: bool = False) -> Any:
        p = quote(partition or "default", safe="")
        q = quote(queue, safe="")
        path = f"ws/v1/partition/{p}/queue/{q}"
        if subtree:
            path += "?subtree=true"
        return self.get_json(path)

    def queue_applications(self, partition: str, queue: str) -> Any:
        p = quote(partition or "default", safe="")
        q = quote(queue, safe="")
        return self.get_json(f"ws/v1/partition/{p}/queue/{q}/applications")

    def nodes(self, partition: str = "default") -> Any:
        p = quote(partition or "default", safe="")
        return self.get_json(f"ws/v1/partition/{p}/nodes")

    def placement_rules(self, partition: str = "default") -> Any:
        p = quote(partition or "default", safe="")
        return self.get_json(f"ws/v1/partition/{p}/placementrules")

    def config(self) -> str:
        # May be YAML text or JSON depending on version; preserve body.
        text = self.get_text("ws/v1/config")
        raw = text if isinstance(text, str) else str(text)
        # Live GET often appends runtime-only keys (checksum, extra, deadlock*)
        # that validate-conf rejects — strip to declared partitions document.
        return normalize_declared_config(raw)

    def validate_conf(self, yaml_body: str) -> tuple[bool, str]:
        yaml_body = normalize_declared_config(yaml_body)
        code, text = self.post_text("ws/v1/validate-conf", yaml_body, "application/yaml")
        # 200 with empty/ok body, or JSON with reason
        if code == 200:
            if not text or "true" in text.lower() or text.strip() in ("{}", "null"):
                return True, text or "ok"
            # Some builds return JSON { "allowed": true }
            try:
                import json

                j = json.loads(text)
                if isinstance(j, dict):
                    allowed = j.get("allowed", j.get("ok", True))
                    return bool(allowed), text
            except ValueError:
                pass
            return True, text
        return False, f"HTTP {code}: {text[:500]}"

    def healthcheck(self) -> Any:
        return self.get_json("ws/v1/scheduler/healthcheck")

    def clusters(self) -> Any:
        return self.get_json("ws/v1/clusters")

    def history_apps(self) -> Any:
        return self.get_json("ws/v1/history/apps")

    def history_containers(self) -> Any:
        return self.get_json("ws/v1/history/containers")

    def node_utilizations(self) -> Any:
        return self.get_json("ws/v1/scheduler/node-utilizations")
