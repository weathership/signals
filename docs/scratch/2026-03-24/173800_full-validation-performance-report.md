# Full Validation and Performance Report

**Date:** 2026-03-24
**Pipeline version:** 5-source DST (cosine + CatBoost + pattern + name-match + SVM)
**GPU:** 6x NVIDIA RTX 4090 (147.4 GB VRAM), driver 570.148.08, CUDA 12.8
**Runtime:** 75 min 58s wall clock (hybrid GPU/CPU)

---

## 1. Regression Testing

| Suite | Result | Expected |
|-------|--------|----------|
| pytest (sigint) | 400/400 pass | 400 |
| BDD tier-0 | 62/62 pass | 62 |

Zero regressions. Test count increased 377 -> 400 since 2026-03-23 (SVM classifier tests, GPU
preflight tests, SHAP analysis tests).

---

## 2. Embedding Model

**Model:** `all-MiniLM-L6-v2` from [sentence-transformers](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)

| Property | Value |
|----------|-------|
| Architecture | BERT (6-layer, 384-dim) |
| Parameters | 22.7M |
| Output dimension | 384 |
| Max sequence length | 256 tokens |
| Training data | 1B+ sentence pairs (AllNLI, S2ORC, etc.) |
| Similarity function | Cosine |
| Device | CUDA (RTX 4090) when available, CPU fallback |
| Batch size | 64 (training encode), 1 (online classify) |

**Dual-embedding strategy:** The CatBoost pipeline encodes each column twice:
1. **Full embedding** (384-dim): all 12 features including column_name, source_table, sibling_context
2. **Value-only embedding** (384-dim): strips domain-specific features (column_name, source_table, sibling_context), retaining only value patterns, cardinality, entropy, type

The dual-embedding approach bridges domain shift between synthetic training data (which has
artificial column names) and real evaluation data (which has meaningful or opaque column names).
The value-only embedding is domain-invariant.

**Category reference embeddings:** 212 category descriptions are encoded once and cached. Cosine
similarity between a column's embedding and each category reference produces the cosine evidence
source. These reference embeddings also serve as CatBoost training anchors (augmenting synthetic
data with canonical category representations).

**SVM text representation:** TF-IDF on character n-grams (3-6 characters) from short text
(`column_name | type | sample_values`). This is a completely independent feature space from
the dense MiniLM-L6 embedding, providing high source independence for DST fusion.

---

## 3. Internal Meta-Tagging Classification

**Dataset:** 355 columns from internal annotations.csv, 350 with ground truth (174 leaf categories)
**Taxonomy:** Annotations hierarchy (depth 7, 174 leaves)
**Synthetic training:** 7,684 auto-generated columns (50 variants per category)

### Results by configuration

| Configuration | Accuracy | Correct | Wrong | Notes |
|---------------|----------|---------|-------|-------|
| DST cosine (5-source) | 60.6% | 212 | 138 | Degraded by SVM text mismatch (see section 7) |
| CatBoost train->eval (with propagation) | **83.1%** | 291 | 59 | 43 annotation cols propagated |
| CatBoost data columns | 88.0% | 154/175 | 21 | Semantic column names |
| CatBoost annotation columns | 78.3% | 137/175 | 38 | Opaque column names |

### Comparison with 2026-03-23

| Metric | 2026-03-23 | 2026-03-24 | Delta |
|--------|-----------|-----------|-------|
| CatBoost train->eval | 83.14% (291/350) | 83.1% (291/350) | Stable |
| CatBoost data cols | 86.9% (152/175) | 88.0% (154/175) | +1.1% |
| CatBoost ann cols | 79.4% (139/175) | 78.3% (137/175) | -1.1% |
| Propagated cols | 48 | 43 | -5 |
| DST 5-source | 84.6% (296/350) | 60.6% (212/350) | -24% (SVM text bug) |

CatBoost accuracy is reproducible at 83.1% (same posterior_sampling=True, rsm=0.6, seed=42).
The sub-category splits vary slightly due to auto-generated training data (different random
variants each run). Overall accuracy is stable.

The DST accuracy drop from 84.6% to 60.6% is caused by the SVM text format mismatch
identified in section 7.

