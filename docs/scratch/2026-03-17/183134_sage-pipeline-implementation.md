# Multi-Stage Classification Pipeline with SAGE Feature Importance

**Date:** 2026-03-17
**Status:** Implementation complete, 131/131 tests passing

## What Was Built

Three-stage pipeline replacing the ad-hoc single-script classification approach:

### New Files (4 source + 3 test)

| File | Purpose |
|------|---------|
| `src/sigint/features.py` | `ColumnFeatures` dataclass (11 named features), `extract_features()`, pattern detectors |
| `src/sigint/sage_analysis.py` | `FeatureMaskModel` (SAGE wrapper), `run_sage_analysis()`, `SageResult` |
| `src/sigint/run_report.py` | `RunReport`, `ColumnResult`, `AccuracyMetrics`, `RunConfig` — JSON + parquet serialization |
| `scripts/run_pipeline.py` | CLI wiring Stages 1-2-3 with `--sage`, `--disable-features`, `--no-name-boost` flags |
| `tests/sigint/test_features.py` | 35 tests: pattern detection, extraction, ablation masks |
| `tests/sigint/test_sage_analysis.py` | 7 tests: FeatureMaskModel, SageResult, integration with real SAGE lib |
| `tests/sigint/test_run_report.py` | 12 tests: JSON round-trip, parquet write, AccuracyMetrics |

### Modified Files (3)

| File | Change |
|------|--------|
| `src/sigint/embedding_classifier.py` | Added `features=` and `feature_mask=` kwargs to `build_embedding_text()` and `classify()`/`_classify_cosine()`. When `features` is provided, delegates to `features.to_embedding_text(mask)`. No change for existing callers. |
| `pyproject.toml` | Added `sage = ["sage-importance>=0.0.6", "numpy>=1.26.0"]` optional dep; added `sage-importance>=0.0.6` to dev group; pinned dev numpy to `>=2.4.3` |
| `devenv.nix` | Added `zlib` to packages (needed by numpy C extensions in pip wheels) |

## 11 Ablatable Features

1. `column_name` — humanized column name ("payment card number")
2. `column_type` — data type when not string/varchar
3. `sample_values` — up to 5 sample values truncated to 80 chars
4. `cardinality` — distinct value count in sample
5. `null_ratio` — null_count / total_count
6. `value_entropy` — Shannon entropy of value lengths
7. `pattern_signals` — detected patterns (email, ssn, ipv4, uuid, etc.)
8. `avg_value_length` — mean character length
9. `numeric_ratio` — fraction parseable as number
10. `sibling_context` — humanized names of other columns in same table
11. `source_table` — table name

## SAGE Integration

- `FeatureMaskModel` wraps the classifier for SAGE's `model(X) → predictions` interface
- Feature matrix X has shape (N, 11) where X[i,j] = sample index (SAGE permutes to marginalize)
- Uses `MarginalImputer` + `PermutationEstimator` with cross-entropy loss
- Ground truth passed as integer class indices (not one-hot)

## Known Issues

- **numpy/zlib in Nix**: `uv sync` replaces Nix-patched numpy wheels with stock manylinux wheels that need `libz.so.1`. Fixed by adding `zlib` to `devenv.nix` packages. Until devenv shell is reloaded, workaround: `LD_LIBRARY_PATH="/nix/store/.../zlib-1.3.1/lib:$LD_LIBRARY_PATH"`

## Pipeline Usage

```bash
# Basic pipeline
uv run python scripts/run_pipeline.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --output build/runs/

# With SAGE analysis
uv run python scripts/run_pipeline.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --sage --sage-permutations 512 --output build/runs/

# Ablation: disable name boost
uv run python scripts/run_pipeline.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --no-name-boost --output build/runs/

# Ablation: disable specific features
uv run python scripts/run_pipeline.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --disable-features sample_values sibling_context \
    --output build/runs/
```

Output per run: `build/runs/<timestamp>/report.json` + `columns.parquet`
