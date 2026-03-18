"""Atlas REST client for classification CRUD."""

from __future__ import annotations

import requests

from sigint.config import TaggingConfig
from sigint.ontology import atlas_classification_defs


class AtlasClient:
    """Thin wrapper around the Atlas v2 REST API for classification operations."""

    def __init__(self, cfg: TaggingConfig) -> None:
        self._base = cfg.atlas_url.rstrip("/")
        self._auth = (cfg.atlas_user, cfg.atlas_password)
        self._cluster = cfg.cluster_name
        self._timeout = 60

    def _api(self, path: str, method: str = "GET", **kwargs) -> requests.Response:
        url = f"{self._base}/api/atlas/v2{path}"
        return requests.request(
            method, url, auth=self._auth, timeout=self._timeout, **kwargs
        )

    # ── Type management ───────────────────────────────────────────────

    def ensure_classification_types(self) -> dict:
        """Create SIGDG classification types that don't already exist.

        Returns dict with 'created' and 'existing' counts.
        """
        defs = atlas_classification_defs()
        to_create = []
        existing = 0

        for d in defs:
            resp = self._api(f"/types/classificationdef/name/{d['name']}")
            if resp.status_code == 200:
                existing += 1
            else:
                to_create.append(d)

        created = 0
        if to_create:
            body = {"classificationDefs": to_create}
            resp = self._api("/types/typedefs", method="POST", json=body)
            resp.raise_for_status()
            created = len(to_create)

        return {"created": created, "existing": existing}

    # ── Entity lookup ─────────────────────────────────────────────────

    def find_entity_guid(self, type_name: str, qualified_name: str) -> str | None:
        """Look up an entity GUID by type and qualifiedName."""
        resp = self._api(
            f"/entity/uniqueAttribute/type/{type_name}",
            params={"attr:qualifiedName": qualified_name},
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("entity", {}).get("guid")

    def find_column_guid(self, table_fqn: str, column_name: str) -> str | None:
        """Find the GUID for a hive_column entity."""
        qn = f"{table_fqn}.{column_name}@{self._cluster}"
        return self.find_entity_guid("hive_column", qn)

    def find_table_guid(self, table_fqn: str) -> str | None:
        """Find the GUID for a hive_table entity."""
        qn = f"{table_fqn}@{self._cluster}"
        return self.find_entity_guid("hive_table", qn)

    # ── Classification CRUD ───────────────────────────────────────────

    def apply_classification(
        self,
        entity_guid: str,
        classification_name: str,
        confidence: float | None = None,
        evidence: str | None = None,
    ) -> bool:
        """Apply a classification to an entity. Returns True on success."""
        attrs = {}
        if confidence is not None:
            attrs["confidence"] = confidence
        if evidence is not None:
            attrs["evidence"] = evidence

        body = [{"typeName": classification_name, "attributes": attrs}]
        resp = self._api(
            f"/entity/guid/{entity_guid}/classifications",
            method="POST",
            json=body,
        )

        if resp.status_code in (200, 204):
            return True
        # Idempotent: already applied
        if resp.status_code == 400 and "already associated" in resp.text:
            # Update the existing classification attributes
            update_body = {"typeName": classification_name, "attributes": attrs}
            resp = self._api(
                f"/entity/guid/{entity_guid}/classifications",
                method="PUT",
                json=[update_body],
            )
            return resp.status_code in (200, 204)
        return False

    def register_table(
        self,
        db_name: str,
        table_name: str,
        columns: list[tuple[str, str]],
    ) -> dict:
        """Register a table and its columns in Atlas via bulk entity create.

        Args:
            db_name: Database name.
            table_name: Table name.
            columns: List of (column_name, column_type) tuples.

        Returns:
            Dict with table_guid, db_guid, and column_guids mapping.
        """
        table_fqn = f"{db_name}.{table_name}"
        db_qn = f"{db_name}@{self._cluster}"
        tbl_qn = f"{table_fqn}@{self._cluster}"

        col_entities = []
        col_guid_map = {}
        for i, (col_name, col_type) in enumerate(columns):
            temp_guid = f"-{10 + i}"
            col_qn = f"{table_fqn}.{col_name}@{self._cluster}"
            col_guid_map[col_name] = temp_guid
            col_entities.append({
                "typeName": "hive_column",
                "guid": temp_guid,
                "attributes": {
                    "qualifiedName": col_qn,
                    "name": col_name,
                    "type": col_type,
                    "owner": "admin",
                    "table": {"guid": "-1", "typeName": "hive_table"},
                    "position": i,
                },
            })

        body = {
            "referredEntities": {
                "-100": {
                    "typeName": "hive_db",
                    "guid": "-100",
                    "attributes": {
                        "qualifiedName": db_qn,
                        "name": db_name,
                        "clusterName": self._cluster,
                        "owner": "admin",
                    },
                },
            },
            "entities": [{
                "typeName": "hive_table",
                "guid": "-1",
                "attributes": {
                    "qualifiedName": tbl_qn,
                    "name": table_name,
                    "owner": "admin",
                    "tableType": "EXTERNAL_TABLE",
                    "db": {"guid": "-100", "typeName": "hive_db"},
                    "columns": [
                        {"guid": ce["guid"], "typeName": "hive_column"}
                        for ce in col_entities
                    ],
                },
            }],
        }
        for ce in col_entities:
            body["referredEntities"][ce["guid"]] = ce

        resp = self._api("/entity/bulk", method="POST", json=body)
        resp.raise_for_status()
        data = resp.json()

        guid_assignments = data.get("guidAssignments", {})
        result = {
            "table_guid": guid_assignments.get("-1"),
            "db_guid": guid_assignments.get("-100"),
            "column_guids": {},
        }

        if not result["table_guid"]:
            mutated = data.get("mutatedEntities", {})
            for action_entities in mutated.values():
                for ent in action_entities:
                    if ent.get("typeName") == "hive_table":
                        result["table_guid"] = ent.get("guid")
                    elif ent.get("typeName") == "hive_db":
                        result["db_guid"] = ent.get("guid")

        for col_name, temp_guid in col_guid_map.items():
            real_guid = guid_assignments.get(temp_guid)
            if real_guid:
                result["column_guids"][col_name] = real_guid

        return result

    def get_entity_classifications(self, entity_guid: str) -> list[str]:
        """Return classification type names on an entity."""
        resp = self._api(f"/entity/guid/{entity_guid}")
        if resp.status_code != 200:
            return []
        entity = resp.json().get("entity", {})
        return [c.get("typeName", "") for c in entity.get("classifications", [])]
