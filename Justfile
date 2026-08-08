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

# Pre-download embedding model for offline / air-gap operation
cache-models:
    mkdir -p build/models
    HF_HUB_OFFLINE=0 SENTENCE_TRANSFORMERS_HOME=build/models \
        uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
    @echo "Model cached in build/models/. Pipeline runs offline (HF_HUB_OFFLINE=1)."

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

# Frontier batch harness (chunk × hop latency × EXPLAIN on edge_out/in)
# Frontier hop bench (PR-K4). Prefer --compare --measure exec for gates.
# Example: just atlas-frontier-bench --compare --skip-seed --batches 8,32,64,256
atlas-frontier-bench *ARGS:
    python3 scripts/atlas_frontier_bench.py --write-scratch {{ARGS}}

# Reset local KDC (required after Kerberos realm renames)
kdc-reset:
    devenv tasks run signals:kdc-reset

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
test *args:
    uv run pytest tests/ -v {{args}}

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

# ── Documentation ─────────────────────────────────────────────────

# Build mdbook docs
docs-build:
    mdbook build docs/current

# Serve mdbook docs with live reload
docs-serve:
    mdbook serve docs/current --open
