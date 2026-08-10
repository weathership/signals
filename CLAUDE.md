# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

signals-360 — uncertainty-aware column classification for metadata governance. Licensed Apache 2.0.

The primary workflow is the **sigint classification pipeline**: a Python package that classifies database columns into a hierarchical taxonomy using Dempster-Shafer evidence fusion, CatBoost gradient boosting, and SAGE feature importance analysis. Classifications feed downstream into Apache Atlas for governance tagging and Ranger for policy enforcement.

Two Python packages live under `src/`:

- `sigint/` — the classification pipeline (features, embeddings, DST fusion, CatBoost/SVM, LLM bootstrap, Atlas tagging)
- `signals/` — platform primitives shared across pipeline stages (`platform.py` capability detection, `persistence.py` persistent homology)

## Primary Workflow

### sigint Classification Pipeline

`scripts/build_sigint_embeddings.py` is the pipeline driver; its `main()` is organized into explicitly commented stages that mirror the architecture:

1. **Feature Extraction** — 12 discrete, ablatable features per column (`FEATURE_NAMES` in `src/sigint/features.py`: column_name, column_type, sample_values, cardinality, null_ratio, value_entropy, pattern_signals, avg_value_length, numeric_ratio, sibling_context, source_table, value_description). Each is independently maskable — that mask is the SAGE ablation hook.
2. **Embedding Classification** — Sentence-transformer embeddings (MiniLM-L6, 384-dim) with cosine similarity to taxonomy reference embeddings
3. **CatBoost Training** — Gradient boosting on a concatenated matrix `[full_emb | value_only_emb | discrete_features]` plus per-category cosine similarities; discrete features are scaled by `sqrt(emb_dim / n_discrete)` so they aren't drowned out by the embedding block. Trained on synthetic data or cross-validated; `--self-train` injects GT labels for LLM annotation reproduction (99.4% accuracy)
4. **DST Evidence Fusion** — Dempster-Shafer Theory combines 5 evidence sources (cosine, CatBoost, pattern detection, name matching, SVM) into belief intervals [Bel, Pl] with conflict diagnostics
5. **SAGE Analysis** — Shapley Additive Global importancE measures each feature's marginal contribution to accuracy (runs always; uses predictions as pseudo-GT when no ground truth is supplied)

DST evidence fusion is always active — the pipeline produces belief intervals automatically when multiple evidence sources are available. Item-wise SHAP explanations are included by default (disable with `--no-shap`).

### Three Operational Modes

**External benchmarks** test generalization on public datasets:
```bash
# Download GitTables CTA benchmark (2517 columns, 122 DBpedia types)
uv run python scripts/download_gittables_benchmark.py --output-dir build/datasets/gittables/

# Evaluate against ground truth (or: just benchmark-gittables)
uv run python scripts/evaluate_gittables.py \
    --data-dir build/datasets/gittables/ \
    --output build/gittables_eval.parquet
```

**Internal synthetic data** trains and evaluates on the SIGDG taxonomy (42 categories, 30 leaves):
```bash
# Single-command: auto-generate synthetic data + train + classify + SHAP
uv run python scripts/build_sigint_embeddings.py \
    --data-dir <data-dir> \
    --taxonomy <taxonomy> --threshold 0.25 \
    --ground-truth <ground-truth.json> \
    --auto-generate --variants-per-category 50 \
    --output build/sigint_shap_eval.parquet

# Two-step: generate separately, then train→eval
uv run python scripts/generate_meta_tagging_train.py \
    --data-dir <data-dir> \
    --output-dir build/datasets/sigint_train/ \
    --variants-per-category 50

uv run python scripts/build_sigint_embeddings.py \
    --data-dir <data-dir> \
    --taxonomy <taxonomy> --threshold 0.25 \
    --ground-truth <ground-truth.json> \
    --train-dir build/datasets/sigint_train/ \
    --output build/sigint_embeddings.parquet
```

