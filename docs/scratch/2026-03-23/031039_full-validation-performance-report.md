# Full Validation and Performance Report

**Date:** 2026-03-23
**Pipeline version:** 5-source DST (cosine + CatBoost + pattern + name-match + SVM)
**Embedding model:** all-MiniLM-L6-v2 (384-dim)

---

## 1. Regression Testing

| Suite | Result | Expected |
|-------|--------|----------|
| pytest (sigint) | 377/377 pass | 377 |
| BDD tier-0 | 62/62 pass | 62 |

Zero regressions after SVM fifth evidence source integration.

---

## 2. GitTables CTA Benchmark

**Dataset:** 2517 columns, 122 DBpedia types (public benchmark)

### Results by configuration

| Configuration | Accuracy | micro-F1 | Mean Bel | Mean Pl-Bel gap | Mean K |
|---------------|----------|----------|----------|-----------------|--------|
| Cosine-only (no CatBoost) | 1.63% | 0.0163 | 0.121 | 0.266 | 0.118 |
| CatBoost + 4-source DST | **71.39%** | 0.7139 | 0.511 | 0.102 | 0.652 |
| CatBoost + DST (no name match) | **71.55%** | 0.7155 | 0.520 | 0.104 | 0.626 |

### SOTA comparison

| System | Accuracy |
|--------|----------|
| Archetype (GPT-4) | 86% |
| ChatGPT | 85% |
| **sigint (CatBoost + DST)** | **71.4%** |
| SemTab 2021 winner | 59% |
| sigint (cosine-only) | 1.6% |

### Analysis

- **CatBoost is the dominant source** on GitTables. Cosine similarity alone is catastrophically
  poor (1.6%) because MiniLM-L6 embeddings cannot discriminate 122 fine-grained DBpedia types
  without supervised signal. CatBoost trained on the benchmark training split rescues accuracy
  to 71.4%.
- **Name matching contributes nothing** on GitTables. The no-name-match variant (71.55%) is
  marginally *better* than with name-match (71.39%), confirming that GitTables column names
  don't follow naming conventions the matcher was designed for.
- **High conflict (K=0.65)** across all GitTables DST runs. With cosine providing near-random
  signal while CatBoost provides strong signal, Dempster's combination rule produces high
  inter-source conflict. This is expected and actually correct behavior — conflict K is an
  honest measure of source disagreement.
- **macro-F1 is very low (0.19)** despite high micro-F1 (0.71). This indicates the model
  performs well on common types but poorly on rare ones — a long-tail distribution problem
  typical of CTA benchmarks with 122+ types.

---

## 3. Internal Meta-Tagging Classification

**Dataset:** 355 columns from internal annotations.csv, 350 with ground truth (174 leaf categories)
**Taxonomy:** Annotations hierarchy (depth 7, 174 leaves)

### Results by configuration

| Configuration | Accuracy | Correct | Wrong |
|---------------|----------|---------|-------|
| Cosine-only | 53.7% | 188 | 162 |
| CatBoost (5-fold CV) | 48.0% | 168 | 182 |
| 4-source DST (cosine + CatBoost + pattern + name-match) | 53.7% | 188 | 162 |
| SVM standalone | **84.6%** | 296 | 54 |
| 5-source DST (+ SVM) | **84.6%** | 296 | 54 |

### DST diagnostics

| Metric | 4-source | 5-source | Delta |
|--------|----------|----------|-------|
| Accuracy | 53.7% | 84.6% | **+30.9%** |
| Avg conflict K | 0.234 | 0.620 | +0.386 |
| Avg uncertainty gap (Pl-Bel) | 0.240 | 0.101 | -0.139 |
| Columns fixed by SVM | — | 110 | — |

### Error pattern analysis

**Cosine-only (162 errors):**
- Clear bifurcation between semantic and opaque column names
- Semantic names (e.g., `personal_data.masked_payment_card_number`): correctly classified
  with ~0.42 confidence
- Opaque names (e.g., `identity_data.attr_1_1_2_2_1_3`): uniformly wrong with ~0.006
  confidence
- All opaque-name errors predict the same few high-prior categories (PASSPORT, PANLAST4,
  BIN, VENDORID) — the model defaults to the most common training exemplars