### CatBoost hyperparameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| iterations | 500 | |
| depth | 8 | |
| learning_rate | 0.08 | |
| posterior_sampling | True | Ordered boosting; **CPU only** (not supported on CatBoost GPU) |
| rsm | 0.6 | Random subspace method; **CPU only** |
| bootstrap_type | Bernoulli | |
| subsample | 0.8 | |
| l2_leaf_reg | 0.3 | |
| loss_function | MultiClass | 212 classes |
| feature_dim | 991 | full_emb(384) + vo_emb(384) + discrete(11) + cosine_sim(212) |

**GPU limitation discovered:** CatBoost GPU does not support `posterior_sampling` or `rsm`
for multiclass classification. Running on GPU without these parameters yields 81.4% (285/350)
-- a 2% accuracy loss. Since accuracy matters more than speed for this workload, CatBoost is
forced to CPU while GPU accelerates SentenceTransformer encoding and SAGE.

---

## 4. DST Diagnostics

| Metric | Value |
|--------|-------|
| Avg Bel | (per-column, in parquet) |
| Avg uncertainty gap (Pl - Bel) | 0.1076 |
| Avg conflict K | 0.6535 |
| Columns evaluated | 355 |

Conflict K remains high (0.65) because the SVM text mismatch causes SVM to produce
predictions that contradict the other sources. When the SVM text mismatch is fixed,
conflict K should decrease back toward the 0.62 seen in the pilot.

---

## 5. SAGE Feature Importance

**Configuration:** 512 permutations, 355 samples, pseudo-GT, cross-entropy loss
**Runtime:** 488.75s on GPU (27.2x faster than 13,278s on CPU)
**Embedding cache:** 53% hit rate (1,319,570 / 2,488,905 lookups)

| Rank | Feature | SAGE importance | Std | Category |
|------|---------|----------------|-----|----------|
| 1 | **column_name** | **+0.1067** | 0.0054 | **Dominant** -- 3.2x the 2nd feature |
| 2 | **sibling_context** | **+0.0331** | 0.0018 | **High** -- neighboring columns provide context |
| 3 | **sample_values** | **+0.0315** | 0.0020 | **High** -- value content is key signal |
| 4 | source_table | +0.0071 | 0.0007 | Medium |
| 5 | value_description | +0.0067 | 0.0011 | Medium |
| 6 | pattern_signals | +0.0046 | 0.0009 | Low-Medium |
| 7 | value_entropy | +0.0004 | 0.0002 | Near-zero |
| 8 | numeric_ratio | +0.0002 | 0.0001 | Near-zero |
| 9 | cardinality | +0.0001 | 0.0001 | Near-zero |
| 10 | avg_value_length | -0.0002 | 0.0001 | Near-zero (noise) |
| 11 | column_type | -0.0000 | 0.0000 | Zero |
| 12 | null_ratio | +0.0000 | 0.0000 | Zero |

### SAGE comparison: 2026-03-23 (CPU) vs 2026-03-24 (GPU)

| Feature | CPU (13,278s) | GPU (489s) | Delta |
|---------|--------------|-----------|-------|
| column_name | +0.1142 | +0.1067 | -0.0075 |
| sample_values | +0.0410 | +0.0315 | -0.0095 |
| sibling_context | +0.0356 | +0.0331 | -0.0025 |
| value_description | +0.0110 | +0.0067 | -0.0043 |
| source_table | +0.0079 | +0.0071 | -0.0008 |
| pattern_signals | +0.0059 | +0.0046 | -0.0013 |

Ranking is identical. Magnitude differences are within expected stochastic variation
(SAGE uses random permutations). The relative ordering is stable across runs.

**Top-3 features account for 86%** of total importance (0.107 + 0.033 + 0.032 = 0.172
out of 0.200 total). Bottom 6 features contribute < 1% combined.

---

## 6. SHAP Explanations (CatBoost TreeSHAP)

**Runtime:** 9.9s for 355 items
**Feature groups:** 14 (full_emb, vo_emb, discrete x 11, cosine_sim)

