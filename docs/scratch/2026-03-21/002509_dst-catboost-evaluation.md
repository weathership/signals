# DST + CatBoost Evaluation for Hierarchical Uncertainty

Date: 2026-03-21
Branch: rch/sigint

## Problem Statement

The current classifier returns a single `confidence: float` per column — a
point estimate that conflates "this is probably a Payment Card Number" with
"this is definitely some kind of Payment Information but I can't tell which
sub-type."  The downstream UI/UX needs to distinguish these cases so it can:

1. Show **ambiguity** at the right level of the hierarchy (e.g., "Address"
   vs "Home Address" vs "Shipping Address")
2. Request **targeted clarification** (e.g., "provide zip codes to
   disambiguate Home vs Work address")
3. Propagate **hierarchical confidence** (if we're 95% sure it's an Address,
   that's useful even if we're only 40% sure it's a *Shipping* Address)

## Current Architecture Gaps

### 1. Flat confidence model
`Classification.confidence` is a scalar.  No notion of "confident at level 3
but uncertain at level 7" in the dot-notation hierarchy.

### 2. No hierarchy in the classifier
`CategorySet` filters to **leaves only** — the parent-child tree exists in
the data (SIGDG: `parent_code` field; annotations: dot-prefix nesting) but
is discarded before classification.  The classifier never considers whether
a column is "definitely 1.1.1 (Identity Document) but ambiguous between
1.1.1.1 (Passport) and 1.1.1.2 (Drivers License)."

### 3. Single-method confidence
Cosine similarity and XGBoost produce independent confidence scores, but
they're never combined into a joint belief.  The "three-signal comparison"
is for evaluation only — at inference time, a single method runs.

---

## Dempster-Shafer Theory (DST) — Applicability Assessment

### What DST provides

DST operates on **belief functions** over a frame of discernment (our
category set).  Unlike Bayesian probability, DST assigns mass to **subsets**
of hypotheses, not just singletons:

- `m({PaymentCardNumber}) = 0.6` — 60% evidence for exactly PAN
- `m({PaymentCardData}) = 0.2` — 20% evidence for the parent category
- `m({Address, HomeAddress, ShippingAddress}) = 0.15` — 15% evidence for
   some kind of address (but can't tell which)
- `m(Θ) = 0.05` — 5% total ignorance

Key concepts:
- **Belief(A)**: minimum guaranteed support for A (sum of mass on all subsets of A)
- **Plausibility(A)**: maximum possible support for A (sum of mass on all subsets that intersect A)
- **Uncertainty interval**: [Bel(A), Pl(A)] — the gap is genuine ambiguity
- **Dempster's rule**: combines evidence from independent sources (cosine, XGBoost, pattern detectors)

### Why DST fits this problem

1. **Hierarchical partial knowledge.** When values look like addresses but
   could be home or shipping, DST lets us assign mass to `{HomeAddress,
   ShippingAddress, BillingAddress}` rather than forcing a leaf choice.
   The uncertainty interval [Bel, Pl] quantifies exactly how much
   disambiguating information is missing.

2. **Independent evidence combination.** Cosine similarity, XGBoost,
   pattern detectors, and sibling context are genuinely independent signals.
   Dempster's rule combines them without requiring calibrated probabilities
   — each source contributes a mass function, and the combination
   automatically reinforces agreement and downweights conflict.

3. **Explicit ignorance.** DST distinguishes "I have no evidence" (mass on
   Θ) from "evidence is ambiguous" (mass on a subset).  This lets the UI
   distinguish "we haven't analyzed this column" from "we've analyzed it
   but the evidence is genuinely split."

4. **Hierarchical roll-up.** Belief propagates naturally up the hierarchy:
   `Bel(Address) >= Bel(HomeAddress) + Bel(ShippingAddress)`.  If the
   classifier is 0.95-confident it's *some* kind of address, the UI can
   show that with a drill-down indicator at the child level.

### DST implementation considerations

**Frame of discernment:** The annotation taxonomy has 175 leaf categories.
Full DST on 2^175 subsets is computationally impossible.  We need to
restrict mass assignments to:
- Singleton leaves (the current behavior)
- Parent-defined subsets (all children of a parent node)
- Confusable pairs identified from the error analysis (ADID/GUID, BAN/PAN,
  Home/Shipping/Billing Address, etc.)

This gives a **hierarchical DST** with ~300 focal elements instead of 2^175.

**Evidence sources as mass functions:**
- **Cosine classifier:** Convert similarity vector to mass function.  Top-1
  similarity → mass on singleton; remaining similarity mass distributed to
  parent category of top candidates if they share a parent.
- **XGBoost/CatBoost:** `predict_proba()` output → mass function via
  probability-to-mass transform (e.g., Smets' pignistic transform inverse).
- **Pattern detectors:** Each pattern match (credit_card_pattern, ssn_pattern)
  → mass on the corresponding category subset with strength proportional to
  match fraction.
- **Column name:** Name-match evidence as a separate mass function (replacing
  the current additive boost hack).

**Combination:** Dempster's rule for combining independent sources.  When
conflict is high (sources disagree), the normalization factor warns of
unreliable combination — this maps directly to "request clarification."

---

## CatBoost — Applicability Assessment

### Why CatBoost over XGBoost

1. **Native categorical feature support.** CatBoost handles categorical
   features (column_type, pattern_signals, source_table) without manual
   encoding.  XGBoost requires one-hot or target encoding, which inflates
   dimensionality and loses ordinality.

2. **Ordered boosting.** CatBoost uses ordered target statistics to avoid
   target leakage during training — directly relevant given the audit
   finding about self-training leakage.

3. **Built-in uncertainty estimation.** CatBoost supports `predict(data,
   prediction_type='RawFormulaVal')` which returns raw scores suitable for
   calibration, and `virtual_ensembles_predict()` for epistemic uncertainty
   via ensemble disagreement.

4. **Better calibrated probabilities.** CatBoost's `predict_proba()` is
   generally better calibrated than XGBoost's, which matters when we convert
   probabilities to DST mass functions.

5. **GPU training.** For 991-dimensional features × 5,000+ training samples,
   CatBoost's GPU implementation is significantly faster.

### CatBoost as DST evidence source

CatBoost's `virtual_ensembles_predict()` returns per-tree predictions that
can be decomposed into:
- **Mean prediction** → point estimate (like current confidence)
- **Prediction variance** → epistemic uncertainty (model doesn't have enough
  training data for this region)
- **Per-class variance** → which classes the model is confused between

This decomposes naturally into a DST mass function:
- High mean, low variance → mass on singleton
- High mean, high variance → mass on parent subset (model is unsure which
  child, but confident in parent)
- Low mean across all classes → mass on Θ (ignorance)

---

## Proposed Architecture

### New data structures

```python
@dataclass(frozen=True)
class BeliefAssignment:
    """DST mass function for a single column classification."""
    focal_elements: dict[frozenset[str], float]
    # key: frozenset of category codes  value: mass [0,1]
    # sum of all masses = 1.0

    def belief(self, codes: set[str]) -> float: ...
    def plausibility(self, codes: set[str]) -> float: ...
    def uncertainty(self, codes: set[str]) -> tuple[float, float]: ...
    def pignistic_probability(self) -> dict[str, float]: ...
    def best_leaf(self) -> tuple[str, float]: ...
    def best_at_level(self, level: int) -> tuple[str, float]: ...

@dataclass(frozen=True)
class HierarchicalClassification:
    """Replaces Classification — adds DST belief + hierarchy."""
    category: ReferenceCategory       # best leaf prediction
    confidence: float                  # pignistic probability of best leaf
    belief_interval: tuple[float, float]  # [Bel, Pl] for best leaf
    parent_confidence: float           # Bel at parent level
    belief: BeliefAssignment           # full mass function
    evidence: str
    sensitivity_code: str | None = None
    ambiguous_with: list[str] = ()     # codes of confusable alternatives
```

### Pipeline changes

1. **Restore hierarchy in CategorySet:** Keep parent categories alongside
   leaves.  Add `parent_code`, `children`, `ancestors()`, `depth` to
   `ReferenceCategory`.

2. **Replace XGBoost with CatBoost:** Same feature vector (991 dims), but
   use categorical feature indices for pattern flags and column_type.
   Enable virtual ensembles for uncertainty decomposition.

3. **Convert each evidence source to a mass function:**
   - `cosine_mass(sims, categories)` → `BeliefAssignment`
   - `catboost_mass(proba, variance, categories)` → `BeliefAssignment`
   - `pattern_mass(patterns, categories)` → `BeliefAssignment`
   - `name_mass(column_name, categories)` → `BeliefAssignment`

4. **Combine via Dempster's rule:** `combine(m1, m2, ..., mn)` with
   conflict tracking.

5. **Extract hierarchical confidence:** From combined mass function,
   compute Bel/Pl at each level of the hierarchy.

### UI/UX output

The combined `HierarchicalClassification` surfaces:
- **Leaf prediction + confidence:** "Payment Card Number (0.85)"
- **Belief interval:** "[0.72, 0.91]" — gap of 0.19 indicates moderate ambiguity
- **Parent confidence:** "Payment Information (0.95)" — very confident at parent level
- **Ambiguous alternatives:** "Could also be: Bank Account Number (Pl=0.18)"
- **Conflict indicator:** High Dempster conflict → "sources disagree, manual review needed"

For the address example: "Address (Bel=0.94), but Home vs Shipping vs
Billing unclear (Bel=0.31 each).  Request: zip code patterns could
disambiguate."

---

## Implementation Phases

### Phase 1: CatBoost swap + calibration
- Replace XGBClassifier with CatBoostClassifier in `_run_xgboost_train_eval`
- Enable virtual ensembles
- Measure calibration (reliability diagram) vs XGBoost
- Fix self-training leak (exclude pseudo-labeled columns from eval)

### Phase 2: Hierarchical CategorySet
- Add parent-child relationships to ReferenceCategory
- Build hierarchy tree from dot-notation codes
- Add `ancestors()`, `children()`, `depth` properties
- Identify confusable subsets from error analysis

### Phase 3: DST mass functions
- Implement BeliefAssignment with Dempster's combination rule
- Convert cosine sims → mass function
- Convert CatBoost predict_proba + variance → mass function
- Convert pattern detector hits → mass function
- Separate name-match into its own mass function (replacing boost hack)

### Phase 4: HierarchicalClassification
- Replace Classification with HierarchicalClassification
- Update pipeline to emit belief intervals and parent confidence
- Update parquet output schema with DST columns
- Update Atlas tagging to include uncertainty metadata

### Phase 5: UI/UX integration
- Expose ambiguity indicators for visualization
- Emit clarification requests when Bel-Pl gap exceeds threshold
- Hierarchical drill-down from confident parent to ambiguous children
