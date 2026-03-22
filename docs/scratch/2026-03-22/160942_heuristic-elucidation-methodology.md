# De Novo Heuristic Elucidation — Methodology Synthesis

**Date**: 2026-03-22
**Branch**: `rch/sage-gpu-accel`

## The Pattern

Today's cross-benchmark experiments (GitTables + meta-tagging) reveal a unifying
methodology behind the classification pipeline's techniques. Each technique is
an **observed, dataset-specific phenomenon reduced to practice** — not a design
choice made a priori. Each can be quantified by SAGE (Shapley values) to measure
its marginal contribution to accuracy.

We call this **de novo heuristic elucidation**: the systematic process of
observing phenomena in benchmark data, formulating them as features, and
incorporating them into the CatBoost+DST pipeline with measured contribution.

## The Cycle

```
Observe  →  Hypothesize  →  Implement  →  Quantify  →  Validate
   ↑                                                       |
   └───────────────────────────────────────────────────────┘
```

1. **Observe**: Run a benchmark, identify failure modes and performance gaps
2. **Hypothesize**: Formulate the phenomenon as a testable feature or technique
3. **Implement**: Add to CatBoost feature vector or post-processing step
4. **Quantify**: SAGE Shapley values measure marginal accuracy contribution
5. **Validate**: Cross-benchmark comparison prevents overfitting to one dataset

The cycle repeats: validation reveals new failure modes, which become new
observations.

## Heuristic Catalog

Seven heuristics discovered through this cycle:

| # | Heuristic | Observation | Implementation | SAGE Feature |
|---|-----------|-------------|----------------|--------------|
| 1 | **Dual embedding** | Annotation columns have opaque names → full embedding includes misleading name signal | Strip name/table/siblings for a second (value-only) embedding; 384 dims each | `column_name` ablation measures name dependency |
| 2 | **Category reference augmentation** | 175 classes × ~2 samples each → CatBoost can't learn boundaries | Inject 212 taxonomy reference embeddings as anchor training points | Category ref cosine sims are a 212-dim feature subvector |
| 3 | **Cosine similarity features** | Cosine similarity to references is strong zero-shot signal on semantic names | Encode 212 cosine similarities as CatBoost feature dimensions | Each category's cosine sim is independently measurable |
| 4 | **Paired column propagation** | Data and annotation columns are paired — annotation follows its data column | Propagate confident data-column predictions to uncertain annotation columns | Pre/post propagation delta measurable |
| 5 | **Value description** | Generic names (`col0`, `field_1`) have no semantic content | Substitute NL descriptions of value patterns when column name is generic | `value_description` is the 12th SAGE feature |
| 6 | **Discrete feature scaling** | 11 discrete features ignored by gradient boosting in presence of 384-dim embeddings | Scale by √(384/11) ≈ 5.9 so magnitudes compete | Each discrete feature individually measurable |
| 7 | **Synthetic data generation** | Real data was procedurally generated from annotations → reverse-engineer the process | 70+ value generators covering all 175 categories, 50/50 semantic/opaque names | Entire train→eval regime is the contribution |

## Cross-Benchmark Validation

| Heuristic | Meta-tagging (semantic names) | GitTables (generic names) | Generalizes? |
|-----------|-------------------------------|--------------------------|--------------|
| Dual embedding | 83.4% (from 33.4% baseline) | Not tested standalone | Yes — value-only embedding helps whenever names are uninformative |
| Category ref augmentation | Anchor training + cosine feature dims | Anchor training (81.6% CatBoost) | Yes — taxonomy references exist for any taxonomy |
| Cosine similarity features | 86.0% (from 83.4%) | Part of CatBoost's 81.6% | Yes — cosine sims are domain-invariant features |
| Paired propagation | 95.4% (from 86.0%) | N/A (no column pairing) | **No** — dataset-specific structural observation |
| Value description | 99.4% cosine on data cols | 1.6% → improves cosine baseline | Yes — any generic-name dataset benefits |
| Discrete scaling | Implicit in all CatBoost runs | Implicit in all CatBoost runs | Yes — universal numerical fix |
| Synthetic data | 95.4% vs 45.1% k-fold | N/A (uses GT labels directly) | **Partially** — requires reverse-engineering data generation |

Key finding: heuristics 1-3, 5-6 are **universally applicable**. Heuristic 4
(paired propagation) is dataset-specific. Heuristic 7 (synthetic data) applies
when the evaluation data's generation process is known or inferable.

## Confidence-Gated Fusion

The cross-benchmark comparison reveals when cosine evidence helps vs. hurts:

| Dataset | Cosine Accuracy | CatBoost Accuracy | DST Fusion Effect |
|---------|-----------------|-------------------|-------------------|
| GitTables (generic names) | 1.6% | 81.6% | **Destructive** — drops to 71.4% |
| Meta-tag data cols (semantic names) | 99.4% | 66.3% | **Beneficial** — cosine dominates |
| Meta-tag annotation cols (opaque names) | 8.0% | 29.7% | CatBoost should dominate |

The principled DST integration:

```
if cosine_confidence > 0.35:   → heavily discount CatBoost (cosine is reliable)
if cosine_confidence < 0.05:   → heavily discount cosine (no signal)
else:                          → standard DST combination
```

This is **confidence-gated fusion**: use the cosine evidence's own confidence to
decide how to weight it against CatBoost. The DST conflict metric K provides the
diagnostic — when K > 0.5, the sources disagree enough that one should be
discounted.

## Agentic Workflow Vision

The heuristic elucidation cycle maps naturally to an agentic workflow with
frontier LLMs:

1. **LLM as observer**: Given a new dataset, the LLM examines column names,
   value distributions, table structure, and identifies phenomena (e.g., "these
   columns appear to be paired", "names are generic positional identifiers")

2. **LLM as hypothesis generator**: The LLM formulates the phenomenon as a
   feature or technique (e.g., "paired column propagation would help here",
   "value descriptions should substitute for generic names")

3. **LLM as bootstrapper**: The LLM classifies columns to generate training
   signal for CatBoost — replacing the manual GT labeling process

4. **SAGE as quality gate**: After implementing a new feature, SAGE automatically
   measures whether it improved accuracy — no human judgment needed

5. **DST conflict as disagreement detector**: When SAGE shows a new feature
   conflicts with existing evidence, the conflict metric K flags it for review

This creates a **self-improving classification pipeline**: each new dataset
encounter produces new heuristics, which are automatically validated and
incorporated. The LLM's role shifts from classifier to *methodology driver*.

## Connections to Prior Notes

- `030016_gittables-baseline-scores.md` — cosine failure on generic names
  motivates heuristics 1, 2, 5
- `040100_gittables-catboost-baseline.md` — CatBoost success + cosine
  interference motivates confidence-gated fusion
- `051200_meta-tagging-dst-vs-catboost.md` — cosine/CatBoost complementarity
  validates the adaptive approach
- `docs/scratch/2026-03-19/214500_xgboost-95pct-accuracy.md` — accuracy
  progression demonstrates the cumulative effect of heuristic discovery
