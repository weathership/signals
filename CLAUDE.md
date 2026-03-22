# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

signals-360 — uncertainty-aware column classification for metadata governance. Licensed Apache 2.0.

The primary workflow is the **sigint classification pipeline**: a Python package that classifies database columns into a hierarchical taxonomy using Dempster-Shafer evidence fusion, CatBoost gradient boosting, and SAGE feature importance analysis. Classifications feed downstream into Apache Atlas for governance tagging and Ranger for policy enforcement.

## Primary Workflow

### sigint Classification Pipeline

The `src/sigint/` package (20 modules) implements a multi-stage classification pipeline:

1. **Feature Extraction** — 12 discrete, ablatable features extracted from column metadata (name, type, sample values, cardinality, entropy, pattern signals, value description, etc.)
2. **Embedding Classification** — Sentence-transformer embeddings (MiniLM-L6, 384-dim) with cosine similarity to taxonomy reference embeddings
3. **CatBoost Training** — Gradient boosting on 992-dim feature vectors (dual embedding + discrete features + cosine similarities), trained on synthetic data or cross-validated
4. **DST Evidence Fusion** — Dempster-Shafer Theory combines 4 independent evidence sources (cosine, CatBoost, pattern detection, name matching) into belief intervals [Bel, Pl] with conflict diagnostics
5. **SAGE Analysis** — Shapley Additive Global importancE measures each feature's marginal contribution to accuracy

### Two Operational Modes

**External benchmarks** test generalization on public datasets:
```bash
# Download GitTables CTA benchmark (2517 columns, 122 DBpedia types)
uv run python scripts/download_gittables_benchmark.py --output-dir build/datasets/gittables/

# Evaluate against ground truth
uv run python scripts/evaluate_gittables.py \
    --data-dir build/datasets/gittables/ \
    --output build/gittables_eval.parquet
```

**Internal synthetic data** trains and evaluates on the SIGDG taxonomy (175 leaf categories):
```bash
# Generate synthetic training data (70+ value generators, 50/50 semantic/opaque names)
uv run python scripts/generate_meta_tagging_train.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --output-dir build/datasets/sigint_train/ \
    --variants-per-category 30

# Train→eval pipeline (95.4% accuracy on 350 GT-labeled columns)
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --ground-truth config/sigint/meta_tagging_gt.json \
    --train-dir build/datasets/sigint_train/ \
    --output build/sigint_embeddings.parquet

# With DST belief intervals
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --ground-truth config/sigint/meta_tagging_gt.json \
    --train-dir build/datasets/sigint_train/ \
    --dst \
    --output build/sigint_dst.parquet
```

### Key Source Files

| File | Purpose |
|------|---------|
| `src/sigint/features.py` | 12 SAGE-ablatable features + pattern detectors |
| `src/sigint/embedding_classifier.py` | Embedding classification + DST orchestration |
| `src/sigint/belief.py` | Dempster-Shafer mass functions and combination |
| `src/sigint/mass_functions.py` | Evidence-to-mass converters (cosine, CatBoost, pattern, name) |
| `src/sigint/classifier.py` | HierarchicalClassification with belief intervals |
| `src/sigint/sage_analysis.py` | SAGE feature importance with GPU acceleration |
| `src/sigint/confusable_pairs.py` | Known ambiguous category pairs (ADID/GUID, BAN/PAN) |
| `src/sigint/category_set.py` | Taxonomy-agnostic category sets (SIGDG + GitTables) |
| `scripts/build_sigint_embeddings.py` | Full pipeline: features → classification → CatBoost → SAGE |
| `scripts/generate_meta_tagging_train.py` | Synthetic column generator (175 categories, 70+ value generators) |
| `config/sigint/gittables_taxonomy.py` | BFO-grounded GitTables taxonomy (122 types) |

## Development Environment

Uses [devenv](https://devenv.sh/) (Nix-based) with direnv for automatic shell activation.

- **Enter the dev shell:** `devenv shell` (or automatic via direnv)
- **Start all services:** `devenv up` (PostgreSQL + Kerberos KDC + Atlas + Kudu + Impala)
- **Run devenv tests:** `devenv test`

Key files:
- `devenv.nix` — packages, services, processes, tasks, and shell configuration
- `devenv.yaml` — Nix inputs configuration
- `.envrc` — direnv integration

### Languages
- **Python 3.12** — primary language; `uv` for package management
- **Java 21** — ASF component builds (Maven)
- **Rust** — planned gRPC engine (not yet implemented)

## Build and Test Commands

```bash
# Run all sigint tests (363 tests)
uv run pytest tests/sigint/ -v

# Run specific test modules
uv run pytest tests/sigint/test_features.py -v
uv run pytest tests/sigint/test_belief.py tests/sigint/test_mass_functions.py -v

# Run SAGE analysis with feature importance
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --sage-permutations 512 \
    --output build/sigint_embeddings.parquet

# Build mdbook documentation
devenv tasks run docs:build

# Serve docs with live reload
devenv tasks run docs:serve
```

### ASF Components (submodules in `components/`)

All tracked on `rch/signals` branch from `rch` GitHub forks:

| Component | Purpose |
|-----------|---------|
| `atlas` | Metadata governance — consumes sigint classifications as tags |
| `ranger` | Tag-based access control policies |
| `kudu` | Columnar storage engine |
| `impala` | Distributed SQL query engine (HMS-free mode) |
| `iceberg` | Table format for analytic datasets |
| `airflow` | Workflow orchestration |
| `nifi` | Data flow routing |

Build dependencies for C++ components (Kudu, Impala): cmake, ninja, gcc, protobuf, flatbuffers.

## Services

### PostgreSQL 16
- **Extensions:** Apache AGE (graph queries), pg_cron (scheduled jobs), pg_trgm (fuzzy search)
- **Database:** `signals` (created automatically)
- Managed by `services.postgres` in devenv — starts automatically with `devenv up`

### Kerberos KDC
- **Realm:** `KRBTEST.COM`
- **KDC port:** `8848` (127.0.0.1)
- **Principals:** `postgres/localhost`, `signals` (password: `signals`)

### Common Commands
```
devenv up                               # Start all services
devenv tasks run signals:kdc-init       # Initialize/verify KDC
psql -d signals                         # Connect to database
kinit signals                           # Get Kerberos ticket (pw: signals)
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
- `reference/research-roadmap.md` — calibration, source independence, confusable pairs
