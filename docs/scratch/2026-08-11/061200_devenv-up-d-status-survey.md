# Survey: `devenv up -d` completeness (2026-08-11)

## Scope

What **should** come up under `devenv up -d` (host process graph +
critical-plane side effects), vs what is **live on this lab host right now**.

## Intended full graph (`devenv.nix`)

Process manager: **native** (`process.manager.implementation = "native"`).

### Host processes (always defined)

| Process | `after` / tasks | Port(s) | Role |
|---------|-----------------|---------|------|
| `postgres` | (service) | 5455 | AGE, Ranger, catalog, Metaflow/Airflow DBs |
| `kdc` | manager.before: kerberos bootstrap | 8848 | Realm `DEV.VISTA.ZNDX.ORG` |
| `rustfs` | data-layout + rustfs-buckets | 9010/9011 | Object plane |
| `atlas` | after postgres | 21010 | Governance + OL SoR |
| `marquez-web` | after atlas; **task** `marquez:build-web` before | 21011 | OL UI validator → Atlas |
| `ranger-admin` | after postgres | 6080 | Authz |
| `signals-ui` | after atlas; **task** `signals:stack-ready` before | 9889 | Primary backplane (YK required) |
| `kudu-master` | kerberos + data-layout | 7051 / web 8051 | Columnar |
| `kudu-tserver` | after kudu-master | 7050 / web 8050 | |
| `impala-statestore` | Linux only (`mkIf`) | 24000 / web 25010 | |
| `impala-catalogd` | after statestore + kudu-tserver | 26000 / web 25020 | HMS-free |
| `impala-impalad` | after catalogd | HS2 21050 / web 25000 | |

### Manager hooks / tasks (not long-running processes)

| Hook | When | Purpose |
|------|------|---------|
| `process.manager.before` | once before any process | `signals_krb_bootstrap` + data layout |
| `marquez:build-web` | before marquez-web | npm + webpack dist |
| `signals:stack-ready` | before signals-ui | PG/RustFS/Atlas soft + YK+Knative auto + Metaflow auto + Airflow auto |
| `signals:federation-ready` | subset / also inline in signals-ui | YK + Knative package |
| `signals:metaflow-platform` | manual or via stack-ready | RKE2 Metaflow M1 |
| `signals:airflow-platform` | manual or via stack-ready | RKE2 Airflow 3 M2 |

### RKE2 critical plane (not devenv processes; stack-ready / federation)

| Service | Lab surface | Status target |
|---------|-------------|---------------|
| YuniKorn | REST :30080 | Required for signals-ui |
| Knative Serving | ns `knative-serving` | Required federation |
| Metaflow metadata | NodePort :30180 | Auto-bootstrap M1 |
| Airflow 3 | NodePort :30800 | Auto-bootstrap M2 (`SIGNALS_STACK_AUTO_AIRFLOW=1`) |

## Live lab snapshot (this host, ~06:10 local)

### Running under native manager (`devenv processes list`)

| Process | Ready | Notes |
|---------|-------|-------|
| postgres | yes | :5455 |
| kdc | yes | |
| rustfs | yes | :9010 |
| atlas | yes | :21010 (`/admin/status` 200; `/version` 401) |
| marquez-web | yes | :21011 healthcheck OK |
| ranger-admin | yes | :6080 → 302 |
| signals-ui | yes (2 restarts) | :9889 `/readyz` ready, yk_required |

### **Not** in current process manager set

| Process | Binaries present? | Listening? |
|---------|-------------------|------------|
| kudu-master / kudu-tserver | yes (`components/kudu/build/latest`) | **no** |
| impala-statestore / catalogd / impalad | yes (`be/build/latest`, `.devenv/impala/*`) | **no** |

Manual 3s start of `kudu-master` succeeded (timeout SIGTERM only) — binaries and
keytab are fine. The gap is **session composition**: the live native manager
only registered the governance/UI subset. Likely causes:

