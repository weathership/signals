# DST + CatBoost Domain-Expert Readiness Audit

**Date**: 2026-03-21
**Scope**: belief.py, mass_functions.py, classifier.py, embedding_classifier.py, category_set.py, build_sigint_embeddings.py, run_report.py
**Question**: Are we ready for a deep-dive with a DST/uncertainty quantification domain expert?

---

## A. Mathematical Correctness

### A1. Bel, Pl -- CORRECT

`belief.py` lines 63-68 (Bel) and 70-75 (Pl) are textbook Shafer 1976:

- `Bel(A) = sum m(B) for B subset-of A` -- correct subset check via `issubset()`
- `Pl(A) = sum m(B) for B intersect A != empty` -- correct intersection check via `&`

The invariant `Bel(A) <= Pl(A)` holds by construction. Test at `test_belief.py:75-78` verifies.

### A2. Pignistic Transform (BetP) -- CORRECT

`belief.py` lines 86-100. The implementation follows Smets & Kennes 1994 (Transferable Belief Model):

```
BetP({x}) = sum_A m(A)/|A| for all A containing x, A != empty
```

The guard at line 93 (`len(singleton.codes) != 1`) correctly enforces singleton-only input. The `len(fe.codes) > 0` check at line 98 is redundant (FocalElements are never empty in practice) but harmless.

**Note**: This is the *unnormalized* pignistic form -- it assumes `m(empty) = 0`, which is guaranteed by `dempster_combine()` (line 115: empty intersections go to conflict, not to a focal element). The standard BetP divides by `(1 - m(empty))` but since m(empty) = 0 throughout, this is equivalent. A domain expert may ask about this -- worth a comment.

### A3. Dempster's Rule of Combination -- CORRECT

`belief.py` lines 103-132. This is standard Dempster's conjunctive rule with normalization:

1. Lines 111-119: Compute all pairwise intersections, accumulate conflict
2. Line 121: Reject total conflict (K >= 1)
3. Lines 126-131: Normalize by `1/(1-K)`

The combination is commutative and associative (Shafer 1976, Theorem 3.1). `combine_multiple()` at lines 135-142 exploits associativity for left-to-right folding -- mathematically sound.

**Potential issue**: The `1e-12` tolerance at line 121 (`conflict >= 1.0 - 1e-12`) means near-total-conflict (K=0.999999999999) is rejected. This is conservative and appropriate for a classification pipeline.

### A4. Mass Function Validity -- CORRECT

`is_valid` at lines 49-52 checks both non-negativity and sum-to-one. The `normalize()` method at lines 54-61 handles renormalization with a dead-mass filter (`v > 1e-15`). The tolerance chain is consistent: `1e-15` for mass filtering < `1e-12` for conflict threshold < `1e-9` for validity.

### A5. Open-World vs Closed-World

The implementation is **closed-world** (Shafer's original): `m(empty) = 0` is enforced by construction (Dempster's rule only produces non-empty intersections). This is appropriate for a classification task where the taxonomy is assumed exhaustive. An expert working in Smets' TBM (open-world, `m(empty) > 0`) would note this choice. It should be documented.

**VERDICT**: The core DST math is correct per Shafer 1976. No errors found.

---

## B. Architecture

### B1. Restricted Focal Set Strategy -- SOUND

`belief.py` lines 145-220. For 175 leaf categories, the full power set `2^175` is intractable. The restriction to:

- 175 singletons
- ~40 internal nodes (hierarchy parents)
- Optional confusable pairs
- 1 Theta (full frame)

yields ~220 focal elements (documented at line 154). This is a well-known approach in applied DST (Denoeux 2008, "Conjunctive and disjunctive combination of belief functions induced by non-distinct bodies of evidence").

**Concern**: The internal nodes are built from the taxonomy hierarchy, which is good. However, the confusable pairs mechanism (`confusable_pairs` parameter, line 160) is never populated in the actual pipeline. In `build_sigint_embeddings.py`, `FrameOfDiscernment(hierarchical_cs)` is called without any confusable pairs (line 894). This feature exists but is dead code in practice.

### B2. Hierarchy Leveraged Appropriately -- MOSTLY

The `HierarchicalCategorySet` (category_set.py) correctly computes `descendants()`, `ancestors()`, and `children()` via cached properties. The `belief_at()` / `plausibility_at()` methods in `HierarchicalClassification` (classifier.py lines 70-108) correctly look up both singletons and internal nodes, computing Bel/Pl over the descendant leaf set when querying a parent node.

