# Classification Training

The classification pipeline's CatBoost train→eval mode trains on synthetic data and evaluates on real data. This page documents the synthetic data generator, the training pipeline, and the techniques that bridge the domain shift between synthetic and real columns.

> **Note**: CatBoost replaced XGBoost in March 2026. CatBoost's ordered boosting (`posterior_sampling=True`) eliminates the self-training target leakage identified in the integrity audit. See the [CatBoost migration](#catboost-migration) section for details.

## Why Synthetic Training

Real datasets typically exhibit extreme data scarcity: many leaf categories with only a few samples each. K-fold cross-validation in this regime produces poor accuracy because each fold's training set has at most 1-2 examples per class.

A second challenge is the **opaque name problem**. Columns with generic or positional names (e.g., `col0`, `field_42`) carry no semantic signal. Cosine similarity achieves high accuracy on semantically named columns but fails on opaque names — the classifier depends on column names, not value patterns.

Synthetic training data addresses both problems: it generates thousands of columns per category with controlled name diversity, and half the synthetic columns use opaque names, forcing CatBoost to learn from value patterns rather than column names.

## Synthetic Data Generator

`scripts/generate_meta_tagging_train.py` generates wide-format CSV training data for all leaf categories in the target taxonomy.

### Name Generation

Each category produces two kinds of synthetic column names:

**Semantic names** use a synonym table (~60 terms with abbreviations and variants) to generate diverse human-readable names. Techniques include:
- Case variants: `snake_case`, `camelCase`, `UPPER_SNAKE_CASE`
- Synonym expansion: `phone` → `tel`, `ph`, `phn`
- Word-dropping: `payment_card_number` → `payment_number`, `card_number`
- Prefixed variants: `user_`, `primary_`, `customer_`, `acct_`, `src_`, `raw_`

**Opaque names** use 13 prefix templates (`field_`, `col_`, `meta_`, `var_`, etc.) with random numeric/alphabetic suffixes, mimicking generic column naming patterns found in real databases.

Each category generates a 50/50 split: half semantic-name columns, half opaque-name columns.

### Value Generators

70+ generator functions cover all SIGDG leaf categories across the full taxonomy:

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
  ├── ground_truth.json                  (column → SIGDG code)
  └── taxonomy.csv                       (copy of controlled vocabulary)
