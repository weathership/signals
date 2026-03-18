# Context Engineering

Context engineering is the discipline of deliberately constructing, measuring, and optimizing the input features fed to an embedding classifier. Rather than treating the text assembled from a column's metadata as an ad-hoc string, we decompose it into 11 discrete, ablatable features and use SAGE (Shapley Additive Global importancE) to quantify each feature's contribution to classification accuracy.

The goal: replace intuition about "what information helps the classifier" with measured Shapley values that show exactly which features drive predictions and which are noise.

## The Problem

An embedding classifier that encodes column metadata as free-form text achieves 100% accuracy on the SIGDG training dataset — but 97.7% of correct predictions are assisted by string-matching heuristics (name boost). This means the model relies almost entirely on column name patterns rather than genuine semantic understanding of the column's data characteristics.

To build a classifier that generalizes beyond known column names, we need to:

1. Know which features actually contribute to correct predictions
2. Measure how much accuracy degrades when each feature is removed
3. Systematically reduce reliance on name matching

## Feature Decomposition

Each column is represented by 11 named features extracted from its metadata:

| # | Feature | Source | Example |
|---|---------|--------|---------|
| 1 | `column_name` | Humanized column name | `"payment card number"` |
| 2 | `column_type` | Data type (suppressed for string/varchar) | `"int"` |
| 3 | `sample_values` | Up to 5 sample values, truncated to 80 chars | `"4111..., 5500..."` |
| 4 | `cardinality` | Distinct value count in sample | `"cardinality=42"` |
| 5 | `null_ratio` | null_count / total_count | `"null_ratio=0.15"` |
| 6 | `value_entropy` | Shannon entropy of value lengths (bits) | `"entropy=2.34"` |
| 7 | `pattern_signals` | Detected regex patterns | `"patterns: email_pattern, uuid_pattern"` |
| 8 | `avg_value_length` | Mean character length | `"avg_len=24.5"` |
| 9 | `numeric_ratio` | Fraction parseable as number | `"numeric=0.95"` |
| 10 | `sibling_context` | Humanized names of other columns in same table | `"siblings: first name, last name, email"` |
| 11 | `source_table` | Table name | `"table=identity_data"` |

Features are composed into pipe-separated embedding text via `ColumnFeatures.to_embedding_text(mask)`, where the mask controls which features are included. With all features enabled, a column might produce:

```
payment card number | int | 4111111111111111, 5500000000000004 | cardinality=42 |
  patterns: credit_card_pattern | avg_len=16.0 | numeric=1.00 |
  siblings: first name, last name, expiry date | table=personal_data
```

### Pattern Detectors

Eight regex-based pattern detectors scan sample values for structural signals:

| Pattern | What it matches |
|---------|----------------|
| `email_pattern` | `user@domain.tld` |
| `phone_pattern` | `+1 (555) 123-4567` |
| `ssn_pattern` | `123-45-6789` |
| `ipv4_pattern` | `192.168.1.1` |
| `uuid_pattern` | `550e8400-e29b-41d4-a716-446655440000` |
| `date_iso_pattern` | `2024-01-15` |
| `url_pattern` | `https://example.com` |
| `credit_card_pattern` | `4111111111111111` |

A pattern is flagged when at least 1/3 of sample values match. This threshold prevents spurious matches from a single outlier value.

## SAGE Feature Importance

[SAGE](https://github.com/iancovert/sage) (Shapley Additive Global importancE) measures the global importance of each feature by estimating how much each feature contributes to reducing classification loss. Unlike local explanation methods (LIME, SHAP per-instance), SAGE provides a single importance score per feature across the entire dataset.

### How It Works

SAGE marginalizes each feature by substituting values from other samples in the dataset. For example, when marginalizing `column_name` for column `email`, SAGE asks: "what if this column had the name `trade_secrets` but the same sample values, cardinality, and patterns?"

The implementation:

1. **Feature index matrix**: `X` has shape `(N, 11)` where `X[i, j] = i` — each sample initially uses its own value for every feature.

2. **Value lookup tables**: For each feature `j`, a table maps sample index → feature text. When SAGE permutes `X[i, j]` to index `k`, the model uses sample `k`'s value for feature `j` instead.

3. **Model wrapper** (`FeatureMaskModel`): Looks up text from the per-feature tables according to `X`, assembles embedding text, encodes via sentence-transformers, and returns softmax'd cosine similarities as class probabilities.

4. **SAGE estimation**: `MarginalImputer` + `PermutationEstimator` with cross-entropy loss estimates each feature's Shapley value across `n_permutations` (default 512) random orderings.

The result is a vector of 11 importance values with standard deviations — a quantitative answer to "which features matter?"

## Pipeline

The classification pipeline runs in three stages:

```
Stage 1: Feature Extraction        Stage 2: Classification         Stage 3: Report + SAGE
  ColumnSample                       ColumnFeatures                   RunReport
  + siblings  → ColumnFeatures  →    + method(s)  ────────────→     + accuracy metrics
  + table ctx     (discrete,          cosine / xgboost /             + SAGE importance
                   ablatable)          name_boost                     + JSON + parquet
```

### Ablation Runs

The pipeline supports controlled ablation experiments:

```bash
# Baseline: all features, name boost enabled
uv run python scripts/run_pipeline.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --output build/runs/

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

# SAGE analysis
uv run python scripts/run_pipeline.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --sage --sage-permutations 512 --output build/runs/
```

Each run produces a structured report at `build/runs/<timestamp>/report.json` + `columns.parquet`, enabling comparison across methods, feature sets, and taxonomies.

### Run Reports

The `RunReport` captures everything needed to reproduce and compare experiments:

- **RunConfig**: taxonomy, method, embedding model, threshold, enabled features, name boost flag
- **ColumnResult**: per-column predictions with confidence, boost amount, evidence, and ground truth
- **AccuracyMetrics**: total, correct, wrong, accuracy, boost-assisted count, boost-dependent count, misclassified list
- **SageResult**: per-feature importance values with standard deviations

## Direction

The immediate objective is to drive down the 97.7% boost-assisted rate by strengthening features that carry genuine semantic signal — particularly `sample_values`, `pattern_signals`, and `sibling_context`. SAGE analysis identifies which features to invest in: if disabling `sample_values` barely changes accuracy but disabling `column_name` collapses it, we know the model hasn't yet learned to use data characteristics effectively.

The longer-term path:

1. **Feature refinement** — richer pattern detectors (date formats, currency symbols, statistical distributions), deeper sample analysis (value distributions, min/max/mode)
2. **Training set expansion** — more columns with ambiguous names that require sample-value reasoning
3. **Multi-method comparison** — cosine embedding vs. XGBoost on the same feature set, measured through SAGE
4. **Feedback integration** — analyst corrections feed back as training signal, with SAGE tracking whether corrections improve non-name features
