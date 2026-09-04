# signals-360

Uncertainty-aware column classification for metadata governance.

Signals-360 classifies database columns into a hierarchical taxonomy using [Dempster-Shafer evidence fusion](docs/current/src/architecture/evidence-fusion.md), producing belief intervals rather than point confidence scores. The pipeline combines four independent evidence sources — embedding similarity, CatBoost gradient boosting, pattern detection, and name matching — and uses [SAGE](docs/current/src/architecture/context-engineering.md) (Shapley Additive Global importancE) to measure each feature's contribution to accuracy.

Classifications feed into Apache Atlas for governance tagging and Apache Ranger for tag-based access control.

## Quick Start

```bash
# Enter the development environment
devenv shell

# Resolve config (materializes build/config/sigint.env from HOCON + .env)
just resolve-config

# Run tests (includes preflight config validation)
just test

# Classify columns with DST belief intervals
just build-embeddings \
    --data-dir <data-dir> \
    --taxonomy sigdg --threshold 0.25 \
    --output build/sigint_embeddings.parquet
```

## Configuration

All pipeline configuration flows through [HOCON](https://github.com/lightbend/config/blob/main/HOCON.md) (`config/base.conf`). Environment variables are captured by HOCON via `${?VAR}` substitution — application code never reads `os.environ` directly.

```
.env (user overrides)  ─┐
                        ├─> HOCON resolves ${?VAR} ─> PipelineConfig ─> application code
config/base.conf ───────┘                                  │
                                                   materialize_config()
                                                           │
                                                build/config/sigint.env
                                             (flat key=value for shell/just)
```

**Setup:**

1. Copy `.env.example` to `.env` and uncomment values to override defaults
2. Run `just resolve-config` to materialize the resolved config
3. Run `just preflight` to validate all required keys are present

The materialized `build/config/sigint.env` is the serialized, fully-resolved config. It is consumed by `just` recipes and can be sourced by shell scripts after `env -i`. Tests automatically validate it via a conftest preflight check.

**Precedence:** CLI args > `.env` / env vars > `config/base.conf` defaults

## Architecture

The classification pipeline runs in stages, each documented in the [mdbook](docs/current/src/SUMMARY.md):

1. **[Feature Extraction](docs/current/src/architecture/context-engineering.md)** — 12 discrete, ablatable features per column
2. **[Classification Training](docs/current/src/architecture/classification-training.md)** — CatBoost on synthetic data, SIGDG taxonomy
3. **[Evidence Fusion](docs/current/src/architecture/evidence-fusion.md)** — Dempster-Shafer belief intervals with conflict diagnostics
4. **[Heuristic Elucidation](docs/current/src/architecture/heuristic-elucidation.md)** — Systematic observation-to-feature methodology, validated across benchmarks

Two operational modes drive development:

- **External benchmarks** — [GitTables CTA](scripts/evaluate_gittables.py) (2517 columns, 122 DBpedia types) tests generalization on public data
- **Internal synthetic data** — [70+ value generators](scripts/generate_meta_tagging_train.py) covering all SIGDG leaf categories train CatBoost for evaluation

### Supervision: Nautilus (planned)

Every Signals project that runs a signals-protocol engine is expected to host its own local [Nautilus](https://github.com/weathership/nautilus) instance — the model-free supervisor that validates the project's `zndx.supervision.v1` instance and observes its declared workflows from outside the engine's trust boundary (cadences, nets, resource intents, and the Operations Backlog state table in Fibonacci-hour slots). The engine communicates with its local Nautilus and Nautilus with its engine; the engine propagates Nautilus messages across the federated engine mesh over signals-protocol peer messaging, so peers observe peers without any cross-engine ledger writes. signals-360 does not host a Nautilus instance yet; the gaius instance is the reference deployment.

## Project Structure

```
config/base.conf          HOCON config — single source of truth
.env.example              Template for user overrides
build/config/sigint.env   Materialized resolved config (gitignored)
Justfile                  Pipeline recipes (just resolve-config, just test, ...)
src/sigint/               20 Python modules — classification pipeline
scripts/                  Pipeline runners, benchmarks, data generation
tests/                    363 tests + conftest preflight validation
config/sigint/            Taxonomy definitions and ground truth
docs/current/src/         mdbook documentation (d2 diagrams, KaTeX math)
docs/scratch/             Dated work notes with experimental results
components/               ASF submodules (Atlas, Ranger, Kudu, Impala, Iceberg)
```

## License

Apache 2.0
