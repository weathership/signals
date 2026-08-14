# signals-360 pipeline recipes
#
# HOCON (config/base.conf) is the single source of truth for all config.
# Environment variables are captured by HOCON, not read directly by code.
#
# Workflow:
#   1. cp .env.example .env && edit .env
#   2. just resolve-config    (materializes build/config/sigint.env)
#   3. just preflight          (validates all required keys)
#   4. just test / just build-embeddings / just tag ...

# ── Config management ─────────────────────────────────────────────

# Resolve HOCON config + env vars to build/config/sigint.env
resolve-config:
    uv run python -c "from sigint.config import load_config, materialize_config; materialize_config(load_config(), 'build/config/sigint.env')"
    @echo "Resolved config -> build/config/sigint.env"

# Validate materialized config has all required keys
preflight:
    uv run python -c "from sigint.config import validate_materialized_config; errs = validate_materialized_config(); [print(f'  ERROR: {e}') for e in errs]; exit(1) if errs else print('Preflight OK')"

# Show resolved config
show-config:
    @if [ -f build/config/sigint.env ]; then cat build/config/sigint.env; else echo "Run 'just resolve-config' first"; fi

# Ensure MiniLM is available via HF_HOME / HF_HUB_CACHE / SENTENCE_TRANSFORMERS_HOME
# (lab: RAID under /raid/cache/*). Does not copy into build/models when caches exist.
cache-models:
    #!/usr/bin/env bash
    set -euo pipefail
    ST_HOME="${SENTENCE_TRANSFORMERS_HOME:-}"
    if [ -z "$ST_HOME" ]; then
      if [ -d /raid/cache/sentence-transformers ]; then
        ST_HOME=/raid/cache/sentence-transformers
      elif [ -n "${HF_HOME:-}" ]; then
        ST_HOME="$HF_HOME"
      else
        ST_HOME=build/models
        mkdir -p "$ST_HOME"
      fi
    fi
    export SENTENCE_TRANSFORMERS_HOME="$ST_HOME"
    export SIGINT_EMBEDDING_CACHE_DIR="${SIGINT_EMBEDDING_CACHE_DIR:-$ST_HOME}"
    echo "SENTENCE_TRANSFORMERS_HOME=$SENTENCE_TRANSFORMERS_HOME"
    echo "HF_HOME=${HF_HOME:-<unset>}  HF_HUB_CACHE=${HF_HUB_CACHE:-<unset>}"
    if find "$SENTENCE_TRANSFORMERS_HOME" ${HF_HUB_CACHE:+"$HF_HUB_CACHE"} ${HF_HOME:+"$HF_HOME"} \
         -type d -name 'models--sentence-transformers--all-MiniLM-L6-v2' 2>/dev/null | head -1 | grep -q .; then
      echo "all-MiniLM-L6-v2 already present — skip download (space-safe)."
      exit 0
    fi
    HF_HUB_OFFLINE=0 uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
    @echo "Model available under SENTENCE_TRANSFORMERS_HOME. Prefer HF_HUB_OFFLINE=1 at runtime."

# ── Pipeline commands ─────────────────────────────────────────────

# Build embeddings parquet
build-embeddings *ARGS:
    uv run python scripts/build_sigint_embeddings.py {{ARGS}}

# Run classification pipeline
run-pipeline *ARGS:
    uv run python scripts/run_pipeline.py {{ARGS}}

# Evaluate against GitTables benchmark
evaluate-gittables *ARGS:
    uv run python scripts/evaluate_gittables.py {{ARGS}}

# ── Benchmarking ──────────────────────────────────────────────────

# Run GitTables benchmark (zero config)
benchmark-gittables:
    uv run python scripts/evaluate_gittables.py \
        --data-dir build/datasets/gittables/ \
        --output build/gittables_eval.parquet

# ── Tag pipeline (live Impala + Atlas) ────────────────────────────

# Tag tables using resolved config
tag *TABLES:
    uv run python -m sigint --tables {{TABLES}}

# Dry-run tag (classify without writing to Atlas)
tag-dry-run *TABLES:
    uv run python -m sigint --tables {{TABLES}} --dry-run

# ── Native / ASF component builds (devenv tasks) ─────────────────

# Build Kudu C++ master + tserver from components/kudu
kudu-build:
    devenv tasks run kudu:build-cpp

# Publish Kudu Java client to local Maven
kudu-java:
    devenv tasks run kudu:install-java

# Download Impala toolchain (~5-10 GB, once per machine)
impala-bootstrap:
    devenv tasks run impala:bootstrap