The `dst_belief_path` output in `build_sigint_embeddings.py` (lines 1029-1049) traces from leaf to root, showing Bel/Pl at each hierarchy level. This is exactly what a domain expert would want to see for interpretability.

**Gap**: The hierarchy is only used for *reporting* (belief paths). It is not used for *decision-making*. The pignistic decision (line 168-171 of classifier.py) considers only singletons. There is no "refuse to classify below this hierarchy level" logic -- the system always commits to a leaf. A DST expert would likely ask about hierarchical decision strategies (e.g., Denoeux & Zouhal 2001 cautious classification).

### B3. Vacuous Source Filtering -- CORRECT

`classifier.py` lines 146-149: vacuous sources (all mass on Theta) are filtered before combination. This is correct -- combining with a vacuous source is an identity operation but wastes computation.

### B4. Evidence Source Independence Assumption -- UNDOCUMENTED

Dempster's rule assumes **independent** evidence sources. The 4 sources (cosine, catboost, pattern, name_match) are:

- **cosine + catboost**: Both consume the same embedding vector. They are NOT independent. The embedding is the same input; CatBoost is a learned transform of cosine-adjacent features. This violates the independence assumption.
- **cosine + name_match**: Name is part of the embedding text, so there is partial dependence.
- **pattern + cosine**: Pattern signals may overlap with value information in the embedding. Weak dependence.

This is the single most likely challenge from a domain expert. Alternatives: Cautious rule (Denoeux 2008), averaging rule, or Yager's rule would handle dependent sources better.

---

## C. Evidence Source Quality

### C1. `cosine_to_mass()` -- REASONABLE WITH CAVEATS

`mass_functions.py` lines 20-58.

**Approach**: Softmax over cosine similarities, then discount by a fixed fraction to Theta.

**Issue 1 -- Softmax temperature**: Temperature = 1 is hardcoded (implicit, line 41). With 175 categories and cosine similarities typically in [0.1, 0.9], softmax-with-temperature-1 will be *very* peaked. This might be appropriate (high confidence is desired) but the lack of temperature tuning means the mass distribution is essentially "winner-take-all" in practice. A domain expert would ask why temperature isn't a tunable parameter calibrated to held-out data.

**Issue 2 -- Fixed discount**: `discount=0.3` (line 23 default, line 397 of embedding_classifier.py). This says "30% of the time, I have no idea." The value 0.3 is not empirically justified anywhere. It should be calibrated against accuracy on a validation set.

**Issue 3 -- Negative similarities**: Cosine similarity can be negative. `math.exp(sim - max_sim)` handles this gracefully (just smaller exponentials), but negative similarities have semantic meaning (anti-correlated embeddings). The mass function treats them as low-probability, which is correct.

### C2. `catboost_to_mass()` -- WELL-DESIGNED

`mass_functions.py` lines 61-95.

**Approach**: Direct probability-to-mass mapping with variance-adaptive discount.

**Strength**: The virtual-ensembles variance integration (lines 81-84) is a genuine contribution. CatBoost's `VirtualEnsembles` feature provides epistemic uncertainty estimates, and mapping `avg_var in [0, 0.25] -> discount in [0.1, 0.5]` is a reasonable linear transform.

**Issue 1 -- Hardcoded constants**: The mapping `0.1 + avg_var * 1.6` (line 84) and floor/ceiling `[0.1, 0.5]` are not justified. The linear mapping assumes variance is uniformly distributed in [0, 0.25], which depends on the number of trees, learning rate, and data distribution.

**Issue 2 -- Default discount 0.15**: Line 86. Lower than cosine's 0.3, reflecting a belief that "CatBoost is generally well-calibrated." This is reasonable but the comment should cite evidence (e.g., calibration plot from the training pipeline).

**Issue 3 -- probabilities may not sum to 1.0 over frame**: The `proba` dict may contain codes not in the frame's singletons (filtered at line 91). The remaining evidence mass is `prob * evidence_mass` for the kept codes, plus `discount` for Theta. If some proba codes are filtered out, the total won't sum to 1.0. This is a **bug**: the resulting BeliefAssignment may fail `is_valid`.

### C3. `pattern_to_mass()` -- ADEQUATE BUT CRUDE

`mass_functions.py` lines 98-148.

**Approach**: Binary pattern detection -> uniform mass split over matched categories, with 0.1 to Theta.

