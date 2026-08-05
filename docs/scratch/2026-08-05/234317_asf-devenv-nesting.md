# Nesting devenv with ASF submodules (Atlas / Ranger / Kudu / Impala)

**Status:** design recommendation (implementation staged; do not block in-flight builds)  
**Context:** signals-360 hosts ASF forks under `components/*` while owning platform wiring (PG, KDC, AGE Atlas, HMS-free Impala, SIGDG → Ranger). Build knowledge currently sprawls across a 1k+ line root `devenv.nix`, while **Kudu already carries a full nested devenv** (`components/kudu` on `rch/devenv`).

## Problem

| Pain | Today |
|------|--------|
| Build recipes for Kudu/Impala/Ranger/Atlas live only in the **host** | Root `devenv.nix` tasks/process blocks |
| Component forks cannot be developed alone with the same Nix fixes | Except Kudu (`rch/devenv`) |
| Host imports raw component devenv | Risk: duplicate PG/KDC, port wars, package bloat |
| Maven SNAPSHOTs leaked to `~/.m2` | Fixed: `SIG_MAVEN_REPO=$PWD/.devenv/m2` |
| Impala pulled CDP Ranger admin tarball | Fixed for *future* bootstrap via `impala-config-local.sh` |
| Branch skew (historical) | Host pinned `rch/signals` while Kudu devenv lived on `rch/devenv` |

Naive `imports: [ ./components/kudu ]` is **not** enough: Kudu’s devenv owns Kerberos, BIND, Aeron, and a full cluster process — fine standalone, hostile as a silent merge into signals.

## Goals

1. **Standalone**: `cd components/kudu && devenv shell` builds and runs Kudu with Nix/GCC workarounds.
2. **Compose**: signals imports *capabilities* (packages + build tasks), not every process.
3. **Portable**: same contract works for aegir / other hosts that vendor the same forks.
4. **Upstream-friendly**: recipes live next to the code that needs them (fork branches), not only in weathership/signals.
5. **Isolated artifacts**: builds write under `.devenv/` (or component `build/`), never global user state by default.

## Non-goals

- Replacing Maven/Gradle with Nix derivations for full Atlas/Ranger (too large for day-one).
- Single mega-flake for all of Apache.
- Breaking in-flight Impala bootstrap / Ranger distro builds mid-flight.

## devenv primitives we should use