# Full Impala build (C++ backend + Java frontend)
impala-build:
    devenv tasks run impala:build

# Build Atlas webapp with AGE graph provider
atlas-build:
    devenv tasks run atlas:build

# Build PostgreSQL Impala FDW extension (PG16 + thrift HS2 client)
impala-fdw-build:
    devenv tasks run impala-fdw:build

# Install FDW into devenv Postgres (:5455/signals) + default HS2 server
impala-fdw-install:
    devenv tasks run impala-fdw:install

# HS2 + FDW object smoke (needs Impala HS2 up)
impala-fdw-smoke:
    devenv tasks run impala-fdw:smoke

# Create atlas.* Kudu projection tables (HS2) + Postgres foreign tables
atlas-kudu-projections-seed:
    bash scripts/atlas_kudu_projections_seed.sh

# Create ranger.* Kudu tag/policy denorm tables (HS2) + Postgres foreign tables
# Admin SoR stays on Postgres ranger DB; projections protect PG under multi-engine load.
ranger-kudu-projections-seed:
    bash scripts/ranger_kudu_projections_seed.sh

# Both governance projection seeds (Atlas + Ranger)
gov-kudu-projections-seed: atlas-kudu-projections-seed ranger-kudu-projections-seed

# Frontier batch harness (chunk × hop latency × EXPLAIN on edge_out/in)
# Frontier hop bench (PR-K4). Prefer --compare --measure exec for gates.
# Example: just atlas-frontier-bench --compare --skip-seed --batches 8,32,64,256
atlas-frontier-bench *ARGS:
    python3 scripts/atlas_frontier_bench.py --write-scratch {{ARGS}}

# PR-K5a: Kudu Kerberos keytab/principal checks
kudu-kerberos-smoke:
    devenv tasks run signals:kudu-kerberos-smoke

# Reset local KDC (required after Kerberos realm renames)
kdc-reset:
    devenv tasks run signals:kdc-reset

# ── Cloudflare WARP / Zero Trust client ───────────────────────────
# Edge reachability (weathership org). Separate from lab Kerberos (just bootstrap).

# Status + interactive connect/disconnect/upgrade prompts (default).
# Subcommands: status | connect | disconnect | upgrade | upgrade --force
warp *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    bash scripts/warp-ops.sh {{ARGS}}

# ── Kerberos (required for all data-plane services — no NOSASL path) ─
# Clients dial $SIGNALS_KRB_HOST (FQDN), never 127.0.0.1, so SPNs match keytabs.

# Kerberos recovery/alias — normal path is `devenv up -d` alone (task
# signals:kerberos-bootstrap runs before Kudu/Impala). Use bootstrap when
# keytabs are missing outside a process-manager session.
bootstrap:
    bash scripts/kerberos-migrate.sh

# Alias kept for muscle memory
kerberos-migrate: bootstrap

# Obtain user ticket from signals.keytab (signals@REALM)
kinit:
    bash -c '. scripts/signals_kerberos.sh && signals_krb_kinit'

# Show tickets, host resolution, GSSAPI HS2 probe
kerberos-status:
    bash scripts/kerberos-status.sh

# KDC init/verify
kdc-init:
    devenv tasks run signals:kdc-init

# Serial stack build: Atlas → Kudu → Impala (long wall-clock)
stack-build:
    devenv tasks run atlas:build
    devenv tasks run kudu:build-cpp
    devenv tasks run impala:build

# ── Tests ─────────────────────────────────────────────────────────
# Layout matches constellation projects (e.g. synth):
#   tests/     — unit / hermetic pytest (testpaths in pyproject.toml)
#   features/  — Gherkin BDD (behave); @tier-0 hermetic, @tier-1 needs stack

# Unit tests (pytest under tests/; preflight via conftest)
# Exclude browser e2e by default (needs live signals-ui); use: just ui-test
test *args:
    uv run pytest tests/ -v --ignore=tests/ui {{args}}

# ── Headless browser (Playwright + Chromium) ──────────────────────
# Prefer devenv `chromium` on PATH. Otherwise install Playwright's browser:
#   just browser-install
# Env: SIGNALS_UI_BASE (default http://127.0.0.1:9889), SIGNALS_CHROMIUM_PATH,
#      SIGNALS_BROWSER_HEADED=1, SIGNALS_UI_BROWSER_SKIP=1

