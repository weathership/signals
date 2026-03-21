# Pipeline Integrity Audit

Date: 2026-03-20

## Scope

Audit of the classification pipeline's 95.4% accuracy claim for methodological
soundness. Focus: data leakage, circular reasoning, evaluation fairness,
and claims that would not survive outside technical review.

## Verdict Summary

| Finding | Severity | Status |
|---------|----------|--------|
| Self-training uses eval-set embeddings | **HIGH** | Must fix or must disclose |
| Paired propagation is dataset-specific | **HIGH** | Must disclose; misrepresented as general technique |
| SAGE pseudo-GT is circular | **MEDIUM** | Already labeled "pseudo" but docs overstate value |
| Shared GT for cosine + XGBoost eval | **Non-issue** | Normal; both methods evaluated on same held-out truth |
| Name-match boost in cosine | **Non-issue** | Feature, not leakage; already ablatable |
| Synthetic domain mismatch | **Non-issue** | Expected; self-training exists to bridge it |

---

## FINDING 1: Self-training leaks eval-set information into training (HIGH)

### The mechanism

`_run_xgboost_train_eval()` lines 390-411 take the cosine classifier's
predictions on the **eval set** and inject confident data-column predictions
(confidence >= 0.50) as pseudo-labeled training samples for XGBoost.

The XGBoost model is then evaluated on the **same** eval set.

### Why this is a problem

The eval-set embeddings (`X_eval_full_emb`, `X_eval_vo_emb`) for
pseudo-labeled columns appear in the XGBoost training matrix. When XGBoost
is later asked to predict these same columns, it has already seen their
exact feature vectors during training. This is **transductive leakage** —
the model memorizes eval points it was trained on.

### Severity assessment

The leakage affects only **data columns** (annotation columns are excluded
from self-training at line 401). Cosine already achieves 98.9% on data
columns independently, so the leaked information mostly confirms already-easy
predictions. The real accuracy claim rests on annotation columns (7.4% →
92.0%), which are **not** leaked.

However, the 98.9% data-column accuracy for XGBoost cannot be claimed as
an independent signal — it is partly a memorization artifact.

### What to do

**Option A (conservative):** Remove self-training entirely. Report the
accuracy without it. Per the progression table, accuracy without
self-training is 33.4% → with dual embedding probably ~50-60%.

**Option B (fix the leak):** Exclude pseudo-labeled columns from the eval
accuracy computation. Train on them, but don't count them as "correctly
predicted" since the model saw their embeddings. This gives a honest
eval-only accuracy on the remaining columns.

**Option C (proper semi-supervised):** Split eval into two halves. Use
cosine pseudo-labels from half A as training, evaluate only on half B.
Report accuracy on the held-out half.

---

## FINDING 2: Paired propagation is a dataset-specific heuristic (HIGH)

### The mechanism

Lines 556-574: after XGBoost predicts, a post-processing pass checks if
each annotation column is immediately preceded by a data column. If so, and
the data column is confident while the annotation column is uncertain,
the data column's prediction overwrites the annotation column's prediction.

### Why this is a problem

This exploits a **structural property of this specific dataset** — that
data columns and their annotation counterparts are interleaved in a fixed
order with matching categories. The technique:

1. Cannot generalize to any dataset where columns aren't paired this way
2. Is not a classification technique — it's a label-copying rule
3. Accounts for the jump from 86.0% → 95.4% (the largest single gain
   on annotation columns: 73.1% → 92.0%)

### Severity assessment

The accuracy progression table in the docs presents paired propagation as
a "technique" alongside genuine ML improvements (dual embedding, cosine
sim features). In review, this would be challenged as a dataset-specific
post-hoc correction, not a generalizable method.

### What to do

**Must do:** Report accuracy both with and without paired propagation.
The honest XGBoost-only number is 86.0% overall (98.9% data / 73.1% ann).

**Should do:** Move paired propagation out of the accuracy progression
table into a separate "dataset-specific optimizations" section, clearly
labeled as non-generalizable.

---

## FINDING 3: SAGE pseudo-GT measures classifier behavior, not ground truth signal (MEDIUM)

### The mechanism

Lines 1119-1123: SAGE is run with the cosine classifier's own predictions
as pseudo-ground-truth. It measures which features the cosine classifier
relies on, not which features predict the actual correct category.