```

CSV headers use `table.column` format (e.g., `synth_001.credit_card_number`) matching the eval data's convention.

## Train/Eval Pipeline

The `--train-dir` flag in `build_sigint_embeddings.py` activates train→eval mode. The pipeline applies four techniques that collectively raise accuracy from a 33.4% naive baseline to 83.1%.

### Feature Vector

Each column is represented by a 992-dimensional feature vector:

```
[full_emb(384) | value_only_emb(384) | discrete(12) | cosine_sims(212)]
```

| Component | Dimensions | Description |
|-----------|-----------|-------------|
| Full embedding | 384 | Sentence embedding of all features (name + values + table + siblings) |
| Value-only embedding | 384 | Sentence embedding with name, table, and siblings stripped |
| Discrete features | 12 | Cardinality, null ratio, entropy, 8 pattern flags, value description — scaled by \\(\sqrt{384/12}\\) |
| Cosine similarities | N | Similarity between value-only embedding and each category reference |

### Dual Embedding

The full embedding encodes everything including column name and table context — strong for columns with semantic names. The value-only embedding strips `column_name`, `source_table`, and `sibling_context`, encoding only value patterns, cardinality, entropy, and detected patterns. This bridges the domain shift for columns with opaque or generic names.

### Category Reference Augmentation

All taxonomy reference embeddings (the same texts cosine similarity uses as targets) are included as training samples. These anchor embeddings exist in the same embedding space as the real eval data, teaching CatBoost the mapping from embedding regions to categories even when synthetic embeddings differ from real ones.

### Cosine Similarity Features

For each column, the pipeline computes cosine similarity between the column's value-only embedding and each category reference embedding. These per-category similarity features encode the cosine classifier's knowledge in a domain-invariant way (category references are identical for training and evaluation).

### Discrete Feature Scaling

The 12 discrete features (cardinality, null ratio, entropy, 8 pattern flags, value description) are multiplied by \\(\sqrt{384/12} \approx 5.7\\) so their magnitude competes with the 384-dimensional embedding vectors. Without scaling, gradient boosting ignores the discrete features because individual embedding dimensions dominate split gain.

### Paired Column Propagation

A post-prediction pass exploits structural column relationships in the dataset. When CatBoost is uncertain about one column (confidence < 0.50) but confident about a structurally related column (confidence ≥ 0.35), the confident prediction propagates to the uncertain one. This is a dataset-specific heuristic — the particular structural relationship varies by dataset (see [Heuristic Elucidation](./heuristic-elucidation.md)).

### StandardScaler

The full feature vector is normalized with `StandardScaler` before CatBoost training for stable gradient boosting across features with different scales.

## Results

Accuracy progression on a GT-labeled evaluation set, showing each technique's marginal contribution:

| Technique | Overall | Data Cols | Ann Cols |
|-----------|---------|-----------|---------|
| Baseline (k-fold CV) | 48.0% | — | — |
| Cosine-only (5-source DST) | 84.6% | — | — |
| Synthetic train→eval + dual embedding | 83.1% | 88.0% | 78.3% |
| SVM standalone (TF-IDF) | 84.6% | — | — |
| **Self-train (GT injection)** | **99.4%** | **99.4%** | **99.4%** |

The naive k-fold CV (48.0%) cannot learn with ~2 examples per class. Synthetic training data + dual embedding (full + value-only) provides the largest gain. Column propagation corrects 43 annotation columns where CatBoost is uncertain but the preceding data column is confident. Self-training injects GT-labeled evaluation columns into the CatBoost training set, raising accuracy from 83.1% to 99.4% — legitimate for the LLM annotation reproduction workflow (see [Self-Training Mode](#self-training-mode)).

**Validated numbers** (2026-03-24, GPU-accelerated): CatBoost standalone (dual embedding + cosine sims + ordered boosting + propagation) achieves 83.1% (291/350, data=88.0%, ann=78.3%). CatBoost with self-training: **99.4% (348/350, data=99.4%, ann=99.4%)** — only 2 residual errors, both in the Masked PAN category. SVM standalone: 84.6% (296/350). SAGE analysis: 489s on GPU vs 13,278s on CPU (27x speedup). CatBoost requires CPU for `posterior_sampling=True` and `rsm=0.6` (not supported on CatBoost GPU for multiclass).

**SVM text format fix** (2026-03-24): The SVM text format mismatch (SVM trained on short `name | type | values` but evaluated on full 12-feature text) has been fixed. `EmbeddingClassifier._build_svm_text()` now ensures consistent short text format between training and inference. 5-source DST accuracy corrected from 60.6% to 84.6%.

## Discovery Methodology

Each technique in the accuracy progression was discovered through benchmark observation, not designed a priori. Dual embedding emerged from observing that opaque-name columns fail because names are uninformative. Category reference augmentation emerged from the observation that many classes with few samples each is insufficient for gradient boosting. Column propagation emerged from noticing exploitable structural relationships between columns in the dataset.

This pattern — observe a phenomenon, hypothesize a mechanism, implement it as a feature, and measure its contribution with SAGE — is the [heuristic elucidation](./heuristic-elucidation.md) methodology. SAGE Shapley values quantify each technique's marginal contribution, and cross-benchmark validation (against [GitTables CTA](./heuristic-elucidation.md#cross-benchmark-validation)) prevents overfitting to a single dataset.

## CatBoost Migration

CatBoost replaced XGBoost in March 2026 for two reasons:

### 1. Self-Training Redesign

The XGBoost pipeline included an implicit self-training step that injected cosine pseudo-labels (confidence ≥ 0.50) from evaluation data into the training set. For benchmark evaluation (where test/train splits matter), this constituted target leakage. The implicit self-training was removed and replaced with an explicit, opt-in `--self-train` mode (see [Self-Training Mode](#self-training-mode)) for the LLM annotation reproduction workflow where it is legitimate.

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

### SHAP Explanations

The pipeline computes per-item feature explanations using CatBoost's built-in TreeSHAP (\\(O(TLD)\\) complexity). For each classified column, the top 3 most influential feature groups are reported:

| Column | Feature Group | Description |
|--------|--------------|-------------|
| `shap_top1_name` | Feature group name | e.g., `full_embedding`, `sample_values`, `column_name` |
| `shap_top1_value` | SHAP magnitude | Summed absolute SHAP value for the feature group |

CatBoost's 992-dimensional feature space is grouped into interpretable categories: `full_embedding` (384 dims), `value_only_embedding` (384 dims), and 11 discrete features (`column_name`, `sample_values`, `cardinality`, `null_ratio`, `entropy`, `pattern_*`, `value_description`, `sibling_context`) plus cosine similarities. SHAP values within each group are summed to produce a single importance score.

Disable SHAP with `--no-shap` for faster runs that skip the TreeSHAP computation.

### Remaining Errors

Remaining errors cluster in confusable category pairs where values are structurally identical — for example, two hex identifier types or two address subtypes that share the same format. These are registered as [confusable pairs](./evidence-fusion.md#restricted-focal-set) in the DST frame so that mass flows to the pair rather than forcing an arbitrary leaf choice.

These pairs cannot be distinguished by value patterns alone — resolution requires richer context (table-level schema, data dictionary, or category consolidation).

## Self-Training Mode

The `--self-train` flag activates self-training, where GT-labeled evaluation data is injected into the CatBoost training set. Off by default.

### When Self-Training is Legitimate

The primary workflow for this pipeline is **LLM annotation reproduction**:

1. An LLM provides initial column classifications (the "ground truth")
2. ML models learn to reproduce those LLM annotations transparently
3. The ML pipeline provides explainability, reproducibility, and measured feature importance

In this workflow, self-training is **not** target leakage — the LLM annotations ARE the ground truth to learn. The ML pipeline's goal is highly accurate recreation of the LLM-provided mappings.

### Validated Results

Self-training (1 round, direct GT injection) achieves **99.4% (348/350)** — only 2 residual errors, both in the Masked PAN category (one opaque annotation column confused with Security Question at 0.039 confidence, one data column confused with PAN India at 0.050 confidence). Training set: 7,684 synthetic + 212 reference + 348 GT-injected = 8,244 samples. Pipeline wall clock: 68 minutes (CatBoost CPU training dominates).

### When Self-Training is Illegitimate

For **benchmark evaluation** (test/train splits measuring generalization to unseen data):

- **Do NOT use `--self-train`** — this inflates accuracy metrics
- The default mode (no self-training) maintains strict train/test separation
- All published benchmark accuracy numbers use the default mode

### Multi-Round Refinement

With `--self-train-rounds N` (N > 1), the pipeline iterates:

1. **Round 1:** Inject all GT-labeled eval columns with their LLM labels
2. **Round 2+:** Inject columns whose CatBoost confidence exceeds `--self-train-threshold` (default 0.80) using CatBoost's predicted labels as pseudo-labels
3. Repeat until no new columns qualify or round limit reached

Embedding encoding happens once before the loop — only CatBoost training repeats per round.

## Commands

### Single-command workflow (recommended)

The `--auto-generate` flag inlines the synthetic data generator, producing a single command that generates training data, trains CatBoost, classifies, computes SHAP explanations, and writes the output parquet:

```bash
uv run python scripts/build_sigint_embeddings.py \
    --data-dir <data-dir> \
    --taxonomy <taxonomy> --threshold 0.25 \
    --ground-truth <ground-truth.json> \
    --auto-generate --variants-per-category 50 \
    --output build/sigint_shap_eval.parquet