# Install Playwright Chromium when system chromium is unavailable
browser-install:
    #!/usr/bin/env bash
    set -euo pipefail
    if command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1; then
      echo "system chromium on PATH — Playwright will use it (no download needed)"
      command -v chromium || command -v chromium-browser
    elif [ -n "${SIGNALS_CHROMIUM_PATH:-}" ] && [ -x "${SIGNALS_CHROMIUM_PATH}" ]; then
      echo "SIGNALS_CHROMIUM_PATH=$SIGNALS_CHROMIUM_PATH"
    else
      echo "no system chromium — installing Playwright Chromium…"
      # avoid nix libstdc++ breaking the installer's node
      env -u LD_LIBRARY_PATH -u LD_PRELOAD uv run playwright install chromium
    fi
    env -u LD_LIBRARY_PATH -u LD_PRELOAD uv run python -c \
      "from signals.browser import chromium_executable, prepare_playwright_env; prepare_playwright_env(); print('chromium:', chromium_executable() or 'playwright-bundled'); print('node:', __import__('os').environ.get('PLAYWRIGHT_NODEJS_PATH'))"

# Browser e2e pytest (live UI required). Clears LD_LIBRARY_PATH for Playwright driver.
ui-test *args:
    #!/usr/bin/env bash
    set -euo pipefail
    env -u LD_LIBRARY_PATH -u LD_PRELOAD uv run pytest tests/ui/ -v -m browser {{args}}

# One-shot lineup verify (screenshots → build/ui-verify/)
ui-verify *args:
    #!/usr/bin/env bash
    set -euo pipefail
    env -u LD_LIBRARY_PATH -u LD_PRELOAD uv run python scripts/ui_browser_verify.py {{args}}

# BDD (default: tier-0 only). For stack scenarios: SIGNALS_BDD_TIER1=1 just behave
behave *args:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "$#" -eq 0 ]; then
      uv run behave --tags=tier-0
    else
      uv run behave "$@"
    fi

# Unit + hermetic BDD
test-all: test behave

# ── Stack backup / restore (only path: full portable all-services) ─
# SIGNALS_DATA_ROOT (default /raid/signals). Stamps under $SIGNALS_DATA_ROOT/backups/.
# No service subsets, no Kudu FS tars, no skip modes — one resilient portable path.

# Full portable backup of every service (fail-closed).
# Requires: just bootstrap, devenv up -d, valid Kerberos ticket (just kinit).
# Impala export is GSSAPI only (FQDN SPN). Auto-builds signals-df if needed.
backup *ARGS:
    bash scripts/backup-stack.sh {{ARGS}}

# Full portable restore + verify (fail-closed). Symmetric to just backup.
#   just restore <stamp>
#   just restore /raid/signals/backups/<stamp>
restore STAMP *ARGS:
    bash scripts/restore-stack.sh {{STAMP}} {{ARGS}}

# DataFusion CLI for the logical plane (also auto-built by just backup)
signals-df-build:
    cargo build -p signals-df --release

# ── YuniKorn UI / REST exposure (lab RKE2) ────────────────────────
# Durable: NodePort 30889 (web) / 30080 (REST) on the node IP.
# Classic ports: `just yk-ui-forward` binds 0.0.0.0:9889 and :9080.
# LAN:  http://192.168.1.55:9889  or  http://192.168.1.55:30889
# REST: http://192.168.1.55:9080  or  http://192.168.1.55:30080
# ZT:   add 192.168.1.55 (or /24) as a Zero Trust private network route, or
#       point a cloudflared Access tunnel at http://127.0.0.1:9889.

