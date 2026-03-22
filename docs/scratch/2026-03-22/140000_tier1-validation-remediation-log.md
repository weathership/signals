# Tier-1 Integration Validation — Remediation Log

Each entry records a manual fix applied during validation, what it unblocked,
and the lasting fix needed so the stack comes up correctly without intervention.

## Remediations

### R-01: pg_cron extension not created in `signals` database

- **Symptom**: `health_postgres.feature:5` fails — `Extension 'pg_cron' is not installed`
- **Manual fix**: `psql -p 5455 -d signals -c "CREATE EXTENSION IF NOT EXISTS pg_cron"`
- **Root cause**: The `initialScript` in devenv.nix runs `CREATE EXTENSION IF NOT EXISTS pg_cron` but this script only executes on first database creation. If the database already existed before pg_cron was added to `shared_preload_libraries`, the extension was never created.
- **Lasting fix needed**: The `initialScript` approach is fragile — it's a one-shot that doesn't re-run. Options:
  1. Add an idempotent task `devenv tasks run signals:pg-extensions` that ensures all extensions exist
  2. Add extension checks to `features/environment.py` `before_all()` or a startup script
  3. Use a migration-style approach that runs on every `devenv up`
- **Status**: PENDING lasting fix

### R-02: Atlas health steps fail on repeated runs (409 Conflict)

- **Symptom**: `health_atlas.feature` scenarios 4, 6, 9 fail with 409 — type/glossary already exists from a previous test run
- **Manual fix**: Made three creation steps idempotent in `health_steps.py`:
  1. `step_create_entity_type` — check if type exists before creating
  2. `step_create_classification_type` — check if classification type exists before creating
  3. `step_create_glossary` — on 409, list glossaries and find existing by name
- **Root cause**: Health check steps assumed a clean Atlas state. Since these are health checks (not isolation tests), they should be idempotent — verifying the resource exists rather than requiring it to not exist.
- **Lasting fix**: The code changes above ARE the lasting fix — committed to `health_steps.py`. No further action needed.
- **Status**: FIXED

### R-03: Kudu REST API `/api/v1/tables` not available

- **Symptom**: `integration_catalog_sync.feature:8` fails — `Kudu API error: No handler for URI /api/v1/tables`
- **Root cause**: The Kudu REST API (`/api/v1/tables`) requires `--enable_rest_api` flag. Our build doesn't include this endpoint. Rather than adding special-case flags (per user preference for single default configuration), the step should verify through the standard path.
- **Lasting fix**: Changed `step_table_in_kudu` to verify table existence via `SHOW TABLES` through Impala, which is the standard operational path and confirms both Kudu storage and Impala catalog visibility.
- **Status**: FIXED

### R-04: Impala UPDATE type precision loss

- **Symptom**: `integration_catalog_sync.feature:14` errors — `AnalysisException: Possible loss of precision... Expression 'value + 1' (type: BIGINT) would need to be cast to INT for column 'value'`
- **Root cause**: Impala arithmetic promotion — `INT + INT` promotes to `BIGINT`. The column is `INT`, so Impala rejects implicit narrowing.
- **Lasting fix**: Changed UPDATE statement to `SET value = CAST(value + 1 AS INT) WHERE id < 5`
- **Status**: FIXED

### R-05: Behave cross-domain step discovery

- **Symptom**: `integration_meta_tagging.feature` scenario 6 (Tagger dry-run) shows all 5 steps as `# None` (undefined), despite step definitions existing in `features/tagging/steps/tagging_steps.py` and being imported in `features/steps/steps.py`.
- **Root cause**: When behave receives a specific feature file path, it uses the file's parent directory as base (`features/platform/`), then only discovers steps from `features/platform/steps/`. The `features/steps/steps.py` re-export hub is never loaded. Steps from other domain directories (e.g. `features/tagging/steps/`) are invisible.
- **Lasting fix**: Added cross-domain step imports to each domain's `steps/__init__.py`:
  - `features/platform/steps/__init__.py` — imports `features.tagging.steps.tagging_steps`
  - `features/tagging/steps/__init__.py` — imports `features.platform.steps.integration_steps`
  This ensures steps are discoverable regardless of which domain's feature file is being run.
- **Status**: FIXED

### R-06: Thrift IPv6 fallback noise on every Impala connection

- **Symptom**: Every Impala step produces 2-4 `ConnectionRefusedError` tracebacks — thrift tries `::1` (IPv6), fails, falls back to `127.0.0.1` (IPv4). Tests pass but output is unreadable.
- **Root cause**: `host="localhost"` resolves to both `::1` and `127.0.0.1`. Impala binds only to `0.0.0.0` (IPv4). Thrift's TSocket tries each address in order and logs failures.
- **Lasting fix**: Changed all Impala host defaults from `"localhost"` to `"127.0.0.1"`:
  - `features/platform/steps/helpers.py` — `impala_conn()` call
  - `src/sigint/config.py` — `PipelineConfig.impala_host` and `TaggingConfig.impala_host` defaults
  - `config/base.conf` — `impala.host` default
  - `.env.example` — commented example value
- **Status**: FIXED

### R-07: HuggingFace phone-home on every Tagger invocation

- **Symptom**: Every Tagger scenario produces ~30 HTTP requests to `huggingface.co` to check model freshness. Incompatible with air-gapped deployments.
- **Root cause**: `SentenceTransformer('all-MiniLM-L6-v2')` phones home to HuggingFace Hub on every load, even when the model is already cached locally.
- **Lasting fix**: Three-layer isolation:
  1. **Config**: Added `embedding.cache_dir = "build/models"` to `base.conf` — local model store, flows through `PipelineConfig` → `EmbeddingClassifierConfig` → `SentenceTransformer(cache_folder=...)`.
  2. **Environment**: `HF_HUB_OFFLINE=1` + `SENTENCE_TRANSFORMERS_HOME` set in `devenv.nix` `enterShell` — prevents any runtime phone-home.
  3. **Bootstrap**: `devenv tasks run sigint:cache-models` (or `just cache-models`) pre-downloads the model with `HF_HUB_OFFLINE=0` temporarily overridden.
  For Zarf: `build/models/` can be baked into container images or staged to S3 via VPC endpoint.
- **Status**: FIXED

## Summary

| ID | Issue | Status |
|----|-------|--------|
| R-01 | pg_cron extension not auto-created | PENDING |
| R-02 | Atlas health steps 409 on repeated runs | FIXED |
| R-03 | Kudu REST API not available | FIXED |
| R-04 | Impala UPDATE type precision loss | FIXED |
| R-05 | Behave cross-domain step discovery | FIXED |
| R-06 | Thrift IPv6 fallback noise | FIXED |
| R-07 | HuggingFace phone-home breaks air-gap | FIXED |

## Final Results

All tier-1 integration scenarios validated and passing:

| Feature | Scenarios | Result |
|---------|-----------|--------|
| health_postgres | 3 | 3/3 pass |
| health_kerberos | 3 | 3/3 pass |
| health_kudu | 3 | 3/3 pass |
| health_impala | 3 | 3/3 pass |
| health_atlas | 10 | 10/10 pass |
| integration_catalog_sync | 4 | 4/4 pass |
| integration_meta_tagging | 6 | 6/6 pass (incl. Tagger setup_types + dry-run) |
| pipeline_tagging | 2 | 2/2 pass (full pipeline + dry-run) |
| **Total** | **34** | **34/34 pass** |

Regressions: 40/40 tier-0 classification, 363/363 pytest