### Severity assessment

The code already labels this `"sage_source": "pseudo"` in the report JSON,
and the docstrings say "predictions as pseudo-GT." The docs page says SAGE
runs "using classifier predictions as pseudo-ground-truth."

However, the docs then present SAGE results as "which features matter" without
qualifying that this means "which features matter to the cosine classifier"
rather than "which features predict the correct answer."

### What to do

When LLM GT is available, SAGE should run against the GT labels (for the
subset of columns where GT exists), not against cosine predictions. This is
a one-line fix: use `gt[col]` instead of `res["tag_code"]` when `--ground-truth`
is provided.

---

## NON-ISSUES (things the raw audit flagged that are actually fine)

### Shared GT for cosine and XGBoost evaluation

The audit flagged that both cosine and XGBoost are evaluated against the same
ground truth file. This is **normal and correct** — it's the same as any ML
evaluation where multiple methods are compared on the same test set. The GT
is not used for training either method (cosine is zero-shot; XGBoost trains
on synthetic data). Using different GT for different methods would make
comparison impossible.

### Name-match boost

The audit flagged `name_match_boost` as a "non-semantic signal." But:
- It's documented as a feature, not hidden
- It's ablatable via `--no-name-boost`
- The cosine accuracy numbers *include* the boost (53.1% overall with boost)
- The XGBoost pipeline doesn't use name-match boost — it has its own features

The boost is a legitimate feature engineering choice. Column names *are*
informative — the problem is that they don't help for annotation columns,
which is why the pipeline exists.

### Synthetic domain mismatch

The audit flagged that synthetic values are "perfect" (100 rows of
well-formed values) while real data has only 5 sample values. This is true
but already addressed: self-training and category reference augmentation
exist specifically to bridge this domain gap. The 33.4% → 66.3% jump from
self-training shows the gap is real and partially closed.

---

## Defensible vs. Indefensible Claims

| Claim | Defensible? | Notes |
|-------|-------------|-------|
| "95.4% overall accuracy" | **No** | Includes self-training leakage + dataset-specific propagation |
| "86.0% overall accuracy" | **Mostly** | Self-training leakage still inflates data-column numbers |
| "73.1% annotation accuracy" | **Yes** | No leakage (self-training excludes ann cols, no propagation) |
| "98.9% data column accuracy" | **No** | Self-training memorizes eval embeddings for data columns |
| "Dual embedding improves annotation accuracy" | **Yes** | Clean technique, no leakage |
| "Cosine sim features improve accuracy" | **Yes** | Domain-invariant, no leakage |
| "Self-training bridges domain shift" | **Partially** | True in principle, but implementation leaks eval data |
| "Paired propagation improves annotation accuracy" | **Dataset-specific** | Not generalizable |

---

## Recommended Accuracy Table for External Review

Strip self-training of leaked eval embeddings and separate propagation:

| Technique | Overall | Data | Annotation | Clean? |
|-----------|---------|------|------------|--------|
| Cosine (zero-shot) | 53.1% | 98.9% | 7.4% | Yes |
| XGBoost k-fold CV | 45.1% | 79.4% | 10.9% | Yes |
| Synthetic train→eval | 33.4% | 44.0% | 22.9% | Yes |
| + Dual embedding | ~50%* | ~85%* | ~40%* | Yes |
| + Cosine sim features | ~55%* | ~90%* | ~45%* | Yes |
| + Self-training (fixed) | TBD | TBD | TBD | Needs re-run |
| + Paired propagation | N/A | N/A | N/A | Dataset-specific |

*Estimates — need to re-run without self-training to get clean numbers for
the dual-embedding and cosine-sim-features stages.

---

## Action Items

1. **Re-run the progression without self-training** to get clean numbers for
   dual embedding and cosine sim features in isolation.
2. **Fix self-training** to exclude eval-set columns from eval accuracy, or
   use a proper train/pseudo/eval three-way split.
3. **Separate paired propagation** from the main accuracy table. Report it
   as a dataset-specific optimization.
4. **Fix SAGE** to use real GT when available.
5. **Update docs** (context-engineering.md, classification-training.md) to
   reflect the corrected claims.