**CatBoost (182 errors):**
- CatBoost performs *worse* than cosine alone (48% vs 53.7%)
- Training data (synthetic, 7684 samples, 174 classes) may be too sparse per class
  (~44 samples/class) for gradient boosting to learn discriminative boundaries
- Cross-validated ML accuracy below cosine indicates the discrete features (cardinality,
  entropy, type) don't compensate for the loss of raw embedding similarity

**SVM (54 errors):**
- SVM dramatically outperforms both cosine and CatBoost
- TF-IDF on character n-grams (3-6) captures subword structure in opaque column names
  (e.g., `attr_1_1_2_2_1_3` → character trigrams encode positional hierarchy)
- Most remaining errors are semantically confusable pairs:
  - Documentation subtypes (Financial/Technical/Product/HR/Incident)
  - Phone number subtypes (Home/Office/Mobile/Other/Fax)
  - Billing/Shipping address variants
  - Security flaw subtypes (General/SourceCode/0-day)
  - Device identifiers (UDID/ICCID/IMEI/SEID/MEI)

---

## 4. Feature Space Assessment

### Evidence source independence

| Source pair | Shared features | Independence |
|------------|----------------|--------------|
| Cosine ↔ CatBoost | MiniLM-L6 embedding (384-dim) | **Low** — both consume the same dense embedding |
| Cosine ↔ SVM | None | **High** — cosine uses dense embedding, SVM uses sparse TF-IDF |
| CatBoost ↔ SVM | None (CatBoost uses embedding+discrete, SVM uses TF-IDF) | **High** |
| Pattern ↔ all | Regex matches on values | **High** — entirely different feature type |
| Name-match ↔ all | String matching on column name | **High** — but very low signal on opaque names |

### Source effectiveness ranking (meta-tagging)

| Rank | Source | Standalone accuracy | Notes |
|------|--------|-------------------|-------|
| 1 | **SVM** | 84.6% | Dominant source; TF-IDF character n-grams capture hierarchical code structure |
| 2 | **Cosine** | 53.7% | Effective for semantic names, useless for opaque |
| 3 | **CatBoost** | 48.0% | Underperforms cosine; insufficient training data per class |
| 4 | **Pattern** | ~10% | Only fires for email, phone, SSN, IP patterns — narrow coverage |
| 5 | **Name-match** | ~5% | Only fires for exact/abbreviation matches — near-zero on opaque names |

### Source effectiveness ranking (GitTables)

| Rank | Source | Contribution | Notes |
|------|--------|-------------|-------|
| 1 | **CatBoost** | Dominant | 1.6% → 71.4% accuracy delta; dense features essential for 122-type discrimination |
| 2 | **Cosine** | Marginal | Near-random alone (1.6%); softmax over 122 types is too diffuse |
| 3 | **Name-match** | Zero | Column names in GitTables don't match DBpedia type labels |
| 4 | **Pattern** | Minimal | Few GitTables columns contain regex-matchable patterns |
| 5 | **SVM** | Not tested | SVM not yet integrated into GitTables pipeline |

### Key finding: source dominance is dataset-dependent

The two datasets reveal opposite source rankings:
- **Meta-tagging (opaque names, 174 types):** SVM dominates because character n-gram features
  capture hierarchical code structure that embeddings miss
- **GitTables (semantic names, 122 types):** CatBoost dominates because gradient boosting on
  embeddings + discrete features discriminates fine-grained semantic types that cosine alone cannot

This implies the pipeline needs **adaptive source weighting** — the discount/weight for each
source should depend on the characteristics of the input data, not be fixed globally.

---

## 5. SVM Pilot Evaluation

### Success criteria assessment

| Criterion | Target | Result | Status |
|-----------|--------|--------|--------|
| Marginal DST improvement > 5-8% on uncertain cases | >5% | +30.9% | **PASS** (exceeds by 6x) |
| No increase in average conflict K | 0 | +0.386 | **FAIL** |
| Lower correlation with cosine/CatBoost | measurable | Yes (TF-IDF vs embedding) | **PASS** |

### Conflict K analysis (RED FLAG)

The 5-source conflict K increase (0.234 → 0.620) violates the "no increase" criterion.
Root cause: SVM provides **strong, correct** signal that directly contradicts the **weak,
incorrect** signal from cosine and CatBoost on opaque-name columns. Dempster's rule
correctly identifies this as conflict.