From devenv **1.10+** monorepo support ([guide](https://devenv.sh/guides/monorepo/), [v1.10 notes](https://devenv.sh/blog/2025/10/07/devenv-110-monorepo-nix-support-with-devenvyaml-imports/)):

- **`devenv.yaml` `imports`** — merge modules; paths starting with `/` are repo-root absolute.
- **`config.git.root`** — stable paths for tasks/processes when cwd varies.
- **`devenv.local.yaml` / `devenv.local.nix`** — developer overrides (gitignored).
- **Profiles** — activate “standalone” vs “library” variants without forking files forever.
- **Submodule as input** (fallback): `path:./components/kudu` when in-tree import is awkward ([#1030](https://github.com/cachix/devenv/issues/1030)).

## Recommended layering

```
┌─────────────────────────────────────────────────────────────┐
│  Host product (signals / aegir / …)                         │
│  devenv.nix  — platform services, ports, realm, product     │
│  config/*    — install.properties, AGE, HMS-free, SIGDG     │
│  imports     — asf modules in “library” profile             │
└───────────────────────────┬─────────────────────────────────┘
                            │ imports (library profile only)
┌───────────────────────────▼─────────────────────────────────┐
│  ASF fork (components/kudu, …)                              │
│  devenv.nix           — full standalone experience          │
│  devenv.module.nix    — packages + tasks only (library)     │
│  OR profiles.standalone / profiles.library                  │
└─────────────────────────────────────────────────────────────┘
```

### Layer A — Component library module (ship in each fork)

**File:** `devenv.module.nix` (or `nix/devenv-library.nix`) in `rch/asf-{kudu,impala,atlas,ranger}`.

**May define:**

- `packages` required to *build* that component on modern Nix (gcc flags story, thrift, JDK 11+jmods for Ranger Nashorn, …)
- `tasks."kudu:build-cpp"`, `tasks."kudu:build-thirdparty"`, …
- `env` knobs with **defaults that do not claim ports**
- Documented outputs: binary paths, `SIG_MAVEN_REPO` install layout for Java artifacts

**Must not define (in library profile):**

- `services.postgres`, host KDC, Atlas HTTP, Impala HS2
- Hard-coded realm/ports that conflict with the host (or gate them behind `enable = false` by default)

### Layer B — Component standalone devenv (same repo)

**File:** existing `devenv.nix` + `devenv.yaml` (Kudu already).

- `imports: [ ./devenv.module.nix ]` (or profile activation)
- Adds optional processes for solo developers (mini-cluster, optional KDC)
- Useful for CI of the fork alone: `devenv tasks run kudu:build-release`

### Layer C — Host product (signals)

**Root `devenv.nix` / `devenv.yaml`:**

```yaml
# devenv.yaml (illustrative)
imports:
  - ./nix/platform          # PG :5455, KDC, SecretSpec, SIG_MAVEN_REPO
  - ./components/kudu       # only if library profile / module import
  # later: ranger, impala, atlas library modules
```

Host owns:

| Concern | Owner |
|---------|--------|
| Ports (5455, 21010, 7051, 21050, 6080) | host |
| Realm `DEV.VISTA.ZNDX.ORG` | host |
| Process graph + depends_on | host |
| Product config (`config/ranger`, `config/impala`, AGE props) | host |
| Cross-wiring (Impala → local Ranger, Kudu masters) | host |
| How to compile Kudu thirdparty on GCC 15 / Nix | **component module** |

Host **processes** stay thin wrappers:

```bash
# host process — do not reimplement build flags here
exec "$KUDU_BUILD/bin/kudu-master" --rpc_bind_addresses=127.0.0.1:7051 ...
```

Host **tasks** either:

1. Delegate: `cd components/kudu && devenv tasks run kudu:build-cpp` (nested CLI), or  
2. Import the library module so `devenv tasks run kudu:build-cpp` works at the root.

Prefer (2) once modules are clean; (1) is an acceptable transitional pattern.

## Concrete contract (v0)

Each ASF component module exports:

```nix
# components/<name>/devenv.module.nix  (sketch)
{ pkgs, lib, config, ... }:
{
  # Identity for host composition
  env.ASF_COMPONENT = "kudu";  # optional

  packages = [ /* build-only */ ];

  tasks = {
    "kudu:build-cpp" = { /* Nix/GCC workarounds live HERE */ };
    "kudu:build-thirdparty" = { /* */ };
  };

  # Optional: declare where artifacts land (host process scripts read these)
  env.KUDU_BUILD = lib.mkDefault "${config.env.DEVENV_ROOT}/build/latest";
}
```

Host sets:

```nix
env.SIG_MAVEN_REPO = "${config.devenv.root}/.devenv/m2";  # or config.git.root
env.RANGER_HOME_OVERRIDE = "${config.git.root}/.devenv/ranger/admin";
```

and product-local files under `config/` that are **not** forked into ASF trees (except thin, gitignored `impala-config-local.sh` copies).

## What goes where (decision table)

| Item | Component module | Host |
|------|------------------|------|
| `EXTRA_CFLAGS=-std=gnu11`, GCC_INSTALL_PREFIX fix | ✓ | |
| JDK 11 + nashorn jmod for Ranger | ✓ | |
| `SIG_MAVEN_REPO` default | ✓ default under component or host `.devenv/m2` | host overrides to single store |
| Atlas AGE JDBC URL / port 21010 | | ✓ |
| Impala HMS-free flags, catalog JDBC | | ✓ |
| `RANGER_VERSION_OVERRIDE` / skip CDP tarball | thin local.sh | ✓ generates/copies |
| `kudu-master` process ports | optional solo | ✓ production layout |
| SecretSpec / `.env` | optional | ✓ |

## Maven / Gradle isolation (already started)

- **`SIG_MAVEN_REPO=$PWD/.devenv/m2`** + `MAVEN_ARGS=-Dmaven.repo.local=…` in host enterShell and tasks.
- Component library modules should **respect** `SIG_MAVEN_REPO` if set, else fall back to `$DEVENV_ROOT/.devenv/m2` when nested, never require `~/.m2` for install.
- Gradle (`kudu:install-java`): same local repo via `-Dmaven.repo.local` / init script.

This is what makes multi-project devenv adoption safe: two checkouts on one machine no longer fight over SNAPSHOT coordinates in the user home.

## Branch strategy for forks (canonical: `rch/devenv`)

Non-signals consumers (aegir, other platforms) should **not** have to pull a
signals-named branch to get Nix/devenv buildability. Converge on:

| Branch | Role |
|--------|------|
| **`rch/devenv`** | **Canonical.** devenv modules, Nix/GCC/Maven build fixes, library + standalone shells. What `.gitmodules` tracks. What other products should vendor. |
| `rch/signals` | **Optional product overlay** only when a change is truly signals-specific (and not yet generalized). Rebase/merge **onto** `rch/devenv` regularly. Prefer promoting useful patches into `rch/devenv` instead. |

```
apache/trunk ──► rch/devenv (devenv + build-on-Nix, shared)
                    │
                    ├── vendor into aegir / other hosts
                    └── rch/signals (rare product-only delta) ──► signals host if needed
```

**Rules of thumb**

- New work that makes an ASF tree buildable under devenv → commit on **`rch/devenv`**.
- Product wiring (AGE JDBC port, SIGDG policies, HMS-free Impala flags) → **host** `config/` + root devenv first; only fork if the Apache tree itself must change.
- If the tree must change for signals *and* the change is generally useful → land on **`rch/devenv`** (not `rch/signals`).
- signals pins submodule **SHAs**; `branch = rch/devenv` in `.gitmodules` only guides `git submodule update --remote`.

## Adoption story for “others”

Anyone (or aegir) can:

1. Vendor `rch/asf-kudu` (etc.) at branch **`rch/devenv`** (or a SHA on that line).
2. Either:
   - **Nested:** `cd components/kudu && devenv up` for Kudu-only, or  
   - **Compose:** host `devenv.yaml` imports `./components/kudu` library module + own platform.
3. Share Nix/GCC/Maven lessons by bumping the submodule pin — no copy of signals’ root `devenv.nix`.

Optional later extract: small `github.com/weathership/asf-devenv-modules` if multiple products need the same import without the full ASF tree — only if copy-paste across forks becomes painful.

## Phased implementation (signals)

### Phase 0 — Document + stop the bleeding (done / in progress)
- [x] Project-local Maven (`.devenv/m2`)
- [x] Impala local Ranger overrides (`config/impala/impala-config-local.sh`)
- [x] Capture this design note

### Phase 1 — Kudu as the reference nested module (on `rch/devenv`)
1. On `components/kudu` **`rch/devenv`**:
   - Split `devenv.module.nix` (packages + build tasks, Nix/GCC 15 fixes from host).
   - Standalone `devenv.nix` imports module + optional processes.
   - Ensure `rch/signals` (if kept) is rebased onto this tip or deleted once obsolete.
2. Host:
   - `.gitmodules` `branch = rch/devenv` (done).
   - `devenv.yaml`: `imports: [ ./components/kudu ]` **only after** library profile defaults disable Kudu’s KDC/PG-like extras.
   - Thin process wrappers keep signals ports.
   - Delete duplicated `kudu:build-cpp` body from host once task names match.

### Phase 2 — Ranger + Impala modules
- Ranger: JDK 11+jmods, `ranger:build` → `$SIG_MAVEN_REPO`, `ranger:install` → `.devenv/ranger/admin`.
- Impala: bootstrap task + toolchain packages; **no** CDP Ranger when override set; FE resolves plugins from `$SIG_MAVEN_REPO`.
- Host process graph only.

### Phase 3 — Atlas module
- `atlas:build` (AGE profile, mockito pin, project m2).
- Host process owns port 21010 + JDBC materialization (already improved).

### Phase 4 — Profiles + CI
- `devenv --profile library` / `standalone` documented per component.
- CI matrix: component-only task smoke; host stack smoke (`devenv up` + tier-0/1).

## Anti-patterns

| Avoid | Prefer |
|-------|--------|
| Host reimplements component build flags | Module task |
| Import full Kudu devenv and live with double KDC | Library module / profile |
| `mvn install` to `~/.m2` | `$SIG_MAVEN_REPO` |
| Copying CDP Ranger because Impala wants a tarball | Local build + `RANGER_*_OVERRIDE` |
| Product JDBC secrets in ASF trees | Host `config/` + SecretSpec |
| One 2k-line root devenv forever | Imports + thin host |

## Open questions

1. **Nested `devenv up`**: one process-compose (host) only; components never start their own compose when imported as library.
2. **Impala toolchain size** (~10GB+): keep bootstrap in Impala module; host disk hygiene docs (purge `thirdparty/build` intermediates, optional CDP ranger tarball removal when local).
3. **Upstream to Apache**: eventual PR of `devenv.module.nix` may be welcome as “unsupported experimental”; until then **`rch/devenv` on the forks** is the distribution channel.
4. **Promoting AGE / HMS-free**: prefer landing generically useful tree changes on `rch/devenv` so non-signals hosts benefit; keep true one-offs in host `config/`.

## Immediate next PR (small)

1. Extract Kudu build-task + Nix packages into `components/kudu/devenv.module.nix` on **`rch/devenv`** (no behavior change standalone).
2. Host import of that module behind a comment / feature flag.
3. Point host `kudu:build-cpp` at the shared task definition (or call through).
4. For each other ASF fork: create/update **`rch/devenv`** (even if initially = build baseline + empty module stub) so consumers have a stable branch name.

## References

- In-tree: `components/kudu/devenv.nix` (full solo env), root `devenv.nix` (platform), `config/impala/impala-config-local.sh`, `config/ranger/*`
- devenv monorepo guide: https://devenv.sh/guides/monorepo/
- devenv 1.10 imports: https://devenv.sh/blog/2025/10/07/devenv-110-monorepo-nix-support-with-devenvyaml-imports/
- Submodule import discussion: https://github.com/cachix/devenv/issues/1030
