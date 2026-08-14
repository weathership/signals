"""archive / current / scratch projection store (Aegir-shaped)."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("signals.engine.projection")

ROOTS = ("current", "scratch", "archive")


@dataclass
class NoteMeta:
    id: str
    title: str
    kind: str
    root: str
    relpath: str
    links: list[str]


class ProjectionStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # current + scratch hold config/ + queues/; archive is stamp dirs only
        for r in ("current", "scratch"):
            (self.root / r).mkdir(parents=True, exist_ok=True)
            (self.root / r / "config").mkdir(parents=True, exist_ok=True)
            (self.root / r / "queues").mkdir(parents=True, exist_ok=True)
        (self.root / "archive").mkdir(parents=True, exist_ok=True)

    def config_path(self, root: str = "current") -> Path:
        return self.root / root / "config" / "queues.yaml"

    def read_config(self, root: str = "current") -> str | None:
        p = self.config_path(root)
        if not p.is_file():
            return None
        return p.read_text(encoding="utf-8")

    def write_config(self, yaml_body: str, root: str = "scratch") -> Path:
        if root not in ("scratch", "current"):
            raise ValueError("write_config only for scratch/current")
        p = self.config_path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml_body, encoding="utf-8")
        if root == "scratch":
            self._write_queue_notes_from_yaml(yaml_body, root="scratch")
            self.rebuild_index()
        return p

    def sync_current(
        self,
        *,
        declared_yaml: str,
        queue_tree: Any,
        partition: str = "default",
    ) -> int:
        """Rebuild current from live declared config + queue tree. Preserves scratch/archive."""
        cur = self.root / "current"
        # clear regenerable current content
        for sub in ("config", "queues"):
            d = cur / sub
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
        self.config_path("current").write_text(declared_yaml, encoding="utf-8")
        n = self._write_queue_notes_from_tree(queue_tree, partition=partition, root="current")
        self.rebuild_index()
        return n

    def _write_queue_notes_from_yaml(self, yaml_body: str, root: str) -> int:
        try:
            data = yaml.safe_load(yaml_body) or {}
        except yaml.YAMLError as e:
            log.warning("scratch yaml parse for notes failed: %s", e)
            return 0
        count = 0
        for part in data.get("partitions") or []:
            pname = part.get("name") or "default"
            for q in part.get("queues") or []:
                count += self._emit_yaml_queue(q, prefix="", partition=pname, root=root)
        return count

    def _emit_yaml_queue(
        self, q: dict, prefix: str, partition: str, root: str
    ) -> int:
        name = q.get("name") or "?"
        fqn = f"{prefix}.{name}" if prefix else name
        if not fqn.startswith("root") and prefix == "":
            # top-level under partition often "root"
            pass
        note_id = f"queues/{partition}/{fqn.replace('.', '/')}"
        rel = f"{root}/queues/{partition}/{fqn.replace('.', '/')}.md"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        resources = q.get("resources") or {}
        body = (
            f"# {fqn}\n\n"
            f"- partition: `{partition}`\n"
            f"- parent: `{prefix or '—'}`\n"
            f"- maxapplications: `{q.get('maxapplications', '—')}`\n"
            f"- submitacl: `{q.get('submitacl', '—')}`\n"
            f"- resources: `{json.dumps(resources)}`\n"
        )
        kids = q.get("queues") or []
        links = [f"queues/{partition}/{(fqn + '.' + c.get('name', '?')).replace('.', '/')}" for c in kids]
        fm = {
            "id": note_id,
            "title": fqn,
            "kind": "queue-policy",
            "root": root,
            "partition": partition,
            "links": links,
        }
        path.write_text(
            "---\n"
            + yaml.safe_dump(fm, default_flow_style=False)
            + "---\n\n"
            + body,
            encoding="utf-8",
        )
        n = 1
        for c in kids:
            n += self._emit_yaml_queue(c, prefix=fqn, partition=partition, root=root)
        return n

    def _write_queue_notes_from_tree(
        self, tree: Any, partition: str, root: str
    ) -> int:
        """Live REST tree may be a single root object or a list."""
        if tree is None:
            return 0
        if isinstance(tree, list):
            if not tree:
                return 0
            node = tree[0]
        else:
            node = tree
        return self._emit_live_queue(node, partition=partition, root=root)

    def _emit_live_queue(self, node: dict, partition: str, root: str) -> int:
        fqn = node.get("queuename") or node.get("queueName") or "root"
        note_id = f"queues/{partition}/{fqn.replace('.', '/')}"
        rel = f"{root}/queues/{partition}/{fqn.replace('.', '/')}.md"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        status = node.get("status", "—")
        alloc = node.get("allocatedResource") or node.get("allocated") or {}
        mx = node.get("maxResource") or node.get("max") or {}
        kids = node.get("children") or node.get("queues") or []
        if not isinstance(kids, list):
            kids = []
        links = []
        for c in kids:
            if isinstance(c, dict):
                cn = c.get("queuename") or c.get("queueName") or "?"
                links.append(f"queues/{partition}/{cn.replace('.', '/')}")
        body = (
            f"# {fqn}\n\n"
            f"**Status:** {status}\n\n"
            f"## Runtime (live)\n\n"
            f"- allocated: `{json.dumps(alloc)}`\n"
            f"- max: `{json.dumps(mx)}`\n"
            f"- runningApps: `{node.get('runningApps', node.get('RunningApps', 0))}`\n"
            f"- isLeaf: `{node.get('isLeaf', node.get('isleaf', False))}`\n\n"
            f"## Children\n\n"
        )
        for link in links:
            short = link.rsplit("/", 1)[-1]
            body += f"- [[{link}|{short}]]\n"
        if not links:
            body += "_none_\n"
        fm = {
            "id": note_id,
            "title": fqn,
            "kind": "queue-live",
            "root": root,
            "partition": partition,
            "status": status,
            "links": links,
        }
        path.write_text(
            "---\n"
            + yaml.safe_dump(fm, default_flow_style=False)
            + "---\n\n"
            + body,
            encoding="utf-8",
        )
        n = 1
        for c in kids:
            if isinstance(c, dict):
                n += self._emit_live_queue(c, partition=partition, root=root)
        return n

    def rebuild_index(self) -> Path:
        notes: list[dict[str, Any]] = []
        for root_name in ("current", "scratch"):
            base = self.root / root_name
            if not base.is_dir():
                continue
            for md in base.rglob("*.md"):
                meta = self._parse_frontmatter(md, root_name)
                if meta:
                    notes.append(meta)
        # archive: one level of stamp dirs
        arch = self.root / "archive"
        if arch.is_dir():
            for stamp_dir in sorted(arch.iterdir()):
                if not stamp_dir.is_dir():
                    continue
                for md in stamp_dir.rglob("*.md"):
                    meta = self._parse_frontmatter(md, "archive", archive_id=stamp_dir.name)
                    if meta:
                        notes.append(meta)
        idx = {
            "counts": {
                "total": len(notes),
                "by_root": {
                    r: sum(1 for n in notes if n.get("root") == r) for r in ROOTS
                },
            },
            "notes": notes,
        }
        path = self.root / "index.json"
        path.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")
        return path

    def _parse_frontmatter(
        self, path: Path, root: str, archive_id: str | None = None
    ) -> dict[str, Any] | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        if not text.startswith("---"):
            rel = str(path.relative_to(self.root))
            return {
                "id": path.stem,
                "title": path.stem,
                "kind": "note",
                "root": root,
                "relpath": rel,
                "links": [],
                **({"archive_id": archive_id} if archive_id else {}),
            }
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None
        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            fm = {}
        rel = str(path.relative_to(self.root))
        out = {
            "id": fm.get("id") or path.stem,
            "title": fm.get("title") or path.stem,
            "kind": fm.get("kind") or "note",
            "root": root,
            "relpath": rel,
            "links": fm.get("links") or [],
        }
        if archive_id:
            out["archive_id"] = archive_id
        return out

    def list_notes(self, root: str, archive_id: str | None = None) -> list[NoteMeta]:
        idx_path = self.root / "index.json"
        if not idx_path.is_file():
            self.rebuild_index()
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        out: list[NoteMeta] = []
        for n in data.get("notes") or []:
            if n.get("root") != root:
                continue
            if root == "archive" and archive_id and n.get("archive_id") != archive_id:
                continue
            out.append(
                NoteMeta(
                    id=n["id"],
                    title=n.get("title") or n["id"],
                    kind=n.get("kind") or "note",
                    root=n.get("root") or root,
                    relpath=n.get("relpath") or "",
                    links=list(n.get("links") or []),
                )
            )
        return out

    def get_note(
        self, root: str, note_id: str, archive_id: str | None = None
    ) -> tuple[dict[str, Any], str] | None:
        """Return (frontmatter, body) or None."""
        # resolve via index
        for n in self.list_notes(root, archive_id=archive_id):
            if n.id == note_id or n.id.endswith("/" + note_id):
                path = self.root / n.relpath
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8")
                if text.startswith("---"):
                    parts = text.split("---", 2)
                    fm = yaml.safe_load(parts[1]) or {}
                    body = parts[2].lstrip("\n") if len(parts) > 2 else ""
                    return fm, body
                return {"id": note_id, "title": note_id}, text
        return None

    def diff_configs(self, include_live: str | None = None) -> tuple[str, str]:
        import difflib

        scratch = self.read_config("scratch") or ""
        current = self.read_config("current") or ""
        u1 = difflib.unified_diff(
            current.splitlines(keepends=True),
            scratch.splitlines(keepends=True),
            fromfile="current/config/queues.yaml",
            tofile="scratch/config/queues.yaml",
        )
        live_diff = ""
        if include_live is not None:
            u2 = difflib.unified_diff(
                (include_live or "").splitlines(keepends=True),
                current.splitlines(keepends=True),
                fromfile="live/ws/v1/config",
                tofile="current/config/queues.yaml",
            )
            live_diff = "".join(u2)
        return "".join(u1), live_diff

    def archive_current(self, stamp: str | None = None) -> str:
        stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = self.root / "archive" / stamp
        if dest.exists():
            shutil.rmtree(dest)
        src = self.root / "current"
        if src.exists():
            shutil.copytree(src, dest)
        else:
            dest.mkdir(parents=True)
        self.rebuild_index()
        return stamp

    def list_archives(self) -> list[dict[str, str]]:
        arch = self.root / "archive"
        if not arch.is_dir():
            return []
        out = []
        for d in sorted(arch.iterdir(), reverse=True):
            # stamp dirs only (skip accidental scaffold config/queues leftovers)
            if not d.is_dir() or d.name in ("config", "queues"):
                continue
            out.append({"id": d.name, "created_at": d.name, "note": ""})
        return out

    def restore_archive_to_scratch(self, archive_id: str) -> None:
        src = self.root / "archive" / archive_id
        if not src.is_dir():
            raise FileNotFoundError(archive_id)
        dest = self.root / "scratch"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        self.rebuild_index()