**LLM bootstrap** produces ground truth for novel tables that have none. The outer loop uses DST conflict `K` as the disagreement signal between LLM and ML predictions, revisiting high-conflict columns until `k_threshold` / `coverage_target` are met (`config/base.conf` → `bootstrap { … }`). Its JSON output is directly consumable as `--ground-truth` / `--self-train` input:
```bash
uv run python scripts/bootstrap_classify.py \
    --data-dir <data-dir> --taxonomy sigdg --threshold 0.25 \
    --output build/bootstrap_gt.json
# air-gap variant: --llm-backend openai_compatible --llm-base-url http://localhost:8000/v1 --llm-model <model>

uv run python scripts/build_sigint_embeddings.py \
    --data-dir <data-dir> --ground-truth build/bootstrap_gt.json \
    --self-train --auto-generate --output build/sigint_final.parquet
```

### Live Tagging

`python -m sigint` (console script: `sigint`) runs sample → classify → tag against live Impala + Atlas, scoped by `scope.databases` / `scope.tables` in HOCON:
```bash
just tag <table> ...          # write classifications to Atlas
just tag-dry-run <table> ...  # classify without writing
```

### Key Source Files

| File | Purpose |
|------|---------|
| `src/sigint/features.py` | 12 SAGE-ablatable features + pattern detectors |
| `src/sigint/embedding_classifier.py` | Embedding classification + DST orchestration |
| `src/sigint/belief.py` | Dempster-Shafer mass functions and combination |
| `src/sigint/mass_functions.py` | Evidence-to-mass converters (cosine, CatBoost, pattern, name) |
| `src/sigint/classifier.py` | HierarchicalClassification with belief intervals |
| `src/sigint/category_set.py` | Taxonomy-agnostic category sets (SIGDG + GitTables), hierarchy nav for DST |
| `src/sigint/ontology.py` | SIGDG categories, sensitivity levels, Atlas type mapping (BFO 2020-grounded) |
| `src/sigint/sage_analysis.py` | SAGE feature importance with GPU acceleration |
| `src/sigint/shap_analysis.py` | Per-item CatBoost TreeSHAP explanations |
| `src/sigint/svm_classifier.py` | TF-IDF + LinearSVC 5th DST evidence source |
| `src/sigint/confusable_pairs.py` | Known ambiguous category pairs (ADID/GUID, BAN/PAN) |
| `src/sigint/llm_backend.py` | Dual LLM backend (Anthropic + OpenAI-compatible) |
| `src/sigint/bootstrap_agent.py` | LLM bootstrap convergence loop (K-based revisiting) |
| `src/sigint/data_element.py` | Composite governance concepts spanning columns/tables (`sigint_data_element` in Atlas) |
| `src/sigint/schema_discovery.py` | Data Element discovery: naming conventions, FK hints, post-hoc co-occurrence |
| `src/sigint/tagger.py` | Orchestrator: sample → classify → tag (Impala + Atlas) |
| `src/signals/platform.py` | Cached CPU/GPU/OS capability probes for hot-path backend selection |
| `src/signals/persistence.py` | `PersistenceBackend` protocol + Ripser CPU backend (CUDA backend planned) |
| `scripts/build_sigint_embeddings.py` | Full pipeline: features → classification → CatBoost → SAGE |
| `scripts/bootstrap_classify.py` | Bootstrap CLI: novel table classification without GT |
| `scripts/generate_meta_tagging_train.py` | Synthetic column generator (all SIGDG leaves, 70+ value generators) |
| `config/sigint/gittables_taxonomy.py` | BFO-grounded GitTables taxonomy (122 types) |

`signals.platform` is the single place accelerator selection lives — modules with CPU and GPU paths query it instead of probing torch/CUDA directly. It is deliberately distinct from `sigint.config.preflight_gpu()`, which produces the rich startup report (nvidia-smi probing, version-mismatch warnings).

## Configuration

HOCON (`config/base.conf`) is the **single source of truth** for all pipeline configuration. No application module reads `os.environ` directly — environment variables are captured by HOCON via `${?VAR}` substitution and flow through `PipelineConfig`.

**Precedence** (highest wins): CLI args > `.env` / env vars > `config/base.conf` defaults