**Issue 1 -- Fixed 0.9/0.1 split**: Lines 130, 135. Pattern matches get 90% evidence mass regardless of how many patterns match or how reliable each pattern is. A regex matching "123-45-6789" as SSN is highly reliable; a regex matching digits as a credit card is much less so. All patterns are treated equally.

**Issue 2 -- No confidence gradation**: A column where 100% of values match `email_pattern` gets the same mass as one where 10% of values match. The pattern detector is binary per-pattern, not frequency-based.

**Issue 3 -- Hardcoded mapping**: `_DEFAULT_PATTERN_MAP` (lines 140-149) maps 8 patterns to category codes. This is a tiny subset of the 175 categories. Most categories have no pattern evidence, making this source vacuous most of the time.

### C4. `name_match_to_mass()` -- REASONABLE

`mass_functions.py` lines 152-210.

**Approach**: Greedy best-match with three tiers (exact=0.7, abbrev=0.5, word-overlap=0.3).

**Issue 1 -- Fixed mass values**: The tier masses (0.7, 0.5, 0.3) are hardcoded. An expert would want to see these calibrated against actual name-match accuracy.

**Issue 2 -- Best-match only**: Only one category gets mass. If "address" matches both "EmailAddress" and "MailingAddress," only the first encountered wins. This discards useful ambiguity information -- a DST approach should support multi-hypothesis mass assignment (e.g., give mass to the union `{EmailAddress, MailingAddress}`).

---

## D. Domain-Expert Concerns

### D1. Source Independence Violation (CRITICAL)

As noted in B4, cosine and CatBoost share the same input embedding. Dempster's rule assumes independent sources. When sources are correlated, Dempster's rule *over-reinforces* the shared signal, producing overconfident results. This is the #1 thing a DST expert will probe.

**Mitigation options**:
1. Use the cautious rule (Denoeux 2008) which handles non-independent sources
2. Use Yager's rule (conflict goes to Theta instead of being normalized away)
3. Treat cosine+catboost as a single source and only combine with pattern/name

### D2. Hardcoded Constants Inventory

| Constant | Location | Value | Justification |
|----------|----------|-------|---------------|
| Cosine discount | mass_functions.py:23 | 0.3 | None |
| Cosine softmax temp | mass_functions.py:41 | 1.0 (implicit) | None |
| CatBoost default discount | mass_functions.py:86 | 0.15 | Comment only |
| CatBoost var->discount slope | mass_functions.py:84 | 1.6 | None |
| CatBoost var->discount floor | mass_functions.py:84 | 0.1 | None |
| CatBoost var->discount ceiling | mass_functions.py:84 | 0.5 | None |
| Pattern evidence mass | mass_functions.py:130 | 0.9 | None |
| Pattern Theta mass | mass_functions.py:135 | 0.1 | None |
| Name exact match mass | mass_functions.py:187-189 | 0.7 | None |
| Name abbrev match mass | mass_functions.py:192-193 | 0.5 | None |
| Name word overlap mass | mass_functions.py:199 | 0.3 | None |
| Needs-clarification gap threshold | classifier.py:125 | 0.3 | None |
| Needs-clarification conflict threshold | classifier.py:125 | 0.2 | None |

**Total: 13 hardcoded constants with no empirical justification.**

### D3. Conflict Computation is Non-Standard

`classifier.py` lines 213-235. `_compute_conflict()` reports the **maximum pairwise conflict** across the sequential combination chain, not the actual cumulative conflict K from the final combination. This is not a standard DST measure. The actual K is available inside `dempster_combine()` but is discarded.

The docstring says "approximate conflict K from pairwise combination" (line 214), which is misleading. The max-pairwise metric measures something different from the cumulative K. A domain expert would immediately question this.

### D4. No Discounting Framework

The discount values are per-source static constants. A proper DST framework would use Shafer's discounting operation: given a reliability factor `alpha` for source S, the discounted mass is `m'(A) = alpha * m(A)` for `A != Theta`, `m'(Theta) = 1 - alpha * (1 - m(Theta))`. The current implementation bakes discounting into each converter differently (cosine: explicit fraction to Theta; catboost: probability scaling; pattern: fixed split). This makes it hard to reason about or tune the reliability of each source uniformly.

### D5. No Sensitivity Analysis Infrastructure

There is no mechanism to sweep the 13 constants and measure the impact on classification accuracy. Without this, the constants cannot be defended.

### D6. Pignistic Decision Without Alternatives

