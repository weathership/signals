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

# ── Tests ─────────────────────────────────────────────────────────

# Run all Python tests (includes preflight config check)
test:
    uv run pytest tests/sigint/ -v

# ── Documentation ─────────────────────────────────────────────────

# Build mdbook docs
docs-build:
    mdbook build docs/current

# Serve mdbook docs with live reload
docs-serve:
    mdbook serve docs/current --open