**Key principle:** All config flows through `.env` → HOCON `${?VAR}` → `PipelineConfig` → application code. This ensures consistent, auditable config state whether running via `just`, `devenv`, or standalone `uv run`.

**Secrets:** Declared in `secretspec.toml` (no values); enabled in `devenv.yaml` (`provider: dotenv`). Non-secret Kerberos shape stays in `devenv.nix` (`KRB5_REALM=DEV.VISTA.ZNDX.ORG`). Prefer `secretspec run -- <cmd>` for secret-bearing jobs. See `docs/current/src/operations/secrets.md`.

HOCON sections: `impala`, `atlas`, `sampling`, `classifier`, `embedding`, `llm`, `taxonomy`, `vocabulary_mapping`, `sage`, `shap`, `svm`, `gpu`, `ml`, `bootstrap`, `data`, `scope`.

### Config Files

| File | Purpose |
|------|---------|
| `config/base.conf` | HOCON schema with defaults and `${?VAR}` env var capture |
| `.env.example` | Template for user overrides (copy to `.env`) |
| `build/config/sigint.env` | Materialized resolved config (gitignored) |
| `src/sigint/config.py` | `PipelineConfig`, `load_config()`, `materialize_config()`, validation, `preflight_gpu()` |
| `src/sigint/vocab_mapping.py` | Vocabulary mapping between user labels and SIGDG codes |

### Setup and Preflight

```bash
cp .env.example .env           # 1. Create user overrides (edit as needed)
just resolve-config            # 2. Materialize HOCON → build/config/sigint.env
just preflight                 # 3. Validate all required keys present
just test                      # 4. Tests auto-validate via conftest preflight
```

The preflight check (`tests/conftest.py`) runs automatically as a session-scoped pytest fixture. It validates that the materialized config contains all required keys and conditionally-required keys (e.g., `ANTHROPIC_API_KEY` when `classifier_type=llm`). If the materialized config doesn't exist, it auto-generates from `config/base.conf` defaults so tests work out of the box. A second session fixture runs `preflight_gpu()` and surfaces CUDA mismatches as warnings, never failures.

### Adding Config Keys

1. Add the HOCON key with default and `${?VAR}` override to `config/base.conf`
2. Add the field to `PipelineConfig` dataclass in `src/sigint/config.py`
3. Add the HOCON path → field mapping to `_HOCON_MAP` in `config.py`
4. Add the env var to `.env.example`
5. If required, add to `REQUIRED_KEYS` or `CONDITIONAL_KEYS` in `config.py`

## Development Environment

