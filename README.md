# signals-360

Uncertainty-aware column classification for metadata governance.

Signals-360 classifies database columns into a hierarchical taxonomy using [Dempster-Shafer evidence fusion](docs/current/src/architecture/evidence-fusion.md), producing belief intervals rather than point confidence scores. The pipeline combines four independent evidence sources — embedding similarity, CatBoost gradient boosting, pattern detection, and name matching — and uses [SAGE](docs/current/src/architecture/context-engineering.md) (Shapley Additive Global importancE) to measure each feature's contribution to accuracy.

Classifications feed into Apache Atlas for governance tagging and Apache Ranger for tag-based access control.

## Quick Start

```bash
# Enter the development environment
devenv shell

# Run tests (363 tests)
uv run pytest tests/sigint/ -v

# Classify columns with DST belief intervals
uv run python scripts/build_sigint_embeddings.py \
    --data-dir <data-dir> \
    --taxonomy <taxonomy> --threshold 0.25 \
    --ground-truth <ground-truth.json> \
    --dst \
    --output build/sigint_dst.parquet

# Build and serve documentation
devenv tasks run docs:serve
```

## Architecture

The classification pipeline runs in stages, each documented in the [mdbook](docs/current/src/SUMMARY.md):

1. **[Feature Extraction](docs/current/src/architecture/context-engineering.md)** — 12 discrete, ablatable features per column
2. **[Classification Training](docs/current/src/architecture/classification-training.md)** — CatBoost on synthetic data, SIGDG taxonomy
3. **[Evidence Fusion](docs/current/src/architecture/evidence-fusion.md)** — Dempster-Shafer belief intervals with conflict diagnostics
4. **[Heuristic Elucidation](docs/current/src/architecture/heuristic-elucidation.md)** — Systematic observation-to-feature methodology, validated across benchmarks

Two operational modes drive development:

- **External benchmarks** — [GitTables CTA](scripts/evaluate_gittables.py) (2517 columns, 122 DBpedia types) tests generalization on public data
- **Internal synthetic data** — [70+ value generators](scripts/generate_meta_tagging_train.py) covering all SIGDG leaf categories train CatBoost for evaluation

## Project Structure

```
src/sigint/               20 Python modules — classification pipeline
scripts/                   Pipeline runners, benchmarks, data generation
tests/sigint/              363 tests across 16 test files
config/sigint/             Taxonomy definitions and ground truth
docs/current/src/          mdbook documentation (d2 diagrams, KaTeX math)
docs/scratch/              Dated work notes with experimental results
components/                ASF submodules (Atlas, Ranger, Kudu, Impala, Iceberg)
```

## License

Apache 2.0
