# Marquez

Submodule: `components/marquez` → `git@github.com:zndx/oss-marquez.git` (`main`).

Marquez-web is the OpenLineage UI. It proxies `/api/v1` and
`/api/v2beta` to Atlas. Lineage events, jobs, datasets, and graphs
live in AGE on the Signals Postgres. Architecture:
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
- Marquez UI: `http://192.168.1.55:21011` → proxies `/api/v1` + `/api/v2beta` → Atlas

## Ops

```bash
devenv tasks run marquez:build-web   # also before devenv up
# UI → Atlas OL
# http://localhost:21011  (or http://<node>:21011)
# proxies to SIGNALS_OL_API_HOST:PORT (default 127.0.0.1:21010)
```

## Acceptance (API completeness)

Marquez-web boot and navigation must not hit 404s on the Marquez API surface.
Minimum probe against Atlas (not Marquez API):

```bash
for p in health tags jobs namespaces events/lineage stats/lineage-events search?q=test; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:21010/api/v1/$p")
  echo "$code  /api/v1/$p"
done
curl -sS -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:21010/api/v2beta/search/jobs?q=test'
```

Expect **200** (empty collections are fine). After seeding RunEvents via
`POST /api/v1/lineage`, the UI jobs/datasets/events/lineage views should show
content.