```

The output parquet includes all classification columns plus item-wise SHAP explanations (`shap_top{1,2,3}_{name,value}`), suitable for visualization with `embedding-atlas`.

### Two-step workflow

For iterating on the synthetic generator separately:

```bash
# Step 1: Generate synthetic training data
uv run python scripts/generate_meta_tagging_train.py \
    --data-dir <data-dir> \
    --output-dir build/datasets/sigint_train/ \
    --variants-per-category 50

# Step 2: Train→eval pipeline
uv run python scripts/build_sigint_embeddings.py \
    --data-dir <data-dir> \
    --taxonomy <taxonomy> --threshold 0.25 \
    --ground-truth <ground-truth.json> \
    --train-dir build/datasets/sigint_train/ \
    --output build/sigint_embeddings.parquet
```

### Self-training (LLM reproduction mode)

```bash
# Direct GT injection — learn the LLM's mapping
uv run python scripts/build_sigint_embeddings.py \
    --data-dir <data-dir> --taxonomy <taxonomy> \
    --ground-truth <ground-truth.json> \
    --auto-generate --self-train \
    --output build/sigint_self_train.parquet

# Multi-round refinement (3 rounds, 85% confidence threshold)
uv run python scripts/build_sigint_embeddings.py \
    --data-dir <data-dir> --taxonomy <taxonomy> \
    --ground-truth <ground-truth.json> \
    --auto-generate --self-train \
    --self-train-rounds 3 --self-train-threshold 0.85 \
    --output build/sigint_self_train_3r.parquet
```

### Other commands

```bash
# Disable SHAP (faster, skips TreeSHAP computation)
uv run python scripts/build_sigint_embeddings.py \
    --data-dir <data-dir> --taxonomy <taxonomy> \
    --ground-truth <ground-truth.json> \
    --auto-generate --no-shap \
    --output build/sigint_eval.parquet

# Run tests
uv run pytest tests/sigint/test_generate_train.py -v
```
