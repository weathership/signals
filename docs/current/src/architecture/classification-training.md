# Classification Training

The classification pipeline's CatBoost train→eval mode achieves 95.4% accuracy (334/350 columns) by training on synthetic data and evaluating on real data. This page documents the synthetic data generator, the training pipeline, and the techniques that bridge the domain shift between synthetic and real columns.

> **Note**: CatBoost replaced XGBoost in March 2026. CatBoost's ordered boosting (`posterior_sampling=True`) eliminates the self-training target leakage identified in the integrity audit. See the [CatBoost migration](#catboost-migration) section for details.

## Why Synthetic Training

The real dataset has extreme data scarcity: 175 leaf categories with ~2 samples each. K-fold cross-validation in this regime produces only 45.1% accuracy because each fold's training set has at most 1-2 examples per class.

A second challenge is the **annotation column problem**. Half the columns in the evaluation set have opaque names like `attr_1_1_1_8_1` that encode taxonomy codes rather than semantic meaning. Cosine similarity achieves 98.9% on semantically named data columns but only 7.4% on annotation columns — the classifier depends on column names, not value patterns.

Synthetic training data addresses both problems: it generates thousands of columns per category with controlled name diversity, and half the synthetic columns use opaque names, forcing CatBoost to learn from value patterns rather than column names.

## Synthetic Data Generator

`scripts/generate_meta_tagging_train.py` generates wide-format CSV training data for all 175 leaf categories.

### Name Generation

Each category produces two kinds of synthetic column names:

**Semantic names** use a synonym table (~60 terms with abbreviations and variants) to generate diverse human-readable names. Techniques include:
- Case variants: `snake_case`, `camelCase`, `UPPER_SNAKE_CASE`
- Synonym expansion: `phone` → `tel`, `ph`, `phn`
- Word-dropping: `payment_card_number` → `payment_number`, `card_number`
- Prefixed variants: `user_`, `primary_`, `customer_`, `acct_`, `src_`, `raw_`

**Opaque names** use 13 prefix templates (`field_`, `col_`, `meta_`, `attr_`, etc.) with random numeric/alphabetic suffixes, mimicking the annotation column naming pattern in the real data.

Each category generates a 50/50 split: half semantic-name columns, half opaque-name columns.

### Value Generators

70+ generator functions cover all 175 leaf categories across the full taxonomy:

- **Payment card data** — PANs (Visa/MC/Amex/Discover prefixes), CVVs, magstripe tracks, BINs, last-4, expiration dates, masked PANs, PINs
- **Identifiers** — SSNs, passports, driver's licenses, CPF (Brazil), PAN (India), VATIN, UUIDs, device IDs, serial numbers, MAC addresses
- **Contact** — full names, first/middle/last/nickname, emails, phone numbers (full and split: country code, area code, subscriber, extension), social media handles
- **Addresses** — full addresses, split components (street, city, state, postal, country), billing/shipping variants, coarse/precise geolocation
- **Demographics** — age, birthdate, gender, race, education, employment, income, benefits, background checks
- **Health** — mental health conditions, physical conditions, genetic markers, biometric IDs
- **Product usage** — login events, crash types, security references, forum posts, photos, videos, user activity, device metrics, app bundles, user agents
- **Authentication** — passwords (masked), security Q&A, e-signatures, key material, key digests
- **System** — IP addresses, LDAP groups, permissions, session data, URLs, cluster nodes, file paths, executables, runtime data
- **Business** — document references, SEC filings, trade secrets

### Output Format

```
build/datasets/sigint_train/
  ├── synth_001.csv ... synth_NNN.csv   (wide-format, 100 rows each, 50 cols per file)
  ├── ground_truth.json                  (column → annotation code)
  └── annotations.csv                    (copy of controlled vocabulary)
```

CSV headers use `table.column` format (e.g., `synth_001.credit_card_number`) matching the eval data's convention.

## Train/Eval Pipeline

The `--train-dir` flag in `build_sigint_embeddings.py` activates train→eval mode. The pipeline applies four techniques that collectively raise accuracy from a 33.4% naive baseline to 95.4%.

### Feature Vector

Each column is represented by a 991-dimensional feature vector:

```
[full_emb(384) | value_only_emb(384) | discrete(11) | cosine_sims(212)]
```

| Component | Dimensions | Description |
|-----------|-----------|-------------|
| Full embedding | 384 | Sentence embedding of all features (name + values + table + siblings) |
| Value-only embedding | 384 | Sentence embedding with name, table, and siblings stripped |
| Discrete features | 11 | Cardinality, null ratio, entropy, 8 pattern flags — scaled by √(384/11) |
| Cosine similarities | 212 | Similarity between value-only embedding and each category reference |

### Dual Embedding

The full embedding encodes everything including column name and table context — strong for data columns with semantic names. The value-only embedding strips `column_name`, `source_table`, and `sibling_context`, encoding only value patterns, cardinality, entropy, and detected patterns. This bridges the domain shift for annotation columns where names are opaque.

### Category Reference Augmentation