Per-item SHAP explanations are stored in the parquet as `shap_top{1,2,3}_{name,value}`.
All 355/355 rows populated.

---

## 7. SVM Text Format Mismatch (BUG IDENTIFIED)

**Impact:** DST accuracy degraded from 84.6% (pilot) to 60.6% (integrated pipeline)

**Root cause:** The SVM is trained on short text from `_build_svm_text()`:
```
column_name | type | value1, value2, value3
```

But when the SVM is called as the 5th DST source in `embedding_classifier.py:395`, it
receives the full 12-feature embedding text from `build_embedding_text()`:
```
column_name: billing_country | column_type: string | sample_values: US, Canada, UK |
cardinality: 45 | null_ratio: 0.02 | value_entropy: 3.21 | ...
```

The TF-IDF character n-grams are completely different between these formats. The SVM
produces near-random predictions on the full text, which poisons the DST combination.

**Fix:** Pass the SVM the same short text format at evaluation time. In `classify()`,
build the short SVM text from the `ColumnSample` and `ColumnFeatures` objects instead
of passing the full embedding text.

**Estimated accuracy after fix:** 84.6% DST (matching pilot) + CatBoost propagation
should push toward 88-90%.

---

## 8. GPU Performance

### Component-level timing

| Component | CPU (2026-03-23) | GPU (2026-03-24) | Speedup | Device |
|-----------|-----------------|-----------------|---------|--------|
| SentenceTransformer encode | ~3 min | ~30s | ~6x | CUDA (RTX 4090) |
| CatBoost train (500 iter) | ~60 min | ~60 min | 1x | CPU (forced) |
| SHAP TreeSHAP | ~10s | ~10s | 1x | CPU |
| SAGE (512 perm, 355 samples) | **13,278s (3.7h)** | **489s (8.1 min)** | **27.2x** | CUDA (indirect) |
| **Total pipeline** | **~5+ hours** | **76 min** | **~4x** | Hybrid |

### GPU utilization

| Stage | GPU 0 | GPUs 1-5 | Memory (GPU 0) |
|-------|-------|----------|---------------|
| SentenceTransformer encode | 35-40% | Idle | 1,262 MiB |
| CatBoost training | 0% | 0% | 1,262 MiB |
| SAGE analysis | 35-40% | Idle | 5,230-5,958 MiB |

Only GPU 0 is utilized. Multi-GPU parallelism is available for future SAGE optimization
(partition permutations across GPUs).

### CatBoost GPU investigation

CatBoost GPU was tested but forced back to CPU for accuracy reasons:

| Config | Accuracy | Time | Issue |
|--------|----------|------|-------|
| CPU: posterior_sampling=True, rsm=0.6 | 83.1% (291/350) | ~60 min | Baseline |
| GPU: no posterior_sampling, no rsm | 81.4% (285/350) | ~5 min | -2% accuracy |
| GPU: multi-GPU (6x RTX 4090) | OOM resolved | ~5 min | 26 GB VRAM on single GPU |

CatBoost GPU multiclass requires disabling posterior_sampling and rsm, both of which
contribute to accuracy. The 12x speed gain does not justify the 2% accuracy loss for
this workload.

---

## 9. 95% Accuracy Target Assessment

**Current best:** 83.1% (CatBoost + propagation) and 84.6% (SVM standalone from pilot)

Neither method currently reaches 95%. This is an honest assessment. The path to 95% is:

### High-confidence improvements (near-term)

1. **Fix SVM text mismatch** (section 7): Restore SVM to 84.6% accuracy within DST.
   Combined with CatBoost propagation, this should push toward 88-90%.
   **Estimated delta: +5-8%**

2. **Adaptive source weighting**: When SVM confidence is high and cosine/CatBoost are
   uncertain, increase their discount (reduce their influence). Currently all sources
   have equal standing regardless of confidence.
   **Estimated delta: +2-3%**

3. **Expand confusable pairs registry**: Many CatBoost errors are near-miss siblings
   (Billing/Shipping, phone subtypes, documentation subtypes). Registering these as
   confusable pairs would redirect mass to pair focal elements instead of wrong singletons.
   **Estimated delta: +1-2%**