**This is not a bug — it's a design tension.** High conflict K means the sources genuinely
disagree, and the SVM is right while the others are wrong. Options:

1. **Accept high conflict as honest:** The conflict measure is working correctly —
   it tells us the 4-source ensemble was confidently wrong on these columns
2. **Discount weaker sources more:** Increase the discount (Theta allocation) for
   cosine and CatBoost when they produce low-confidence predictions
3. **Adaptive discounting:** Use SVM confidence to dynamically adjust other sources'
   discounts — when SVM is highly confident, discount cosine/CatBoost more heavily
4. **Remove CatBoost on meta-tagging:** CatBoost actively hurts accuracy on this dataset
   (48% < 53.7% cosine alone); its mass contribution adds noise

### SVM error clusters (54/350 wrong)

| Cluster | Count | Example pairs |
|---------|-------|---------------|
| Documentation subtypes | 6 | Financial↔Incident, Technical↔Product, HR↔Product |
| Phone number subtypes | 5 | Home↔Other, Office↔Home, Mobile↔Office |
| Billing↔Shipping | 4 | BillingAddr↔ShippingAddr, BillingState↔ShippingState |
| Security flaw subtypes | 2 | General↔SourceCode |
| Device identifier subtypes | 5 | UDID↔SEID, IMEI↔ICCID, MEI↔SEID |
| Cross-domain confusion | 12 | CVV2↔ShellCommands, CreditScore↔AreaCode, IPAddr↔SystemIPs |
| Miscellaneous | 20 | Various fine-grained leaf confusion |

---

## 6. SAGE Feature Importance

**Empirical results:** 512 permutations, 355 samples, pseudo-GT, cross-entropy loss.
Runtime: 13,278 seconds (3.7 hours) on CPU. Embedding cache: 52% hit rate
(1,296,814 / 2,488,905 lookups, 1,192,091 unique encodes).

| Rank | Feature | SAGE importance | Std | Category |
|------|---------|----------------|-----|----------|
| 1 | **column_name** | **+0.1142** | 0.0053 | **Dominant** — 5.3x the 2nd feature |
| 2 | **sample_values** | **+0.0410** | 0.0022 | **High** — value content is the 2nd signal |
| 3 | **sibling_context** | **+0.0356** | 0.0019 | **High** — neighboring columns provide strong context |
| 4 | **value_description** | +0.0110 | 0.0012 | Medium — LLM-generated summaries add modest signal |
| 5 | **source_table** | +0.0079 | 0.0006 | Medium — table-level context |
| 6 | **pattern_signals** | +0.0059 | 0.0009 | Low-Medium — regex matches (email, phone, SSN) |
| 7 | value_entropy | +0.0009 | 0.0003 | Near-zero |
| 8 | numeric_ratio | +0.0001 | 0.0001 | Near-zero |
| 9 | cardinality | +0.0001 | 0.0000 | Near-zero |
| 10 | avg_value_length | -0.0001 | 0.0001 | Near-zero (slightly negative = noise) |
| 11 | column_type | -0.0000 | 0.0000 | Zero |
| 12 | null_ratio | -0.0000 | 0.0000 | Zero |

### Analysis

- **column_name is overwhelmingly dominant** (+0.114, 52% of total importance). This confirms
  that the embedding model's primary discriminative signal comes from column names. When the
  column name is semantic (e.g., `salary`, `date_of_birth`), the model classifies correctly
  with high confidence. When opaque (e.g., `attr_1_1_1_8_2`), the model defaults to
  high-prior categories.

- **Top-3 features account for 88%** of total importance (0.114 + 0.041 + 0.036 = 0.191
  out of 0.217 total). This is a very concentrated importance distribution.