All 212 taxonomy reference embeddings (the same texts cosine similarity uses as targets) are included as training samples. These anchor embeddings exist in the same embedding space as the real eval data, teaching CatBoost the mapping from embedding regions to categories even when synthetic embeddings differ from real ones.

### Cosine Similarity Features

For each column, the pipeline computes cosine similarity between the column's value-only embedding and each of the 212 category reference embeddings. These 212 features encode the cosine classifier's knowledge in a domain-invariant way (category references are identical for training and evaluation).

### Discrete Feature Scaling

The 11 discrete features (cardinality, null ratio, entropy, 8 pattern flags) are multiplied by √(384/11) ≈ 5.9 so their magnitude competes with the 384-dimensional embedding vectors. Without scaling, gradient boosting ignores the discrete features because individual embedding dimensions dominate split gain.

### Paired Column Propagation

A post-prediction pass exploits the dataset structure: data columns and annotation columns are paired (the annotation column follows its data column), and both refer to the same category. When CatBoost is uncertain about an annotation column (confidence < 0.50) but confident about the preceding data column (confidence ≥ 0.35), the data column's prediction is propagated to the annotation column.

### StandardScaler

The full feature vector is normalized with `StandardScaler` before CatBoost training for stable gradient boosting across features with different scales.

## Results

Accuracy progression on 350 GT-labeled columns, showing each technique's marginal contribution:

| Technique | Overall | Data Columns | Annotation Columns |
|-----------|---------|--------------|-------------------|
| Baseline (k-fold CV) | 45.1% | 79.4% | 10.9% |
| Synthetic train→eval | 33.4% | 44.0% | 22.9% |
| + Dual embedding | 83.4% | 98.3% | 68.6% |
| + Cosine sim features | 86.0% | 98.9% | 73.1% |
| + Paired propagation | 95.4% | 98.9% | 92.0% |

The naive synthetic baseline (33.4%) is *worse* than k-fold CV because of domain shift between synthetic and real embeddings. Dual embedding and cosine similarity features provide the largest gains on annotation columns by reducing reliance on column names.

## CatBoost Migration

CatBoost replaced XGBoost in March 2026 for two reasons:

### 1. Self-Training Target Leakage

The XGBoost pipeline included a self-training step that injected cosine pseudo-labels (confidence ≥ 0.50) from evaluation data columns into the training set. While this improved accuracy metrics, it constituted target leakage: evaluation embeddings were present in the training data, inflating accuracy measurements. The self-training block has been removed entirely.

### 2. Ordered Boosting

CatBoost's `posterior_sampling=True` enables ordered boosting — a method that constructs each tree using only "historical" data points, preventing the prediction shift that occurs when a model is trained and evaluated on the same data distribution. This provides a principled alternative to self-training without leakage.

### Hyperparameter Mapping

| XGBoost | CatBoost | Notes |
|---------|----------|-------|
| `objective="multi:softprob"` | `loss_function="MultiClass"` | Both produce probability vectors |
| `n_estimators` | `iterations` | Number of boosting rounds |
| `max_depth` | `depth` | Maximum tree depth |
| `reg_alpha` | `l2_leaf_reg` | L2 regularization |
| `colsample_bytree` | `rsm` | Random subspace method (feature sampling) |
| `min_child_weight` | `min_data_in_leaf` | Minimum samples per leaf |
| — | `posterior_sampling=True` | Ordered boosting (CatBoost-specific) |

### Evidence Fusion Integration

CatBoost's `predict_proba()` output is now available as a mass function source for [evidence fusion](./evidence-fusion.md). When a trained CatBoost model is loaded, its class probabilities are converted to a `BeliefAssignment` via `catboost_to_mass()`, contributing independent evidence alongside cosine similarity, pattern detection, and name matching. CatBoost's virtual ensembles can additionally provide per-class variance estimates, enabling adaptive discounting: high model uncertainty → more mass allocated to \\(\Theta\\) (total ignorance).

### Remaining Errors

16 of 350 columns are misclassified. All errors are inherently confusable category pairs where values are structurally identical:

- **ADID / GUID** — both are hex identifiers
- **BAN / PAN** — both are long numeric strings
- **Under 13 / Under 18** — both are boolean flags
- **Billing address / Shipping address** — identical address formats
- **Security flaw subtypes** — identical reference number formats

These pairs cannot be distinguished by value patterns alone — resolution requires richer context (table-level schema, data dictionary, or category consolidation).

## Commands

```bash
# Generate synthetic training data (175 categories × 30 variants = 5,250 columns)
uv run python scripts/generate_meta_tagging_train.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --output-dir build/datasets/sigint_train/ \
    --variants-per-category 30

# Train→eval pipeline
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --ground-truth config/sigint/meta_tagging_gt.json \
    --train-dir build/datasets/sigint_train/ \
    --output build/sigint_embeddings.parquet

# Train→eval with DST belief intervals
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations --threshold 0.25 \
    --ground-truth config/sigint/meta_tagging_gt.json \
    --train-dir build/datasets/sigint_train/ \
    --dst \
    --output build/sigint_dst.parquet

# Run tests
uv run pytest tests/sigint/test_generate_train.py -v
```