The system always makes a leaf-level decision via BetP (classifier.py line 169). There is no:
- **Cautious classification**: "I'm uncertain between A and B, so I report their common parent"
- **Rejection option**: "Conflict is too high, I refuse to classify" (the `needs_clarification` flag exists but doesn't change the output)
- **Interval-dominance decision**: Using the belief interval [Bel, Pl] for ranking instead of BetP

### D7. Edge Cases

1. **All sources vacuous**: Handled correctly (classifier.py lines 151-154), returns vacuous with conflict=0.
2. **Total conflict**: Caught by ValueError (line 162), returns vacuous with conflict=1.0.
3. **Single source**: Works (line 215 returns 0 conflict, line 141 returns the source itself).
4. **Empty frame**: Would crash at line 176 (`raise ValueError("No singletons in frame")`). Not reachable in practice.
5. **CatBoost proba codes not in frame**: **UNHANDLED** -- as noted in C2 Issue 3, filtered probabilities cause a non-summing mass function.

---

## E. Gaps to Close Before Domain-Expert Review (Ranked by Severity)

### SEVERITY 1 -- Will Undermine Credibility

**E1. Source independence violation (B4/D1)**
Cosine and CatBoost share the same embedding vector. This is a textbook violation of Dempster's rule prerequisites. An expert will ask "why Dempster?" when the sources are dependent.
- **Fix**: Either (a) document this explicitly and argue the dependence is weak enough, (b) switch to Denoeux's cautious rule for cosine+catboost, or (c) merge cosine+catboost into a single source.

**E2. 13 unjustified constants (D2)**
Every hardcoded value will be challenged. No calibration data exists.
- **Fix**: Run a grid search or Bayesian optimization over a held-out validation set. Document the chosen values with accuracy curves.

### SEVERITY 2 -- Will Draw Significant Questions

**E3. Non-standard conflict metric (D3)**
The max-pairwise conflict is not the standard K. The actual K from the final combination is available but discarded.
- **Fix**: Return the actual K from `dempster_combine()`. Refactor to return `(BeliefAssignment, float)` tuples.

**E4. CatBoost mass function may not sum to 1.0 (C2 Issue 3)**
When proba codes are filtered out, the mass function is invalid.
- **Fix**: Re-normalize after filtering, or allocate the residual to Theta.

**E5. No hierarchical decision strategy (B2 gap)**
The system always classifies to a leaf. A DST expert expects the uncertainty representation to enable cautious classification.
- **Fix**: Implement a `cautious_classify()` that returns the deepest hierarchy node where `Bel > threshold`.

### SEVERITY 3 -- Good to Address, Not Blocking

**E6. Pattern evidence ignores frequency (C3 Issue 2)**
A column where 1/100 values match email gets the same mass as one where 100/100 match.
- **Fix**: Weight pattern mass by match fraction.

**E7. Name match discards ambiguity (C4 Issue 2)**
Multiple name matches should assign mass to the union, not pick a winner.
- **Fix**: When 2+ categories match at the same tier, assign mass to a `FocalElement` containing all matched codes.

**E8. Confusable pairs mechanism is dead code (B1)**
The feature exists in `FrameOfDiscernment` but is never used.
- **Fix**: Either populate it from empirical confusion matrices or remove it to reduce the surface area of questions.

**E9. Discounting is not uniform across sources (D4)**
Each converter implements discounting differently.
- **Fix**: Implement a generic `discount(ba, alpha)` function and apply it post-construction for each source.

**E10. No sensitivity analysis tooling (D5)**
- **Fix**: Add a parameter sweep script that varies each constant and reports accuracy/Bel/Pl changes.

---

## Overall Assessment

**Are we ready for a domain-expert deep dive?**

**Not yet, but close.** The core DST mathematics is correct (Bel, Pl, BetP, Dempster combination). The restricted focal set strategy is sound. The test suite (41/41 passing) covers the fundamentals. The architecture is clean and well-separated.

The blocking issues are:
1. The source independence violation (E1) -- this is a *theoretical* problem that a DST expert will catch in the first 5 minutes
2. The 13 unjustified constants (E2) -- "why 0.3?" is a question you cannot currently answer

Addressing E1 (document the dependence or switch combination rules) and E2 (run one calibration experiment) would make this defensible. The remaining issues (E3-E10) are improvements that would strengthen the presentation but are not conversation-killers.

**Estimated effort to reach readiness**: 2-3 days focused work on E1 and E2.
