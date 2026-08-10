# Marquez (UI only)

Submodule: `components/marquez` → `git@github.com:zndx/oss-marquez.git` (`main`).

## Role

| Deployed | Not deployed |
|----------|--------------|
| **Marquez-web** (default `devenv` process) | Stock Marquez API |
| Proxy `/api/v1` → Atlas OpenLineage surface | Marquez Postgres / Flyway schema |

Signals is the system of record. Marquez is the **OpenLineage reference UI** and
a source of **API contract tests**. Doctrine:
[OpenLineage + Atlas](../architecture/openlineage-atlas.md).

## Port convention

**Marquez UI port = Atlas HTTP port + 1.**

| Service | Default port | Env override |
|---------|--------------|--------------|
| Atlas | **21010** | `SIGNALS_ATLAS_HTTP_PORT` (process uses fixed `-port 21010` today; keep in sync) |
| Marquez-web | **21011** | `MARQUEZ_WEB_PORT` (default `ATLAS + 1`) |
| OL proxy target | Atlas host/port | `SIGNALS_OL_API_HOST` / `SIGNALS_OL_API_PORT` |

`:3000` is reserved for ad-hoc local frontend dev (Vite/CRA, Atelier, etc.) and
must not be the lab Marquez bind.

LAN example (this project’s Atlas on the node IP):

- Atlas: `http://192.168.1.55:21010`
- Marquez UI: `http://192.168.1.55:21011` → proxies `/api/v1` → Atlas

## Ops

```bash
devenv tasks run marquez:build-web   # also before devenv up
# UI → Atlas OL
# http://localhost:21011  (or http://<node>:21011)
# proxies to SIGNALS_OL_API_HOST:PORT (default 127.0.0.1:21010)
```