- **sibling_context outperforms value_description** (+0.036 vs +0.011). Neighboring column
  names provide more context than LLM-generated value summaries. This suggests the
  embedding model benefits more from structural context (what's next to this column?)
  than from semantic value descriptions.

- **Bottom 6 features are effectively dead weight** (importance < 0.001). column_type,
  null_ratio, cardinality, avg_value_length, and numeric_ratio contribute nothing to
  cosine classification accuracy. These features may still be valuable for CatBoost
  (which can exploit nonlinear interactions), but for the embedding-based classifier,
  they're noise.

- **pattern_signals has modest value** (+0.006). Despite narrow coverage (only fires for
  email, phone, SSN, IP patterns), regex matches provide genuine signal when they fire.
  Coverage-limited but precision-positive.

### GitTables SAGE comparison

SAGE also completed on the GitTables benchmark (2517 columns, 122 types, 512 permutations).
Cache: 65% hit rate (11.7M/18M), 6.4M unique encodes.

| Feature | Meta-Tagging | GitTables | Insight |
|---------|-------------|-----------|---------|
| column_name | +0.114 | +0.081 | Dominant in both |
| sample_values | +0.041 | +0.026 | High in both |
| **sibling_context** | **+0.036** | **+0.001** | **Dataset-dependent:** high when columns share a table, near-zero for isolated columns |
| value_description | +0.011 | +0.000 | Only helps with rich annotations |
| source_table | +0.008 | +0.000 | Only helps within unified datasets |
| pattern_signals | +0.006 | +0.005 | Consistent across datasets |
| cardinality | +0.000 | **+0.003** | Discrete features matter more on GitTables |
| numeric_ratio | +0.000 | **+0.003** | Same pattern |
| column_type | -0.000 | **+0.003** | Same pattern |

**Key finding:** Feature importance is dataset-dependent. Structural context (sibling_context,
source_table) helps when columns come from the same table. Discrete features (cardinality,
numeric_ratio, column_type) help when discriminating 122 fine-grained types. This reinforces
the adaptive source weighting recommendation.

### CatBoost train→eval accuracy (new)

The full pipeline with synthetic training data achieved **83.1%** (291/350):
- Data columns: **86.9%** (152/175)
- Annotation columns: **79.4%** (139/175)
- 48 annotation columns corrected by paired column propagation
- 59 misclassified columns (down from 162 cosine-only)

---

## 7. Recommendations

### Immediate (pre-production)

1. **Promote SVM to default-enabled** — The +30.9% accuracy gain is overwhelming. Accept
   the conflict K increase as honest disagreement measurement.

2. **Add CatBoost disable switch for small taxonomies** — CatBoost hurts accuracy when
   training data is sparse (<50 samples/class). For the internal annotations taxonomy
   (174 classes, ~44 samples/class), CatBoost should be disabled.

3. **Wire `SIGINT_ANNOTATIONS_PATH` through HOCON** — Currently passed as a bare env var
   to the SVM pilot. This violates the project config principle that all env vars flow
   through HOCON → `build/config/sigint.env`.

4. **Move device detection to preflight/HOCON** — `_detect_device()` in
   `embedding_classifier.py` probes `torch.cuda.is_available()` at runtime. Device
   selection should happen in preflight, set via HOCON (`embedding.device`), and flow
   through `PipelineConfig`. Runtime code should not probe hardware.

   **GPU inventory:** 6x NVIDIA GeForce RTX 4090 (147.4 GB total VRAM), all idle at 0%
   utilization during this entire SAGE analysis. Root cause: PyTorch 2.10.0+cu128 bundles
   CUDA 12.8 runtime, but driver 550.90.07 only supports CUDA 12.4. Fix: install
   `torch+cu124` to match the driver, or upgrade driver to 555+. Preflight should detect
   this mismatch and fail loudly rather than silently falling back to CPU.

5. ~~**Remove `--dst` flag references**~~ — **DONE.** Cleaned up in CLAUDE.md and all
   docs/current/ architecture pages. DST is always-on, no flag needed.

6. **Add progress indicators for long-running operations** — SAGE, CatBoost training,
   and sentence-transformer encoding all suppress progress output (`bar=False`,
   `verbose=0`, `show_progress_bar=False`). Users will wait days for results if they
   see proof of forward progress, but will abort a silent multi-hour job. At minimum:
   - Enable SAGE's built-in progress bar (`bar=True`)
   - Log periodic CatBoost training iteration counts
   - Log SAGE permutation count + cache hit rate every N permutations
   - Emit estimated time remaining based on elapsed/completed ratio

### Short-term (R-01 follow-up)

4. **Confidence-gated discounting** — When a source produces max singleton probability
   below a threshold (e.g., 0.1), increase its discount toward 1.0 (vacuous). This would
   reduce conflict K without losing accuracy.

5. **SVM integration into GitTables pipeline** — Test whether SVM provides additional
   signal on the GitTables benchmark where CatBoost already dominates.

6. **Expand confusable pairs registry** — The SVM error clusters reveal new confusable
   pairs not yet registered: Documentation subtypes (6 pairs), phone subtypes (10 pairs),
   device identifier subtypes (10 pairs).

### Short-term (infrastructure)

7. **Fix CUDA version mismatch** — Install `torch+cu124` (matching driver 550.90.07's
   CUDA 12.4 support) or upgrade NVIDIA driver to 560+ for CUDA 12.8. Current
   `torch 2.10.0+cu128` silently falls back to CPU on all 6x RTX 4090s.

8. **Enable GPU P2P transfers** — RTX 4090 has P2P disabled by default (NVIDIA consumer
   product segmentation). Install tiny corp's patched kernel module
   (`tinygrad/open-gpu-kernel-modules`, branch `550.90.07-p2p`) to enable 24 GB/s
   GPU-to-GPU bandwidth. Required for efficient multi-GPU SAGE and distributed
   training. Compatible with NCCL/PyTorch `torch.distributed`.
   Requires: `iommu=off` kernel boot parameter.

### Medium-term (research roadmap)

9. **Adaptive source weighting** — The dataset-dependent source dominance finding suggests
   a meta-learning approach: use input characteristics (name opacity, taxonomy depth,
   training set size) to set per-source discounts.

10. **Larger embedding model** — MiniLM-L6 (384-dim) may be too small for 122+ type
   discrimination. Evaluate bge-small-en-v1.5 (384-dim, better training) or
   all-mpnet-base-v2 (768-dim) on both datasets.

---

## 8. Raw Numbers Summary

```
REGRESSION
  pytest:  377/377
  bdd:     62/62

GITTABLES (2517 columns, 122 types)
  cosine-only:     1.63%    (41/2517)
  catboost+dst:   71.39%  (1796/2517)   mean_bel=0.511  gap=0.102  K=0.652

META-TAGGING (350 evaluated, 174 types)
  cosine-only:    53.71%   (188/350)
  catboost-cv:    48.00%   (168/350)
  catboost-train: 83.14%   (291/350)    data=86.9%  ann=79.4%
  4-source dst:   53.71%   (188/350)    mean_bel=n/a    gap=0.240  K=0.234
  svm-standalone: 84.57%   (296/350)
  5-source dst:   84.57%   (296/350)    mean_bel=n/a    gap=0.101  K=0.620

SVM PILOT
  delta accuracy:     +30.86%
  delta conflict K:   +0.386   [RED FLAG]
  delta uncertainty:  -0.139   [GOOD]
  columns fixed:       110

SAGE — META-TAGGING (512 perms, 355 samples, 13278s CPU, 52% cache)
  column_name:      +0.1142  (dominant, 52% of total)
  sample_values:    +0.0410  (high)
  sibling_context:  +0.0356  (high)
  value_description:+0.0110  (medium)
  source_table:     +0.0079  (medium)
  pattern_signals:  +0.0059  (low-medium)
  value_entropy:    +0.0009  (near-zero)
  numeric_ratio:    +0.0001  (near-zero)
  cardinality:      +0.0001  (near-zero)
  avg_value_length: -0.0001  (zero/noise)
  column_type:      -0.0000  (zero)
  null_ratio:       -0.0000  (zero)

SAGE — GITTABLES (512 perms, 2517 samples, 65% cache)
  column_name:      +0.0812  (dominant)
  sample_values:    +0.0258  (high)
  pattern_signals:  +0.0046  (low-medium)
  cardinality:      +0.0030  (low — higher than meta-tagging)
  numeric_ratio:    +0.0028  (low — higher than meta-tagging)
  column_type:      +0.0026  (low — higher than meta-tagging)
  value_entropy:    +0.0021  (low)
  sibling_context:  +0.0013  (near-zero — much lower than meta-tagging)
  source_table:     +0.0001  (zero)
  avg_value_length: -0.0001  (zero)
  null_ratio:       +0.0000  (zero)
  value_description:+0.0000  (zero)

GPU HARDWARE (idle during entire SAGE run)
  6x NVIDIA RTX 4090 (147.4 GB VRAM)
  Driver: 550.90.07 (CUDA 12.4 max)
  PyTorch: 2.10.0+cu128 (needs CUDA 12.8)
  Status: CUDA unavailable due to driver/toolkit mismatch
```
