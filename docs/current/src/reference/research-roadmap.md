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

3. **Switch to a cautious combination rule.** Replace Dempster's rule with Denoeux's cautious rule [Denoeux, 2008] or Yager's modified rule [Yager, 1987], which do not require source independence. The cautious rule uses the least-commitment principle — it produces weaker but more honest intervals.

4. **Quantify and document the dependence.** Measure the correlation between cosine and CatBoost mass functions empirically. If correlation is low (which is plausible — CatBoost learns nonlinear patterns cosine cannot capture), document the argument that "weak dependence does not invalidate Dempster combination in practice" with supporting data.

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

### R-03: Conflict Metric Correction (P1)

**Problem.** `_compute_conflict()` in `classifier.py` computes the maximum pairwise conflict across the sequential Dempster combination chain. This is not standard. The actual cumulative conflict \\(K\\) is computed inside `dempster_combine()` but discarded.

**Impact.** The reported `dst_conflict` column and the `needs_clarification` flag depend on this metric. An incorrect value means the diagnostic is unreliable.

**Approach:** Modify `dempster_combine()` to return \\(K\\) alongside the combined mass. Thread the cumulative \\(K\\) through `combine_multiple()` and `from_combined_evidence()`.

**Acceptance criteria:**
- [ ] `dempster_combine()` returns `(BeliefAssignment, float)` tuple where the float is \\(K\\)
- [ ] `combine_multiple()` returns cumulative \\(K = 1 - \prod_i (1-K_i)\\) (Smarandache & Dezert, 2005)
- [ ] `_compute_conflict()` removed or replaced
- [ ] All existing tests updated and passing
- [ ] New tests verifying \\(K\\) for known conflict scenarios

**Estimated scope:** 1 session

---

### R-04: CatBoost Mass Normalization (P1)

**Problem.** `catboost_to_mass()` filters proba entries by checking `if code in frame.singletons`. When CatBoost's class set diverges from the frame's leaf set (e.g., unseen classes at training time), the filtered probabilities plus the fixed discount no longer sum to 1.0. This produces an invalid mass function.

**Approach:** After filtering, allocate the residual probability mass to \\(\Theta\\):

```python
evidence_mass = 1.0 - discount
assigned = sum(masses.values()) - discount  # mass already assigned to singletons
residual = evidence_mass - assigned
masses[frame.theta] = discount + max(0, residual)
```

**Acceptance criteria:**
- [ ] `catboost_to_mass()` always produces a valid mass function (sum = 1.0)
- [ ] Test with mismatched class sets
- [ ] `BeliefAssignment.is_valid` assertion added to all mass function tests

**Estimated scope:** 0.5 sessions

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

## Dependency Graph

```d2
direction: right

r01: "R-01\nSource Independence\n(P0)" {style.fill: "#fce4ec"}
r02: "R-02\nCalibration Experiment\n(P0)" {style.fill: "#fce4ec"}
r03: "R-03\nConflict Metric\n(P1)" {style.fill: "#fff3e0"}
r04: "R-04\nCatBoost Normalization\n(P1)" {style.fill: "#fff3e0"}
r05: "R-05\nCautious Classification\n(P1)" {style.fill: "#fff3e0"}
r06: "R-06\nPattern Frequency\n(P2)" {style.fill: "#e8f4f8"}
r07: "R-07\nName Ambiguity\n(P2)" {style.fill: "#e8f4f8"}
r08: "R-08\nConfusable Pairs\n(P2)" {style.fill: "#e8f4f8"}
r09: "R-09\nUniform Discounting\n(P2)" {style.fill: "#e8f4f8"}
r10: "R-10\nVirtual Ensembles\n(P2)" {style.fill: "#e8f4f8"}

r01 -> r02: "Independence\naffects calibration"
r03 -> r02: "Correct K needed\nfor calibration"
r04 -> r02: "Valid masses needed\nfor calibration"
r09 -> r02: "Unified discounting\nsimplifies search"
r05 -> r08: "Cautious classification\nuses confusable pairs"
r07 -> r08: "Ambiguity → union\nfocal elements"
r10 -> r04: "VE variance uses\ncatboost_to_mass"
```

**Critical path:** R-01 + R-03 + R-04 → R-02 → R-05. Resolve the independence assumption first, fix the conflict metric and normalization bug, then run the calibration experiment with correct infrastructure. Cautious classification builds on calibrated intervals.

## Evaluation Protocol

All work items should be evaluated against the same protocol for consistency:

1. **Accuracy**: Classification accuracy on the 350 GT-labeled evaluation set (maintain ≥ 95%)
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
