# Context Engineering

Context engineering is the discipline of deliberately constructing, measuring, and optimizing the input features fed to an embedding classifier. Rather than treating the text assembled from a column's metadata as an ad-hoc string, we decompose it into 11 discrete, ablatable features and use SAGE (Shapley Additive Global importancE) to quantify each feature's contribution to classification accuracy.

The goal: replace intuition about "what information helps the classifier" with measured Shapley values that show exactly which features drive predictions and which are noise.

## The Problem

An embedding classifier that encodes column metadata as free-form text achieves high accuracy on well-named data columns — but most correct predictions are assisted by string-matching heuristics (name boost). Annotation columns with opaque numeric identifiers (e.g., `attr_1_1_1_8_1`) expose the model's dependence on column names: cosine similarity drops to 7.4% accuracy on these columns while maintaining 98.9% on semantically named data columns.

To build a classifier that generalizes beyond known column names, we need to:

1. Know which features actually contribute to correct predictions
2. Measure how much accuracy degrades when each feature is removed
3. Systematically reduce reliance on name matching
4. Compare multiple classification methods on the same feature set

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

The classification pipeline runs in four stages, producing a parquet with three independent signals per column:

```d2
direction: right

s1: "Stage 1\nFeature Extraction" {
  tooltip: "ColumnSample + siblings → ColumnFeatures (11 discrete, ablatable features)"
  style.fill: "#e8f4f8"
}

s2: "Stage 2\nClassification" {
  tooltip: "Cosine embedding similarity + name-match boost"
  style.fill: "#e8f4f8"
}

s3: "Stage 3\nGround Truth +\nXGBoost CV" {
  tooltip: "LLM GT evaluation + augmented k-fold cross-validated ML predictions"
  style.fill: "#f0e8f8"
}

s4: "Stage 4\nSAGE + Report" {
  tooltip: "SAGE feature importance (pseudo-GT) + JSON report + parquet output"
  style.fill: "#e8f8e8"
}

csv: "CSV Data\n(all columns)" {
  style.fill: "#fff3e0"
}

gt: "LLM Ground Truth\n(column → code)" {
  style.fill: "#fff3e0"
}

out: "Parquet +\nReport JSON" {
  style.fill: "#fce4ec"
}

csv -> s1: "load_csv_columns"
s1 -> s2: "ColumnFeatures\n+ feature mask"
gt -> s3: "expert mappings"
s2 -> s3: "cosine predictions\n+ embeddings"
s3 -> s4: "three signals\nper column"
s4 -> out: "38 columns\n355 rows"
```

### Three-Signal Comparison

When ground truth is provided (`--ground-truth`), the pipeline produces three independent classification signals per column:

| Signal | Method | Data Columns | Annotation Columns | Overall |
|--------|--------|-------------|-------------------|---------|
| **Cosine** | Zero-shot embedding similarity + name boost | 98.9% | 7.4% | 53.1% |
| **XGBoost** | Augmented stratified k-fold CV | 79.4% | 10.9% | 45.1% |
| **LLM GT** | Expert column→code mapping (target) | — | — | — |

Agreement analysis across 350 GT-labeled columns:

| Category | Count | Interpretation |
|----------|-------|----------------|
| Both correct | 142 | High-confidence predictions |
| Cosine only | 44 | Name semantics sufficient |
| XGBoost only | 16 | ML features find signal cosine misses |
| Both wrong | 148 | Primarily annotation columns lacking semantic signal |

The XGBoost CV uses category reference embedding augmentation to overcome the extreme low-data regime (212 classes, ~2 samples each). Each fold's training set includes all 212 category reference embeddings (the same texts cosine uses as targets), giving at least 2 training points per class even in held-out folds.

### Column Kinds

The pipeline classifies each column into one of three kinds based on naming patterns:

- **data** (175): Semantically named columns (`email`, `first_name`, `amount`) — cosine excels here
- **annotation** (175): Opaque taxonomy-encoded references (`attr_1_1_1_8_1`, `ref_1_1_1_4_2_1_1`) — both methods struggle
- **row_id** (5): Row identifiers — excluded from GT evaluation

### Ablation Runs

The pipeline supports controlled ablation experiments:

```bash
# Three-signal comparison with LLM ground truth
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --ground-truth config/sigint/meta_tagging_gt.json \
    --output build/sigint_embeddings.parquet

# Feature ablation (disable specific features)
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --disable-features sample_values sibling_context \
    --output build/sigint_ablation.parquet

# With SAGE feature importance
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --sage-permutations 512 \
    --output build/sigint_embeddings.parquet

# Visualize with embedding-atlas
embedding-atlas build/sigint_embeddings.parquet --text embedding_text
```

### Output Schema

Each run produces a parquet (38 columns) and companion report JSON:

| Column Group | Columns | Description |
|-------------|---------|-------------|
| Identity | `embedding_text`, `source_table`, `column_name`, `sample_values`, `column_kind` | Column metadata and kind |
| Cosine | `tag_code`, `tag_label`, `tag_abbrev`, `confidence`, `boost` | Zero-shot cosine predictions |
| Ground Truth | `gt_code`, `correct` | LLM GT evaluation (when provided) |
| XGBoost CV | `ml_tag_code`, `ml_tag_label`, `ml_confidence`, `ml_correct` | Cross-validated ML predictions |
| Features | `feat_column_name` ... `feat_source_table` (×11) | Transparency: input features as strings |
| SAGE | `sage_column_name` ... `sage_source_table` (×11) | Global feature importance values |

## Direction

The three-signal comparison reveals a clear split: cosine embedding similarity dominates on semantically named data columns (98.9%) but fails on opaque annotation columns (7.4%). XGBoost CV shows marginal improvement on annotation columns (10.9%) but cannot match cosine on data columns (79.4%). The 148 columns where both methods fail are almost entirely annotation references — columns whose names encode taxonomy codes rather than semantic meaning.

The path forward:

1. **Annotation column signal** — annotation columns contain taxonomy codes as values (e.g., `1.1.1.1.1.1.1`). A dedicated annotation-aware classifier that decodes these suffixes could close the 90% gap on annotation columns
2. **Feature refinement** — richer pattern detectors (date formats, currency symbols, statistical distributions), deeper sample analysis (value distributions, min/max/mode)
3. **Training set expansion** — more columns with ambiguous names that require sample-value reasoning, and real-world datasets where column names don't match known taxonomy entries
4. **Ensemble methods** — the 16 columns where XGBoost is correct and cosine is wrong suggest a hybrid approach could push overall accuracy above either method alone
5. **Feedback integration** — analyst corrections feed back as training signal, with SAGE tracking whether corrections improve non-name features