1. An earlier `devenv up -d <subset>` or partial recovery after process-compose
   exit (`processes.log` Aug 10 ends with “Project Completed” after kudu/impala
   task bootstrap only).
2. Native manager does not auto-heal missing graph members without a full
   `devenv processes down` + `devenv up -d`.

**Remediation (ops):**  
`devenv processes down && devenv up -d`  
(or explicitly `devenv up -d kudu-master kudu-tserver impala-statestore impala-catalogd impala-impalad` with deps).

### RKE2 critical plane (live)

| Check | Result |
|-------|--------|
| YuniKorn REST | OK |
| Knative Serving pods | Running (activator, autoscaler, controller, kourier, webhook) |
| Metaflow `/ping` | OK (`pong`) |
| Airflow `/api/v2/version` | OK (`3.1.7`) |
| `just stack-ready` / preflight (after Atlas status fix) | **critical plane OK** (0 warnings) |

## Completeness matrix for “turn-key `devenv up -d`”

| Capability | Wired in nix? | Auto on `up -d`? | Live now | Completeness |
|------------|---------------|------------------|----------|--------------|
| Postgres + AGE | yes | yes | yes | **done** |
| KDC / kerberos bootstrap | yes | before all | yes | **done** (still need `just bootstrap` once for keytabs on fresh machine) |
| RustFS | yes | yes | yes | **done** |
| Atlas | yes | yes | yes | **done** |
| Marquez-web bootstrap + process | yes | yes (task before) | yes | **done** |
| Ranger-admin | yes | yes | yes | **done** (install/setup are separate one-time tasks) |
| signals-ui + YK hard require | yes | stack-ready before | yes | **done** |
| Federation YK+Knative | scripts + stack-ready | auto if package path set | yes | **done** (package path default `/raid/signals/zarf-build/…`) |
| Metaflow M1 | scripts + stack-ready | auto | yes | **done** |
| Airflow 3 M2 | scripts + stack-ready | auto | yes | **done** |
| Kudu | yes | **should** | **no (this session)** | **gap: process graph not fully active** |
| Impala (Linux) | yes | **should** | **no (this session)** | **gap: depends on kudu healthy** |
| Knative Eventing (M3) | policy only | no | n/a | **not started** |
| Catalog-init / FDW | tasks | no | unknown | one-shot ops, not `up -d` |
| Impala/Kudu build | tasks | no | bins present | prerequisite, not runtime |

## Gaps / follow-ups (priority)

1. **Full graph enforcement** — ensure `devenv up -d` with no args always
   registers kudu+impala (repro: clean down/up; if still missing, native
   manager / process registration bug).
2. **signals-ui restarts: 2** — investigate whether stack-ready race or YK flap.
3. **Atlas preflight** — fixed to `/admin/status` (was false soft-fail on 401).
4. **PG loopback** — Metaflow hostNetwork / Airflow socat still required; optional
   later: open `listen_addresses` for pod CIDR.
5. **Airflow hard-require** — policy-critical but default soft until
   `SIGNALS_STACK_REQUIRE_AIRFLOW=1`.
6. **M3** — Knative Eventing → Airflow DAG runs.
7. **One-time lab gates** not in `up -d`: `just bootstrap`, Ranger
   build/install/setup, Kudu/Impala compile, Zarf package build path.

## Commands cheat sheet

```bash
devenv up -d
devenv processes list          # expect kudu-*, impala-*, atlas, marquez-web, rustfs, signals-ui, …
just stack-ready
just metaflow-platform         # if Metaflow missing
just airflow-platform          # if Airflow missing
just bootstrap                 # once: keytabs + kinit
devenv processes down
```

## Changes made with this survey

- `components/impala`: gitignore `lib/python/build/` (pushed `rch/signals`)
- parent: bump impala + Atlas `/admin/status` in `signals_stack_preflight.sh`
