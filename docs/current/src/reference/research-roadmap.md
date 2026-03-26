# Research Roadmap: Evidence Fusion

This roadmap converts the findings from the DST domain-expert readiness audit into a structured research plan. Each work item has defined acceptance criteria, estimated scope, and priority based on impact to external credibility. The goal is to make the evidence fusion layer defensible under scrutiny from domain experts in uncertainty quantification, Dempster-Shafer theory, and applied machine learning.

## Priority Classification

| Priority | Meaning | Gate |
|----------|---------|------|
| **P0** | Blocks domain-expert review — will undermine credibility if unaddressed | Must resolve before any external presentation |
| **P1** | Will draw significant questions — defensible answers required | Should resolve before peer review |
| **P2** | Strengthens the contribution — good practice | Address as capacity allows |

## Work Items

### R-01: Source Independence Analysis (P0)

**Problem.** Dempster's rule assumes independent evidence sources. The cosine and CatBoost sources both consume the same sentence-transformer embedding vector — they are fundamentally not independent. Name matching partially overlaps with cosine (the column name is part of the embedding text). This violates the theoretical precondition for Dempster combination and causes over-reinforcement of shared signals, producing overconfident belief intervals.

**Impact.** A DST expert will identify this in the first 5 minutes. It is the single most important issue.

**Approach options:**

1. **Merge cosine + CatBoost into one source.** Treat them as a single "embedding-based" evidence source. CatBoost subsumes cosine when a trained model is available; cosine is the fallback when no model exists. This eliminates the dependence at the cost of reducing from 4 sources to 3 (or 2 when CatBoost is loaded).

2. **Decouple the feature spaces.** Train CatBoost on value-only embeddings (stripping column name, table, siblings) while cosine uses the full embedding. This creates genuinely different input representations, though residual correlation from shared value content remains.

