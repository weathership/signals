"""Server-to-server query helpers (signals-protocol Engine/ServerQuery).

Pairwise snapshot — not gossip. Do not invent remotes, peers, or peer UI URLs.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from signals.engine.generated.zndx.engine.v1 import engine_pb2

CONTRACT = Path("config/platform/peer-contract.json")
LATTICE_SKIP = frozenset(
    {"service", "proto", "server_reflection", "first_party_clients"}
)
_LOOPBACK = frozenset(
    {"", "localhost", "127.0.0.1", "0.0.0.0", "::1", "::", "[::1]", "[::]"}
)


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().strip("[]")
    if not h:
        return True
    if h.lower() in _LOOPBACK or h.startswith("127."):
        return True
    return False


def advertise_host() -> str:
    """LAN hostname or IP. Never loopback — empty is honest."""
    for key in (
        "SIGNALS_ADVERTISE_HOST",
        "SIGNALS_LATTICE_HOST",
        "SIGNALS_UI_PUBLIC_HOST",
        "SIGNALS_KRB_HOST",
    ):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        host = raw.split("/")[-1].split(":")[0].strip("[]")
        if host and not is_loopback_host(host):
            return host
    try:
        fqdn = (socket.getfqdn() or "").strip()
        if fqdn and not is_loopback_host(fqdn) and "." in fqdn:
            return fqdn
        hn = (socket.gethostname() or "").strip()
        if hn and not is_loopback_host(hn):
            return hn
        for info in socket.getaddrinfo(hn or "localhost", None, socket.AF_INET):
            ip = info[4][0]
            if ip and not is_loopback_host(ip):
                return ip
    except OSError:
        pass
    return ""


def rewrite_public_url(url: str) -> str:
    """Replace a loopback URL host with advertise_host(). Non-loopback unchanged."""
    host = advertise_host()
    if not url or not host:
        return url
    parsed = urlparse(url)
    if not parsed.hostname or not is_loopback_host(parsed.hostname):
        return url
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunparse(
        (parsed.scheme or "http", netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def repo_root() -> Path:
    raw = (
        os.environ.get("SIGNALS_REPO_ROOT")
        or os.environ.get("DEVENV_ROOT")
        or ""
    ).strip()
    if raw:
        return Path(raw)
    here = Path.cwd()
    for cand in (here, *here.parents):
        if (cand / ".git").exists() and (cand / "components" / "signals-protocol").exists():
            return cand
    return here


def list_named_remotes(root: Path | None = None) -> list[tuple[str, str]]:
    """Unique (name, fetch_url) from `git remote -v`. Do not invent remotes."""
    checkout = root or repo_root()
    try:
        proc = subprocess.run(
            ["git", "-C", str(checkout), "remote", "-v"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    if proc.returncode != 0:
        return []
    seen: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, url = parts[0], parts[1]
        if "(push)" in line and name in seen:
            continue
        if name not in seen:
            seen[name] = url
    return [(name, seen[name]) for name in seen]


def advertised_head(root: Path | None = None) -> str:
    checkout = root or repo_root()
    try:
        proc = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def local_primary_ui() -> str:
    """This engine's product UI as a hostname URL (S2S identity). Never loopback.

    Browser waffle links are rebased by signals-ui from the request Host when
    the client arrived on a LAN IP that cannot resolve the Zero Trust name.
    """
    raw = (os.environ.get("SIGNALS_UI_URL") or "").strip()
    if raw:
        rewritten = rewrite_public_url(raw)
        parsed = urlparse(rewritten)
        if parsed.hostname and not is_loopback_host(parsed.hostname):
            return rewritten
    host = advertise_host()
    if not host:
        return ""
    port = "9889"
    bind = (os.environ.get("SIGNALS_UI_BIND") or "").strip()
    if bind:
        maybe = bind.rsplit(":", 1)[-1]
        if maybe.isdigit():
            port = maybe
    return f"http://{host}:{port}"


def local_surfaces() -> list[engine_pb2.Surface]:
    out: list[engine_pb2.Surface] = []
    url = local_primary_ui()
    if url:
        out.append(engine_pb2.Surface(kind="primary", url=url, healthy=True))
    host = advertise_host()
    if host:
        port = (os.environ.get("SIGNALS_DCGM_OTEL_PORT") or "9410").strip()
        out.append(
            engine_pb2.Surface(
                kind="telemetry",
                url=f"http://{host}:{port}/v1/metrics",
                healthy=True,
            )
        )
    return out


def configured_peers(contract: Path | None = None) -> list[tuple[str, str]]:
    """Lattice Engine targets from peer-contract. Skip self. Empty is honest."""
    path = contract
    if path is None:
        env = (os.environ.get("SIGNALS_PEER_CONTRACT") or "").strip()
        path = Path(env) if env else repo_root() / CONTRACT
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    lattice = doc.get("engine_grpc_lattice") or {}
    host = (os.environ.get("SIGNALS_LATTICE_HOST") or advertise_host()).strip()
    if ":" in host and not host.startswith("["):
        host = host.rsplit(":", 1)[0]
    if not host or is_loopback_host(host):
        return []
    self_name = (os.environ.get("SIGNALS_ENGINE_PROJECT") or "signals").strip()
    out: list[tuple[str, str]] = []
    for name, port in lattice.items():
        if name in LATTICE_SKIP or name == self_name:
            continue
        if not isinstance(port, int):
            continue
        out.append((str(name), f"{host}:{port}"))
    return out


# PRODUCTS answers come from the warehouse (the inventory of record) and are
# briefly cached so ServerQuery fan-outs never hammer Impala; the JSON seed is
# the honest degraded answer while the warehouse is unreachable.
_PRODUCTS_CACHE: tuple[float, list] = (0.0, [])
_PRODUCTS_TTL_S = 30.0


def _product_hint(row: dict) -> engine_pb2.ProductHint:
    return engine_pb2.ProductHint(
        product_id=str(row.get("id") or row.get("product_id") or ""),
        peer=str(row.get("peer") or ""),
        title=str(row.get("title") or ""),
        kind=str(row.get("kind") or ""),
        leaf=str(row.get("leaf") or ""),
        table_identifier=str(row.get("table_identifier") or ""),
        data_uri=str(row.get("data_uri") or ""),
        flow=str(row.get("flow_name") or ""),
        step=str(row.get("step_name") or ""),
        agent_focus=str(row.get("agent_focus") or ""),
        history="details/tx/hx in signals_dataproducts (warehouse of record)",
    )


def local_products() -> list[engine_pb2.ProductHint]:
    """Every product the warehouse inventories (own + peers'), as hints.

    Signals is the warehouse of record, so its PRODUCTS answer is the full
    federated catalog — each hint carries its producing peer. Discovery only:
    the details/tx/hx views remain the inventory the agent observes.
    """
    global _PRODUCTS_CACHE
    import time as _time

    now = _time.monotonic()
    stamp, cached = _PRODUCTS_CACHE
    if cached and now - stamp < _PRODUCTS_TTL_S:
        return list(cached)
    rows: list[dict] = []
    try:
        from signals.ops.warehouse import default_warehouse

        rows = default_warehouse().list_details()
    except Exception:  # noqa: BLE001 — degraded answer below, never an abort
        rows = []
    if not rows:
        try:
            from signals.ops.history import products as seed_products

            rows = seed_products()
        except Exception:  # noqa: BLE001
            rows = []
    hints = [h for h in (_product_hint(r) for r in rows) if h.product_id]
    if hints:
        _PRODUCTS_CACHE = (now, hints)
    return hints


def local_response(
    kind: int,
    *,
    root: Path | None = None,
    contract: Path | None = None,
) -> engine_pb2.ServerQueryResponse:
    """Answer ServerQuery. Unknown kind → project only (honest empty payload)."""
    resp = engine_pb2.ServerQueryResponse(project="signals")
    if kind in (
        engine_pb2.SERVER_QUERY_KIND_UNSPECIFIED,
        engine_pb2.SERVER_QUERY_KIND_REMOTES,
    ):
        resp.remotes.extend(
            engine_pb2.GitRemote(name=n, url=u) for n, u in list_named_remotes(root)
        )
        resp.head = advertised_head(root)
    if kind == engine_pb2.SERVER_QUERY_KIND_PEERS:
        resp.peers.extend(
            engine_pb2.PeerHint(project=pid, target=tgt)
            for pid, tgt in configured_peers(contract)
        )
    if kind == engine_pb2.SERVER_QUERY_KIND_SURFACES:
        resp.surfaces.extend(local_surfaces())
    if kind == engine_pb2.SERVER_QUERY_KIND_PRODUCTS:
        resp.products.extend(local_products())
    # WORKLOADS: Signals is scheduler, not a model host — empty is honest.
    return resp