Uses [devenv](https://devenv.sh/) (Nix-based) with direnv for automatic shell activation.

- **Enter the dev shell:** `devenv shell` (or automatic via direnv)
- **Start all services:** `devenv up` (PostgreSQL + Kerberos KDC + Atlas + Kudu + Impala)
- **Run devenv tests:** `devenv test`
- **List tasks:** `devenv tasks list` — notable: `signals:kdc-init`, `signals:kdc-reset`, `signals:catalog-init`, `sigint:resolve-config`, `sigint:cache-models`, `docs:build`, `docs:serve`, `atlas:build`, `kudu:build-cpp`, `impala:build`, `impala:build-fe`, `impala:test-fe`, `hms:init-schema`, `polaris:install`

Key files:
- `devenv.nix` — packages, services, processes, tasks, and shell configuration
- `devenv.yaml` — Nix inputs configuration
- `.envrc` — direnv integration

**Note:** `uv` manages a project-local `.venv`. The first `uv run` in a fresh checkout syncs a large dependency set (torch, catboost, sentence-transformers) and can take many minutes — a "hanging" first test run is usually this sync.

### Languages
- **Python 3.12** — primary language; `uv` for package management
- **Java 21** — ASF component builds (Maven)
- **Rust** — planned gRPC engine (not yet implemented)

### Air-gap / offline operation

```bash
just cache-models   # ensure MiniLM via HF_HOME / SENTENCE_TRANSFORMERS_HOME (RAID preferred)
```
Afterwards the pipeline runs with `HF_HUB_OFFLINE=1` and existing HF cache env vars (`HF_HOME`, `HF_HUB_CACHE`, `SENTENCE_TRANSFORMERS_HOME` — lab defaults under `/raid/cache/*`). Do not force a second copy under `build/models/` when RAID caches exist. For LLM stages, point `--llm-backend openai_compatible --llm-base-url` at a local vLLM server instead of a hosted API.

## Build and Test Commands

`Justfile` holds the canonical entry points — prefer them over ad-hoc invocations:

```bash
just resolve-config       # materialize HOCON → build/config/sigint.env (required first)
just preflight            # validate materialized config
just show-config          # print resolved config
just cache-models         # pre-download embedding model for offline use
just test                 # uv run pytest tests/sigint/ -v
just build-embeddings ... # scripts/build_sigint_embeddings.py
just run-pipeline ...     # scripts/run_pipeline.py
just evaluate-gittables ...
just benchmark-gittables  # zero-config GitTables run
just tag / just tag-dry-run <tables>
just docs-build / just docs-serve
```

### Test layout (constellation standard)

| Path | Role |
|------|------|
| `tests/` | **Unit / hermetic pytest** (`testpaths` in pyproject.toml). `tests/sigint/` pipeline units; `tests/workload/` stack lifecycle harness |
| `features/` | **BDD (behave)** Gherkin + steps. Domains: `classification/`, `platform/`, `tagging/`. Retired specs in `features_archive/` |

Same split as synth (`tests/` + `features/`).

### Python unit tests

```bash
just test                    # uv run pytest tests/ -v  (all units + preflight)
uv run pytest tests/sigint/ -v
uv run pytest tests/sigint/test_belief.py::TestBeliefAssignment::test_normalization -v
```

### BDD suite (behave)

Tier tags in `features/environment.py`:

- `@tier-0` — pure Python, no services (default for `just behave`)
- `@tier-1` — full `devenv up` stack; **opt in** with `SIGNALS_BDD_TIER1=1` (then hook waits on process-compose + Atlas/Impala readiness)
- tier-2/3 — not implemented, auto-skipped

```bash
just behave                  # --tags=tier-0
just behave features/classification/
SIGNALS_BDD_TIER1=1 just behave --tags=tier-1 --no-capture \
    features/platform/data_lifecycle.feature
just test-all                # unit + hermetic BDD
```

### Workload harness

`tests/workload/lifecycle.py` drives a real data lifecycle against the running stack:

```bash
uv run python -m tests.workload.lifecycle --phase all --rows 1000 --partitions 10 --upsert-ratio 0.20
# phases: setup | land | consolidate | verify | all | teardown
```

### CI

- `.github/workflows/catalog-ci.yml` — Tier 0 runs Impala FE `ConfigLoaderTest` under Maven/Java 21 on `ubuntu-latest`; Tier 1 runs `devenv up --detach`, `signals:catalog-init`, the lifecycle workload, and the `@data-lifecycle and @ci` BDD scenarios on a **self-hosted** runner. Triggered by changes under `components/impala/fe/.../{catalog,service}/`, `config/{impala,hms,polaris}/`, `tests/workload/`, `features/platform/data_lifecycle*`.
- `.github/workflows/docs.yml` — builds the mdbook (mdBook + D2 + preprocessors) and deploys to GitHub Pages.

### ASF Components (submodules in `components/`)

All tracked on **`rch/devenv`** branch from `rch` GitHub forks (shared devenv/Nix line for non-signals consumers too):

| Component | Purpose |
|-----------|---------|
| `atlas` | Metadata governance — consumes sigint classifications as tags (AGE backend) |
| `ranger` | Tag-based access control policies |
| `kudu` | Columnar storage engine (build from submodule) |
| `impala` | Distributed SQL query engine (HMS-free mode) |
| `impala_fdw` | PostgreSQL FDW → Impala HS2 → **Kudu only** (`weathership/impala_fdw`) |
| `marquez` | OpenLineage **reference UI** (`zndx/oss-marquez`); SoR is Atlas OL extension — **no Marquez DB** |
| `iceberg` | Table format for analytic datasets |
| `airflow` | Workflow orchestration |
| `nifi` | Data flow routing |
| `openph` | Optional reference for CUDA PH (CPU path uses Ripser via `signals.persistence`) |

Build dependencies for C++ components (Kudu, Impala): cmake, ninja, gcc, protobuf, flatbuffers.

## Services

Started together by `devenv up` (process-compose). Impala processes are `lib.mkIf pkgs.stdenv.isLinux` — on Darwin the stack comes up without them, so tier-1 scenarios and live tagging are Linux-only.

| Service | Endpoint / notes |
|---------|------------------|
| PostgreSQL 16 | port **5455**, database `signals` (+ `signals_catalog` registry); extensions Apache AGE (graph), pg_cron, pg_trgm |
| Kerberos KDC | realm `DEV.VISTA.ZNDX.ORG`, host `tinybox.dev.vista.zndx.org`, port 8848 (127.0.0.1); user `signals` (pw `signals`) |
| Atlas | port **21010**, AGE graph backend on PG `signals` / graph `atlas_graph` (OL SoR target) |
| Marquez Web | port **21011** (= Atlas HTTP + 1; default stack; `marquez:build-web` before process + `languages.javascript.npm.install`) |
| Ranger | port **6080** (admin; when configured) |
| Kudu | master webserver 8051, tserver 8050; data under `$SIGNALS_DATA_ROOT/kudu` (default `/raid/signals/kudu`) |
| Impala | HS2 **21050**, beeswax 21001, statestore 24000, catalogd 26000 (HMS-free, config from `config/impala/catalog_config_dir/`), webservers 25000/25010/25020 |

**Data root:** `SIGNALS_DATA_ROOT` (default `/raid/signals`) — siblings `kudu/`, `rustfs/`, `flink/`, `backups/`. See `docs/current/src/operations/storage-and-backup.md`.

**Kerberos required** for Impala + Kudu + backup (no NOSASL path). FQDN SPNs via `$SIGNALS_KRB_HOST`.
Product edge identity: Cloudflare Zero Trust + Okta/GitHub (see Gaius); authz via Atlas → Ranger.
Multi-modal agent UIs (synth WebRTC / omni) assume ZT + HTTPS — `architecture/identity-and-access.md`.

**Backup/restore:** one portable all-services path (`just backup` / `just restore`). Kudu via DataFusion Parquet only.

```bash
just bootstrap                          # KDC keytabs + kinit + .env FQDN (required once)
devenv up -d                            # Start all services (Kerberos processes)
just kinit                              # refresh ticket
just kerberos-status                    # expect: impala HS2 GSSAPI OK
just backup                             # full portable stamp
just restore <stamp>
devenv tasks run signals:catalog-init
psql -p 5455 -d signals
```

## Documentation

mdbook with d2, katex, and mermaid preprocessors.
- Source: `docs/current/src/`
- Config: `docs/current/book.toml`
- Work notes: `docs/scratch/$(date --iso-8601)/` with time-prefixed filenames

Key architecture pages:
- `architecture/context-engineering.md` — 12 features, SAGE importance
- `architecture/classification-training.md` — CatBoost, synthetic data, train→eval
- `architecture/heuristic-elucidation.md` — observation-to-feature methodology
- `architecture/evidence-fusion.md` — DST theory, belief intervals, confidence-gated fusion
- `architecture/bootstrap-agent.md` — LLM convergence loop for novel tables
- `architecture/meta-tagging.md` — SIGDG hierarchy and Atlas projection
- `reference/sigdg-ontology.md` — taxonomy reference
- `reference/research-roadmap.md` — calibration, source independence, confusable pairs

## Deployment Assets

Not part of the classification pipeline, but present at the repo root: `zarf/` (air-gap bundle: charts, images, manifests), `policy/` (k8s + OpenTofu), `infra/` (AWS, benchmarks), `tilt/` + `Tiltfile` (engine dev loop).