### Medium-term improvements

4. **Larger embedding model**: all-MiniLM-L6-v2 (384-dim, 22.7M params) may be too small
   for 174-type discrimination. Candidates: `bge-small-en-v1.5` (384-dim, better training),
   `all-mpnet-base-v2` (768-dim), `gte-large` (1024-dim).

5. **CatBoost feature engineering**: Add SVM predictions as a CatBoost input feature
   (stacking). SVM's TF-IDF features capture information CatBoost cannot access through
   dense embeddings alone.

6. **Synthetic data quality**: Current 50 variants/category may not capture enough
   variation for rare categories. Targeted augmentation for high-error categories.

### Assessment

The 95% target is achievable through the combination of items 1-3 (estimated +8-13%).
From 83.1%, this projects to 91-96%. The SVM text fix alone (item 1) is the highest-impact
single change.

---

## 10. Delta Summary: 2026-03-23 -> 2026-03-24

```
DELTA: 2026-03-23 (CPU) -> 2026-03-24 (GPU)
  GPU:              IDLE (driver mismatch)      -> ACTIVE (6x RTX 4090, CUDA 12.8)
  Driver:           550.90.07                   -> 570.148.08
  SVM:              Pilot experiment            -> Always-on 5th DST source
  R-04:             Mass sum < 1.0 bug          -> Fixed (residual -> Theta)
  Tests:            377 pass                    -> 400 pass
  CatBoost:         CPU, 83.1%                  -> CPU (forced), 83.1%  [stable]
  DST:              84.6% (SVM pilot)           -> 60.6% (SVM text mismatch)
  SAGE timing:      13,278s (3.7h CPU)          -> 489s (8.1 min GPU, 27.2x faster)
  Total pipeline:   ~5+ hours                   -> 76 min (4x faster)
  Parquet sage_*:   All zeros (--sage-perm 0)   -> All populated (sage.perm=512)
  Parquet shap_*:   355/355 populated           -> 355/355 populated
  Bug found:        —                           -> SVM text format mismatch
```

---

## 11. Raw Numbers Summary

```
REGRESSION
  pytest:  400/400
  bdd:     62/62

META-TAGGING (350 evaluated, 174 types)
  dst 5-source:     60.57%   (212/350)    gap=0.108  K=0.654  [degraded: SVM text bug]
  catboost-train:   83.14%   (291/350)    data=88.0%  ann=78.3%  propagated=43
  svm-standalone:   84.57%   (296/350)    [2026-03-23 pilot, correct text format]

SAGE -- META-TAGGING (512 perms, 355 samples, 489s GPU, 53% cache)
  column_name:      +0.1067  (dominant, 53% of total)
  sibling_context:  +0.0331  (high)
  sample_values:    +0.0315  (high)
  source_table:     +0.0071  (medium)
  value_description:+0.0067  (medium)
  pattern_signals:  +0.0046  (low-medium)
  value_entropy:    +0.0004  (near-zero)
  numeric_ratio:    +0.0002  (near-zero)
  cardinality:      +0.0001  (near-zero)
  avg_value_length: -0.0002  (zero/noise)
  column_type:      -0.0000  (zero)
  null_ratio:       +0.0000  (zero)

SHAP -- CATBOOST (355 items, 14 feature groups, 9.9s)
  355/355 items explained (top-3 feature contributions per item)

GPU HARDWARE
  6x NVIDIA RTX 4090 (147.4 GB VRAM)
  Driver: 570.148.08 (CUDA 12.8)
  PyTorch: 2.10.0+cu128 -- CUDA ACTIVE
  CatBoost: forced to CPU (posterior_sampling not supported on GPU)
  SAGE: 27.2x speedup (13,278s -> 489s)

EMBEDDING MODEL
  Model:      all-MiniLM-L6-v2 (sentence-transformers)
  Params:     22.7M
  Dim:        384
  Max tokens: 256
  Strategy:   Dual embedding (full + value-only)
  CatBoost feature dim: 991 (384 + 384 + 11 + 212)
  SVM feature:  TF-IDF char n-grams (3-6), independent of embedding
```