yk-ui-forward:
    #!/usr/bin/env bash
    set -euo pipefail
    export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/rke2.yaml}"
    # Ensure NodePort surface exists (idempotent)
    kubectl patch svc yunikorn-service -n yunikorn --type=merge -p '{
      "spec": {
        "type": "NodePort",
        "ports": [
          {"name": "yunikorn-service", "port": 9080, "targetPort": 9080, "nodePort": 30080, "protocol": "TCP"},
          {"name": "yunikorn-service-web", "port": 9889, "targetPort": 9889, "nodePort": 30889, "protocol": "TCP"}
        ]
      }
    }' >/dev/null
    if pgrep -f 'kubectl.*port-forward.*yunikorn-service' >/dev/null 2>&1; then
      echo "port-forward already running:"
      pgrep -af 'kubectl.*port-forward.*yunikorn-service' || true
    else
      LOG="${TMPDIR:-/tmp}/yk-port-forward.log"
      nohup kubectl port-forward --address=0.0.0.0 -n yunikorn \
        svc/yunikorn-service 9889:9889 9080:9080 >"$LOG" 2>&1 &
      sleep 1
      echo "port-forward started (log $LOG)"
    fi
    HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    HOST_IP="${HOST_IP:-192.168.1.55}"
    echo ""
    echo "Stock YuniKorn web (if still enabled on this pin):"
    echo "  NodePort    : http://${HOST_IP}:30889/"
    echo "  classic pf  : http://${HOST_IP}:9889/  (conflicts with signals-ui)"
    echo "REST          : http://${HOST_IP}:30080/  (also :9080 with this forward)"
    echo "signals-ui    : just signals-ui  → http://${HOST_IP}:9889/  (primary)"
    echo "  SIGNALS_YK_API_URL=http://${HOST_IP}:30080"
    echo ""
    echo "Zero Trust: WARP include-mode does not yet route this LAN — either"
    echo "  (1) Zero Trust → Networks → add private route 192.168.1.0/24 via this host, or"
    echo "  (2) cloudflared tunnel + Access app → http://127.0.0.1:9889"
    curl -sS -m 2 -o /dev/null -w "smoke :9889 → HTTP %{http_code}\n" "http://${HOST_IP}:9889/" || true

yk-ui-forward-stop:
    #!/usr/bin/env bash
    set -euo pipefail
    pkill -f 'kubectl.*port-forward.*yunikorn-service' 2>/dev/null && echo "stopped" || echo "no port-forward"

# ── signals-ui (primary backplane UI — yk-web superset, Rust/Axum) ─
# YuniKorn required (SIGNALS_YK_API_URL). Default bind 0.0.0.0:9889 (LAN).
# Stock YK web (when still enabled upstream): NodePort :30889.
# Lab REST default: NodePort :30080 on the RKE2 node.

signals-ui-build:
    #!/usr/bin/env bash
    set -euo pipefail
    cd components/signals-ui
    cargo build --release -p signals-ui
    echo "→ components/signals-ui/target/release/signals-ui"

# Foreground run. Release binary if present; else cargo run.
# Critical plane: PG + RustFS + Kudu/Impala + YK + Knative + Metaflow + Airflow.
# See docs/current/src/architecture/stack-critical-plane.md
# Invoked automatically before signals-ui on `devenv up -d`.
# Preflight may auto-bootstrap Metaflow/Airflow/Eventing; for check-only use signals-ready.
stack-ready:
    bash scripts/signals_stack_preflight.sh

# Check-only readiness oneshot (Gaius PASS/WARN/FAIL). Critical includes Kudu + Metaflow.
# Exit 0 iff all critical components PASS. Peers / systemd should wait on this.
signals-ready *ARGS:
    bash scripts/signals_ready.sh {{ARGS}}

# Regenerate Python stubs from components/signals-protocol (spec → codegen).
gen-zndx-engine-py:
    bash scripts/gen_zndx_engine_py.sh

# gRPC lattice CI: generated Status client + reflection check (SKIP if down).
# Require subset: just lattice-ci --require gaius,metabase
lattice-ci *ARGS:
    bash scripts/lattice_ci.sh {{ARGS}}

# Install foundation systemd units (sudo). --peers / --enable / --start optional.
install-systemd *ARGS:
    bash scripts/install_signals_systemd.sh {{ARGS}}

# Assert devenv process graph includes Kudu/Impala (not a partial up).
process-assert:
    bash scripts/devenv_process_assert.sh

# Kudu/Impala binary + layout gate (does not compile).
data-plane-preflight:
    bash scripts/data_plane_preflight.sh

# Post-up Kudu + Impala CI gate (elevated system check).
data-plane-ci:
    bash scripts/data_plane_ci.sh

# One-off alias → data-plane-ci (prefer *-ci for elevated gates).
data-plane-smoke:
    bash scripts/data_plane_smoke.sh

# Clean stop of *this* stack only (never kill foreign devenv Postgres) + up -d.
stack-reset:
    bash scripts/devenv_stack_reset.sh

# M3: Knative Eventing + platform Broker + Airflow DAG-run sink (no Argo).
knative-eventing:
    bash scripts/knative_eventing_bootstrap.sh

# Publish CloudEvent to signals-events/default Broker.
events-publish *ARGS:
    bash scripts/signals_events_publish.sh {{ARGS}}

# CE → Airflow DAG CI gate (installs eventing if needed).
airflow-eventing-ci:
    bash scripts/airflow_eventing_ci.sh

# One-off alias → airflow-eventing-ci.
airflow-eventing-smoke:
    bash scripts/airflow_eventing_smoke.sh

