# Marquez (UI only)

Submodule: `components/marquez` → `git@github.com:zndx/oss-marquez.git` (`main`).

## Role

| Deployed | Not deployed |
|----------|--------------|
| **Marquez-web** (default `devenv` process, `:3000`) | Stock Marquez API |
| Proxy `/api/v1` → Atlas OpenLineage surface | Marquez Postgres / Flyway schema |

Signals is the system of record. Marquez is the **OpenLineage reference UI** and
a source of **API contract tests**. Doctrine:
[OpenLineage + Atlas](../architecture/openlineage-atlas.md).

## Ops

```bash
devenv tasks run marquez:build-web   # also before devenv up
# UI → Atlas OL
# http://localhost:3000  proxies to SIGNALS_OL_API_HOST:PORT (default 127.0.0.1:21010)
```