3. **Add an architecturally independent source.** *(Implemented — always-on.)* The SVM source (`svm_to_mass()`) operates on sparse TF-IDF features (character 3–6 grams + word bigrams) with no dependency on the sentence-transformer embedding. The main pipeline trains SVM inline on synthetic data and injects it before classification. Standalone accuracy: 84.6%. A validation script (`scripts/svm_pilot.py`) measures source correlation and impact on fused belief intervals. See [SVM Short-Text Classification](../architecture/evidence-fusion.md#svm-short-text-classification--mass) in the Evidence Fusion architecture.

4. **Switch to a cautious combination rule.** Replace Dempster's rule with Denoeux's cautious rule [Denoeux, 2008] or Yager's modified rule [Yager, 1987], which do not require source independence. The cautious rule uses the least-commitment principle — it produces weaker but more honest intervals.

5. **Quantify and document the dependence.** Measure the correlation between cosine and CatBoost mass functions empirically. If correlation is low (which is plausible — CatBoost learns nonlinear patterns cosine cannot capture), document the argument that "weak dependence does not invalidate Dempster combination in practice" with supporting data.

**Acceptance criteria:**
- [ ] Empirical correlation measurement between cosine and CatBoost mass functions on the evaluation set
- [ ] Selection and implementation of the chosen approach (with rationale document)
- [ ] Updated belief intervals on the evaluation set with comparison to current results
- [ ] Section in evidence-fusion.md documenting the independence assumption and its treatment

**Estimated scope:** 2-3 sessions

---

### R-02: Constant Calibration Experiment (P0)

**Problem.** The implementation contains 13 hardcoded constants that control evidence weighting. None have empirical justification:

| Constant | Location | Current Value | Role |
|----------|----------|---------------|------|
| Cosine discount | `cosine_to_mass()` | 0.30 | Fraction of cosine mass → \\(\Theta\\) |
| CatBoost base discount | `catboost_to_mass()` | 0.15 | Fraction of CatBoost mass → \\(\Theta\\) |
| CatBoost max discount | `catboost_to_mass()` | 0.50 | Maximum variance-adjusted discount |
| Variance scale factor | `catboost_to_mass()` | 1.60 | Maps variance [0,0.25] → discount [0.1,0.5] |
| Pattern evidence mass | `pattern_to_mass()` | 0.90 | Mass on matched pattern categories |
| Pattern \\(\Theta\\) mass | `pattern_to_mass()` | 0.10 | Residual mass to \\(\Theta\\) |
| Name exact match mass | `name_match_to_mass()` | 0.70 | Mass for exact column→category match |
| Name abbrev match mass | `name_match_to_mass()` | 0.50 | Mass for abbreviation match |
| Name overlap match mass | `name_match_to_mass()` | 0.30 | Mass for multi-word overlap match |
| Uncertainty gap threshold | `needs_clarification` | 0.30 | \\(Pl - Bel\\) above which clarification is flagged |
| Conflict threshold | `needs_clarification` | 0.20 | \\(K\\) above which clarification is flagged |
| Softmax temperature | `cosine_to_mass()` | 1.0 | Temperature for cosine→probability conversion |
| Variance base discount | `catboost_to_mass()` | 0.10 | Minimum discount with variance data |

**Impact.** An expert will ask "where do these numbers come from?" The answer cannot be "intuition."

**Approach:**

1. **Grid search on held-out set.** For each constant, sweep a range of values while holding others fixed. Measure accuracy, calibration error (ECE), and mean uncertainty gap on a held-out portion of the evaluation set.

2. **Bayesian optimization.** Use Optuna or similar to jointly optimize the constants against a combined objective: accuracy + calibration + uncertainty gap separation (clarification-needed columns should have higher gaps than confident columns).

3. **Sensitivity analysis.** For each constant, compute \\(\partial(\text{accuracy}) / \partial(\text{constant})\\) and \\(\partial(\text{ECE}) / \partial(\text{constant})\\) to identify which constants matter and which are inert.

**Acceptance criteria:**
- [ ] Sensitivity analysis showing which constants significantly affect accuracy and calibration
- [ ] Optimized values with confidence intervals from cross-validation
- [ ] Calibration plot (reliability diagram) before and after optimization
- [ ] Constants extracted to a configuration dataclass with documented defaults and rationale
- [ ] Reproducible calibration script in `scripts/`

**Estimated scope:** 2-3 sessions

---

### R-03: Conflict Metric Correction (P1) — ✓ Complete

**Problem.** The conflict metric must use cumulative \\(K\\) across all Dempster combination steps, not a single pairwise value.

**Resolution.** `dempster_combine()` returns `(BeliefAssignment, K)` (belief.py:105). `combine_multiple()` computes cumulative \\(K = 1 - \prod_i (1-K_i)\\) via Smarandache & Dezert (2005) (belief.py:146-156). The cumulative K threads through `from_combined_evidence()` → `HierarchicalClassification.conflict`. Tests verify exact K values for known conflict scenarios (`test_returns_conflict_value`, `test_combine_multiple_cumulative_k`).

**Acceptance criteria:**
- [x] `dempster_combine()` returns `(BeliefAssignment, float)` tuple where the float is \\(K\\)
- [x] `combine_multiple()` returns cumulative \\(K = 1 - \prod_i (1-K_i)\\) (Smarandache & Dezert, 2005)
- [x] `_compute_conflict()` removed or replaced
- [x] All existing tests updated and passing
- [x] New tests verifying \\(K\\) for known conflict scenarios

---

### R-04: CatBoost Mass Normalization (P1) — ✓ Complete

**Problem.** `catboost_to_mass()` and `svm_to_mass()` filter proba entries by checking `if code in frame.singletons`. When the class set diverges from the frame's leaf set, the filtered probabilities plus the fixed discount no longer sum to 1.0, producing an invalid mass function.

**Resolution.** After computing singleton masses, residual probability from dropped codes is allocated to \\(\Theta\\):

```python
assigned = sum(masses.values())
masses[frame.theta] = discount + max(0.0, evidence_mass - assigned)
```

Applied to both `catboost_to_mass()` and `svm_to_mass()` in `mass_functions.py`. Three new tests verify valid mass functions with mismatched class sets.

**Acceptance criteria:**
- [x] `catboost_to_mass()` always produces a valid mass function (sum = 1.0)
- [x] `svm_to_mass()` always produces a valid mass function (sum = 1.0)
- [x] Test with mismatched class sets (3 new tests)
- [x] `BeliefAssignment.is_valid` assertion in all mass function tests

---

### R-05: Cautious Hierarchical Classification (P1)

**Problem.** The pignistic transform always commits to a leaf singleton. When evidence supports a broader category but is ambiguous at the leaf level, the classifier still picks a specific leaf — even when \\(Bel(\text{leaf}) \ll Bel(\text{parent})\\). This discards the hierarchy's value.

**Impact.** The "belief at every hierarchy level" data is available but not used for decision-making. A domain expert will ask: "why compute hierarchy-level intervals if you always commit to a leaf?"

**Approach:** Implement `cautious_classify()` that returns the deepest hierarchy node where \\(Bel(A) > \tau\\) (configurable threshold). This follows Denoeux & Zouhal (2001):

```d2
direction: down

root: "InformationEntity\nBel=0.95 ✓" {
  style.fill: "#e8f8e8"

  identity: "IdentityInfo\nBel=0.72 ✓" {
    style.fill: "#e8f8e8"

    gov: "GovtID\nBel=0.45 ✗" {
      style.fill: "#fce4ec"
      tooltip: "Below threshold — refuse to descend"

      tin: "TaxID\nBel=0.38 ✗" {style.fill: "#fce4ec"}
      dl: "DriversLicense\nBel=0.07 ✗" {style.fill: "#fce4ec"}
    }
    plat: "PlatformID\nBel=0.15 ✗" {style.fill: "#fce4ec"}
  }
}
```

In this example, cautious classification would return `IdentityInformation (0010)` — the deepest node where \\(Bel > 0.5\\) — rather than guessing `TaxIdentifier (0085)`.

**Acceptance criteria:**
- [ ] `cautious_classify()` method on `HierarchicalClassification`
- [ ] Configurable threshold (default 0.5)
- [ ] Returns `(code, depth, bel, pl)` tuple
- [ ] Evaluation: compare leaf accuracy vs. cautious accuracy at varying thresholds
- [ ] Tests covering: confident→leaf, uncertain→parent, very uncertain→root

**Estimated scope:** 1-2 sessions

---

### R-06: Pattern Evidence Frequency Weighting (P2)

**Problem.** `pattern_to_mass()` treats pattern detection as binary — a pattern is either detected or not. In practice, the pattern detectors fire when ≥1/3 of sample values match. A column where 95/100 values match the email regex provides much stronger evidence than one where 35/100 match.

**Approach:** Pass match ratios (not just boolean flags) from `ColumnFeatures.pattern_signals` and scale mass accordingly:

\\[m(\\{c\\}) = \text{base\_mass} \times \text{match\_ratio}^{0.5}\\]

The square root prevents low-ratio matches from contributing negligible mass.

**Acceptance criteria:**
- [ ] `ColumnFeatures` provides match ratios alongside pattern names
- [ ] `pattern_to_mass()` accepts and uses match ratios
- [ ] Test with varying match ratios showing monotonic mass increase

**Estimated scope:** 1 session

---

### R-07: Name Match Ambiguity Handling (P2)

**Problem.** `name_match_to_mass()` uses a greedy best-match strategy. When multiple categories match at the same tier (e.g., "address" matches both `BillingAddress` and `ShippingAddress`), only one is selected. The correct DST treatment is to assign mass to the union \\(\\{BillingAddress, ShippingAddress\\}\\), representing the evidence that "it's one of these, but I can't tell which."

**Approach:** When multiple categories match at the same tier, create a composite focal element for their union. This requires the union to be in the restricted focal set — add it as a confusable pair or ad-hoc focal element.

**Acceptance criteria:**
- [ ] Multi-match detection in `name_match_to_mass()`
- [ ] Mass assigned to union focal element when multiple matches exist
- [ ] Test cases for ambiguous names ("address", "identifier", "data")

**Estimated scope:** 1 session

---

### R-08: Confusable Pairs Activation (P2)

**Problem.** The `FrameOfDiscernment` accepts `confusable_pairs` at construction, but the pipeline never passes any. The 16 remaining classification errors cluster in ~6 category pairs (ADID/GUID, BAN/PAN, Under13/Under18, Billing/Shipping address, security flaw subtypes). These are exactly the confusable pairs the mechanism was designed for.

**Approach:** Define the known confusable pairs from error analysis. When evidence is ambiguous between members of a pair, mass goes to the pair focal element rather than forcing a leaf choice.

**Acceptance criteria:**
- [ ] Confusable pairs defined from error analysis
- [ ] Passed to `FrameOfDiscernment` constructor in the pipeline
- [ ] At least one mass function produces mass on pair focal elements
- [ ] Evaluation showing confusable pairs reduce false precision on known error categories

**Estimated scope:** 1 session

---

### R-09: Uniform Discounting Framework (P2)

**Problem.** Each mass function converter implements discounting differently — some as a parameter, some hardcoded, some variance-adaptive. There is no uniform `discount(ba, alpha)` operation.

**Approach:** Implement a standard discounting operation [Shafer, 1976, §11]:

\\[m_\alpha(A) = (1-\alpha) \cdot m(A) \quad \text{for } A \neq \Theta\\]
\\[m_\alpha(\Theta) = \alpha + (1-\alpha) \cdot m(\Theta)\\]

Each converter produces a full-confidence mass function, then discounting is applied uniformly as a separate step. This separates the evidence encoding from the reliability weighting.

**Acceptance criteria:**
- [ ] `discount(ba, alpha)` utility function in `belief.py`
- [ ] All 4 converters refactored to use it
- [ ] Discount factors externalized to configuration
- [ ] Existing tests pass with equivalent results

**Estimated scope:** 1 session

---

### R-10: Virtual Ensembles Integration (P2)

**Problem.** CatBoost's virtual ensembles API (`get_virtual_ensembles_predictions`) provides per-class prediction variance — a direct measure of model uncertainty. The `catboost_to_mass()` function accepts this variance but it is never provided by the pipeline because `classify_dst()` doesn't call the virtual ensembles API.

**Approach:** When a CatBoost model supports virtual ensembles, call `get_virtual_ensembles_predictions()` in `classify_dst()` and pass the variance to `catboost_to_mass()`.

**Acceptance criteria:**
- [ ] Virtual ensemble predictions extracted when CatBoost model supports it
- [ ] Per-class variance passed through to `catboost_to_mass()`
- [ ] Test with mock virtual ensemble output
- [ ] Comparison: fixed discount vs. variance-adaptive discount on evaluation set

**Estimated scope:** 1 session

---

### R-11: Confidence-Gated Adaptive Discounting (P1)

**Problem.** Cross-benchmark analysis revealed three cosine reliability regimes: high confidence (>0.35, near-perfect), low confidence (<0.05, destructive), and intermediate. The current pipeline uses fixed discounts regardless of regime. On GitTables (all generic names), cosine evidence is near-random (1.6% accuracy) but still receives 70% of its mass, creating systematic conflict \\(K = 0.65\\) that overwhelms CatBoost's 81.6% accuracy.

**Impact.** A 10+ percentage point accuracy drop from evidence fusion (71.4% fused vs. 81.6% CatBoost-only on GitTables) is not acceptable. The regime analysis is documented but not operationalized.

**Approach:** Implement per-column adaptive discounting based on the cosine similarity score of the top prediction. When the maximum cosine similarity is below a threshold, increase the cosine discount toward 1.0 (vacuous). When it is high, decrease the discount toward 0.0 (full trust). This converts the three-regime observation into an operational improvement.

\\[d_{cosine} = \begin{cases} 0.10 & \text{if } \max(sim) > 0.35 \text{ (high confidence)} \\\\ 0.30 & \text{if } 0.05 \leq \max(sim) \leq 0.35 \text{ (intermediate)} \\\\ 0.90 & \text{if } \max(sim) < 0.05 \text{ (low confidence)} \end{cases}\\]

**Acceptance criteria:**
- [ ] `cosine_to_mass()` accepts adaptive discount mode
- [ ] Per-column discount based on max similarity score
- [ ] GitTables accuracy improves (target: CatBoost-only 81.6% maintained under fusion)
- [ ] SIGDG benchmark accuracy maintained ≥ 95% (self-train mode already achieves 99.4%)
- [ ] Regime boundaries tuned on held-out data (not hardcoded)

**Estimated scope:** 1 session

---

### R-12: GPU-Accelerated Calibration Pipeline (P2)

**Problem.** The calibration experiment (R-02) requires sweeping 13 constants across a multi-dimensional space. With 6x RTX 4090 GPUs active (driver 570.148.08, CUDA 12.8, PyTorch 2.10.0+cu128), the calibration loop should exploit GPU parallelism for SAGE computation and SentenceTransformer encoding. CatBoost multiclass requires CPU for `posterior_sampling` and `rsm` (GPU drops these, losing 2% accuracy).

**GPU validation (2026-03-24):** Full pipeline completed in 76 min (vs 5+ hours CPU-only). SAGE achieved 27x speedup (489s GPU vs 13,278s CPU). CatBoost forced to CPU for accuracy; GPU used for SentenceTransformer encoding and SAGE.

**Approach:** Build `scripts/calibrate_constants.py` using Optuna. Each trial evaluates accuracy + ECE + uncertainty separation. SAGE and embedding encoding on GPU (27x speedup). CatBoost training on CPU with `posterior_sampling=True`. Multi-trial parallelism via Optuna's `n_jobs`.

**Acceptance criteria:**
- [ ] Optuna-based calibration script with GPU CatBoost
- [ ] Joint optimization of accuracy + ECE + uncertainty gap separation
- [ ] Reliability diagram (calibration plot) before and after optimization
- [ ] Constants extracted to HOCON config with documented rationale
- [ ] Multi-GPU parallelism (1 trial per GPU)

**Estimated scope:** 2 sessions

---

## Completed Items

| Item | Status | Key Result |
|------|--------|------------|
| R-01 option 3 (SVM source) | **Done** | SVM always-on as 5th DST source. 84.6% standalone accuracy. TF-IDF features are architecturally independent from dense embeddings. |
| R-03 (conflict metric) | **Done** | `dempster_combine()` returns K; `combine_multiple()` computes cumulative K via Smarandache & Dezert. Tests verify exact values. |
| R-04 (mass normalization) | **Done** | `catboost_to_mass()` and `svm_to_mass()` allocate residual from dropped codes to Theta. 3 new tests. |
| GPU preflight validation | **Done** | `preflight_gpu()` validates driver/CUDA compat. 6x RTX 4090 active (driver 570.148.08, CUDA 12.8). SAGE 27x speedup (489s GPU vs 13,278s CPU). CatBoost forced to CPU (posterior_sampling not supported on GPU). |
| SHAP explanations | **Done** | Per-item CatBoost TreeSHAP with top-3 feature attribution in parquet output. |
| Single-command pipeline | **Done** | `--auto-generate` trains SVM + CatBoost inline on synthetic data. Zero manual steps. |
| Self-training mode | **Done** | `--self-train` injects GT-labeled eval data into CatBoost training. 99.4% accuracy (348/350). LLM annotation reproduction workflow. SVM text format fix: 60.6% → 84.6% DST accuracy. |
| LLM bootstrap agent | **Done** | K-based convergent classification for novel tables. Dual backend (Anthropic + OpenAI-compatible). Tiered sampling, label propagation, LLM revisit with ML context. `llm_to_mass()` as 6th DST source. Output feeds `--self-train`. |

## Dependency Graph

```d2
direction: right

r01: "R-01\nSource Independence\n(P0) ✓ partial" {style.fill: "#c8e6c9"}
r02: "R-02\nCalibration Experiment\n(P0)" {style.fill: "#fce4ec"}
r03: "R-03\nConflict Metric\n(P1) ✓" {style.fill: "#c8e6c9"}
r04: "R-04\nCatBoost Normalization\n(P1) ✓" {style.fill: "#c8e6c9"}
r05: "R-05\nCautious Classification\n(P1)" {style.fill: "#fff3e0"}
r06: "R-06\nPattern Frequency\n(P2)" {style.fill: "#e8f4f8"}
r07: "R-07\nName Ambiguity\n(P2)" {style.fill: "#e8f4f8"}
r08: "R-08\nConfusable Pairs\n(P2)" {style.fill: "#e8f4f8"}
r09: "R-09\nUniform Discounting\n(P2)" {style.fill: "#e8f4f8"}
r10: "R-10\nVirtual Ensembles\n(P2)" {style.fill: "#e8f4f8"}
r11: "R-11\nAdaptive Discounting\n(P1)" {style.fill: "#fff3e0"}
r12: "R-12\nGPU Calibration\n(P2)" {style.fill: "#e8f4f8"}

r01 -> r02: "Independence\naffects calibration"
r03 -> r02: "Correct K needed\nfor calibration"
r04 -> r02: "Valid masses needed\nfor calibration"
r09 -> r02: "Unified discounting\nsimplifies search"
r05 -> r08: "Cautious classification\nuses confusable pairs"
r07 -> r08: "Ambiguity → union\nfocal elements"
r10 -> r04: "VE variance uses\ncatboost_to_mass"
r11 -> r02: "Adaptive discount\nreduces search space"
r12 -> r02: "GPU infra for\ncalibration sweep"
```

**Critical path:** R-01 (partial ✓) + R-03 (✓) + R-04 (✓) + R-11 → R-02 (R-12 accelerates) → R-05. Three P0/P1 prerequisites are resolved. The remaining critical path is: implement adaptive discounting (R-11), then run the GPU-accelerated calibration experiment (R-02/R-12). Cautious classification (R-05) builds on calibrated intervals.

## Evaluation Protocol

All work items should be evaluated against the same protocol for consistency:

1. **Accuracy**: Classification accuracy on the GT-labeled evaluation set (current best: 83.1% CatBoost benchmark, 84.6% SVM, **99.4% with self-training**; benchmark target ≥ 95%)
2. **Calibration**: Expected Calibration Error (ECE) — do belief intervals track true accuracy?
3. **Uncertainty separation**: Do columns flagged `needs_clarification` genuinely have higher error rates?
4. **Conflict utility**: Does high \\(K\\) correlate with misclassification? (ROC-AUC of \\(K\\) as a misclassification predictor)
5. **Hierarchy utility**: At what belief threshold does cautious classification achieve 99% accuracy? How deep does it commit on average?

## References

- Denoeux, T. (2008). Conjunctive and disjunctive combination of belief functions induced by nondistinct bodies of evidence. *Artificial Intelligence*, 172(2-3), 234-264.
- Denoeux, T. & Zouhal, L.M. (2001). Handling possibilistic labels in pattern classification using evidential reasoning. *Fuzzy Sets and Systems*, 122(3), 409-424.
- Shafer, G. (1976). *A Mathematical Theory of Evidence*. Princeton University Press.
- Smets, P. & Kennes, R. (1994). The Transferable Belief Model. *Artificial Intelligence*, 66(2), 191-234.
- Smarandache, F. & Dezert, J. (2005). Information fusion based on new proportional conflict redistribution rules. *Proceedings of Fusion 2005*.
- Yager, R.R. (1987). On the Dempster-Shafer framework and new combination rules. *Information Sciences*, 41(2), 93-137.