# Preferred up/down wrappers (turn-key + port lattice hygiene).
# Bare `devenv processes down` often leaves the postmaster on :5455; we stop
# only *our* .devenv/state/postgres PID (see signals_port_lattice.sh).
up:
    devenv up -d

down:
    #!/usr/bin/env bash
    set -euo pipefail
    ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    cd "$ROOT"
    devenv processes down 2>/dev/null || true
    # shellcheck source=/dev/null
    . "$ROOT/scripts/signals_port_lattice.sh"
    signals_pg_stop_ours "$ROOT"
    echo "stack down — signals :5455 free (system :5432 and other devenvs untouched)"

# Require federation (YK+Knative) only.
federation-ready:
    bash scripts/federation_preflight.sh

# Platform Metaflow M1: metadata service on RKE2 + PG + RustFS bucket.
# Submodule: components/metaflow (weathership/oss-metaflow rch/devenv).
metaflow-platform:
    bash scripts/metaflow_platform_bootstrap.sh

metaflow-platform-status:
    #!/usr/bin/env bash
    set -euo pipefail
    export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/rke2.yaml}"
    echo "=== metaflow ns ==="
    kubectl get all,cm,secret -n metaflow 2>&1 | head -40
    echo "=== ping ==="
    curl -sS -m 3 -w "\nHTTP %{http_code}\n" http://127.0.0.1:30180/ping || true

# Platform Airflow 3 M2: LocalExecutor on RKE2 + host PG + NodePort 30800.
# Chart: components/airflow/chart · values: config/k8s/airflow/values-signals.yaml
airflow-platform:
    bash scripts/airflow_platform_bootstrap.sh

airflow-platform-status:
    #!/usr/bin/env bash
    set -euo pipefail
    export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/rke2.yaml}"
    echo "=== airflow ns ==="
    kubectl get all,cm,secret -n airflow 2>&1 | head -50
    echo "=== API (public version) ==="
    curl -sS -m 3 -w "\nHTTP %{http_code}\n" http://127.0.0.1:30800/api/v2/version 2>/dev/null || true
    echo "=== JWT probe (admin) ==="
    TOKEN="$(curl -sS -m 5 -X POST http://127.0.0.1:30800/auth/token \
      -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"admin"}' 2>/dev/null \
      | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null || true)"
    if [[ -n "$TOKEN" ]]; then
      curl -sS -m 5 -H "Authorization: Bearer $TOKEN" \
        'http://127.0.0.1:30800/api/v2/dags?limit=5' 2>/dev/null \
        | python3 -c 'import sys,json; d=json.load(sys.stdin); print("dags:", [x["dag_id"] for x in d.get("dags",[])])' 2>/dev/null || true
    else
      echo "(no token — admin user may not exist yet)"
    fi

# Trigger signals_ci DAG and wait for success (elevated M2 CI gate).
airflow-platform-ci:
    bash scripts/airflow_platform_ci.sh

# One-off alias → airflow-platform-ci.
airflow-platform-smoke:
    bash scripts/airflow_platform_smoke.sh

signals-ui *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    cd "$ROOT"
    unset SIGNALS_UI_ALLOW_NO_YK || true
    export SIGNALS_YK_API_URL="${SIGNALS_YK_API_URL:-http://127.0.0.1:30080}"
    export SIGNALS_UI_BIND="${SIGNALS_UI_BIND:-0.0.0.0:9889}"
    export SIGNALS_ATLAS_HTTP_URL="${SIGNALS_ATLAS_HTTP_URL:-http://127.0.0.1:${SIGNALS_ATLAS_HTTP_PORT:-21010}}"
    export SIGNALS_UI_CONFIG="${SIGNALS_UI_CONFIG:-$ROOT/build/config/signals-ui.json}"
    bash scripts/federation_preflight.sh
    cd components/signals-ui
    export SIGNALS_UI_ASSETS="$PWD/assets"
    mkdir -p "$(dirname "$SIGNALS_UI_CONFIG")"
    BIN="$PWD/target/release/signals-ui"
    if [ -x "$BIN" ]; then
      exec "$BIN" {{ARGS}}
    fi
    cargo run -p signals-ui -- {{ARGS}}

data-layout:
    devenv tasks run signals:data-layout

# ── Documentation ─────────────────────────────────────────────────

# Build mdbook docs
docs-build:
    mdbook build docs/current

# Serve mdbook docs with live reload
docs-serve:
    mdbook serve docs/current --open
