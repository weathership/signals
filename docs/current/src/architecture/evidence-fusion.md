# Evidence Fusion

The evidence fusion layer replaces single-point confidence scores with belief intervals derived from Dempster-Shafer Theory (DST). Each evidence source — cosine similarity, CatBoost prediction, pattern detection, name matching — produces an independent mass function. These are combined via Dempster's rule of combination to yield belief intervals \\([Bel(A), Pl(A)]\\) at every level of the category hierarchy.

The key insight: a flat confidence of 0.85 conflates "definitely Payment Card Number" with "definitely some kind of Payment Information but unsure which sub-type." Belief intervals expose this distinction. When \\(Bel(\text{PaymentCardData}) = 0.6\\) but \\(Pl(\text{PaymentCardData}) = 0.95\\), the gap signals that evidence supports the broader category but is ambiguous at the leaf level — a meaningful signal for downstream consumers and human reviewers.

## Theoretical Foundation

### Dempster-Shafer Theory

DST generalizes Bayesian probability by assigning mass not only to singleton hypotheses but to subsets of the frame of discernment \\(\Theta\\). A mass function \\(m: 2^\Theta \to [0,1]\\) satisfies \\(m(\emptyset) = 0\\) and \\(\sum_{A \subseteq \Theta} m(A) = 1\\). The belief function \\(Bel(A) = \sum_{B \subseteq A} m(B)\\) gives a lower bound on the evidence supporting \\(A\\), while the plausibility function \\(Pl(A) = \sum_{B \cap A \neq \emptyset} m(B)\\) gives an upper bound. The interval \\([Bel(A), Pl(A)]\\) represents epistemic uncertainty: what the evidence commits to versus what it does not rule out.

For decision-making, the pignistic probability transform [Smets & Kennes, 1994] redistributes mass from composite focal elements to singletons:

\\[BetP(\\{x\\}) = \sum_{A \ni x} \frac{m(A)}{|A|}\\]

This converts belief intervals into point probabilities suitable for classification decisions while preserving uncertainty information in the intervals themselves.

### Dempster's Rule of Combination

Given two independent mass functions \\(m_1\\) and \\(m_2\\), Dempster's rule produces:

\\[m_{1 \oplus 2}(A) = \frac{1}{1-K} \sum_{B \cap C = A} m_1(B) \cdot m_2(C)\\]

where \\(K = \sum_{B \cap C = \emptyset} m_1(B) \cdot m_2(C)\\) measures conflict between sources. High conflict (\\(K > 0.2\\)) signals that sources disagree — a diagnostic the flat-confidence approach discards entirely.

### Closed-World Assumption

The implementation enforces \\(m(\emptyset) = 0\\) (closed-world assumption), appropriate for a classification task with an exhaustive taxonomy. Mass on \\(\Theta\\) represents ignorance ("one of these categories, but I don't know which"), not rejection. The Transferable Belief Model's open-world extension [Smets, 1990] would allow \\(m(\emptyset) > 0\\) for unknown-category detection — a potential future direction.

## Architecture

```d2
direction: down

sources: Evidence Sources {
  style.fill: "#e8f4f8"

  cosine: "Cosine\nSimilarity" {
    tooltip: "Embedding similarity → softmax → discounted mass"
  }
  catboost: "CatBoost\nProbability" {
    tooltip: "predict_proba() → discounted mass (variance-aware)"
  }
  pattern: "Pattern\nDetection" {
    tooltip: "Regex matches → category mass"
  }
  name_match: "Name\nMatch" {
    tooltip: "Column name → category label matching"
  }
}

mass: Mass Functions {
  style.fill: "#f0e8f8"

  m1: "m₁: cosine_to_mass()" {
    tooltip: "softmax(sims) × (1-discount), remainder → Θ"
  }
  m2: "m₂: catboost_to_mass()" {
    tooltip: "proba × (1-discount), variance → adaptive discount"
  }
  m3: "m₃: pattern_to_mass()" {
    tooltip: "matched codes → 0.9 mass, Θ → 0.1"
  }
  m4: "m₄: name_match_to_mass()" {
    tooltip: "exact=0.7, abbrev=0.5, overlap=0.3, none=vacuous"
  }
}

combine: "Dempster's Rule\nm₁₂ = m₁ ⊕ m₂\nm₁₂₃ = m₁₂ ⊕ m₃\nm₁₂₃₄ = m₁₂₃ ⊕ m₄" {
  style.fill: "#fff3e0"
  tooltip: "Conjunctive combination, normalized by 1/(1-K)"
}

decide: Decision Layer {
  style.fill: "#e8f8e8"

  betp: "BetP({x})\nPignistic Transform" {
    tooltip: "Best singleton for classification decision"
  }
  interval: "[Bel(A), Pl(A)]\nBelief Intervals" {
    tooltip: "At every hierarchy level for uncertainty reporting"
  }
  conflict: "K: Conflict\nDiagnostic" {
    tooltip: "High K → sources disagree → flag for review"
  }
}

sources.cosine -> mass.m1
sources.catboost -> mass.m2
sources.pattern -> mass.m3
sources.name_match -> mass.m4

mass.m1 -> combine
mass.m2 -> combine
mass.m3 -> combine
mass.m4 -> combine

combine -> decide.betp
combine -> decide.interval
combine -> decide.conflict
```

## Restricted Focal Set

For a taxonomy with \\(N\\) leaves, the power set \\(2^N\\) is computationally intractable for any non-trivial taxonomy. The implementation uses a restricted focal set [Denoeux, 2008] containing only semantically meaningful subsets:

| Element Type | Count (SIGDG) | Description |
|-------------|---------------|-------------|
| Singletons | 30 | One per leaf category |
| Internal nodes | 12 | Descendant leaf sets for each parent in the hierarchy |
| Confusable pairs | ~10 | Manually specified pairs from error analysis |
| \\(\Theta\\) | 1 | Full frame (total ignorance) |
| **Total** | **~53** | vs. \\(2^{30} \approx 10^{9}\\) |

This exploits the category hierarchy: rather than tracking arbitrary subsets, focal elements correspond to nodes in the taxonomy tree. An internal node like `IdentityInformation (0010)` maps to the focal element \\(\\{0011, 0012, 0013\\}\\) — the set of its descendant leaves.

```d2
direction: down

frame: "Frame of Discernment (Θ)" {
  style.fill: "#fafafa"

  info: "InformationEntity\n{all 175 leaves}" {
    style.fill: "#e8f4f8"

    identity: "IdentityInfo\n{0011, 0012, 0013}" {
      style.fill: "#f0e8f8"
      gov: "GovtID\n{0085, ...}" {style.fill: "#e8f8e8"}
      plat: "PlatformID\n{0076, ...}" {style.fill: "#e8f8e8"}
      dev: "DeviceID\n{0013}" {style.fill: "#e8f8e8"}
    }

    personal: "PersonalInfo\n{0021-0026 leaves}" {
      style.fill: "#f0e8f8"
      financial: "FinancialInfo\n{0070, ...}" {style.fill: "#e8f8e8"}
      contact: "ContactInfo\n{0074, 0076, ...}" {style.fill: "#e8f8e8"}
    }
  }

  confusable: "Confusable Pairs\n{ADID,GUID}, {BAN,PAN}" {
    style.fill: "#fff3e0"
  }
}
```

### Complexity

Each Dempster combination computes pairwise intersections over focal elements. With \\(F\\) focal elements and \\(S = 4\\) sources requiring \\(S-1 = 3\\) combinations:

\\[\text{Cost per column} = 3 \times F^2\\]

For the SIGDG taxonomy (\\(F \approx 53\\)), this is ~8,400 operations per column — negligible compared to the ~50ms sentence-transformer encode step. Even for larger taxonomies with hundreds of focal elements, DST overhead remains sub-millisecond.

## Mass Function Converters

Each evidence source implements a converter from raw signal to `BeliefAssignment` (mass function). All converters produce valid mass functions: non-negative masses summing to 1.0, with a fraction allocated to \\(\Theta\\) representing the source's inherent uncertainty.

### Cosine Similarity → Mass

```
cosine_to_mass(similarities, frame, discount=0.3)
```

Applies softmax to cosine similarities across all leaf categories, then discounts by allocating 30% of mass to \\(\Theta\\):

\\[m(\\{c_i\\}) = \text{softmax}(s_i) \times (1 - d), \quad m(\Theta) = d\\]

The softmax transform converts raw cosine similarities (which may be negative or arbitrarily scaled) into a probability distribution. The discount parameter \\(d\\) controls how much trust is placed in cosine similarity as a standalone signal.

### CatBoost Probability → Mass

```
catboost_to_mass(proba, frame, virtual_ensembles_variance=None)
```

Maps `predict_proba()` output directly to singleton masses. When CatBoost's virtual ensembles provide per-class variance estimates, high variance increases the discount (more mass to \\(\Theta\\)):

\\[d = \min(0.5,\ 0.1 + \bar{\sigma}^2 \times 1.6)\\]

This adaptive discounting means CatBoost contributes less evidence when its own uncertainty is high — a principled integration of aleatoric uncertainty from the model into the epistemic uncertainty framework.

### Pattern Detection → Mass

```
pattern_to_mass(pattern_signals, frame, pattern_category_map=None)
```

Binary pattern signals (email regex, SSN regex, credit card regex, etc.) map to known category codes. When patterns are detected, mass is concentrated on matched categories with high confidence (0.9) because regex patterns have near-zero false positive rates:

| Pattern | Category | Rationale |
|---------|----------|-----------|
| `email_pattern` | EmailAddress (0076) | `user@domain.tld` is unambiguous |
| `ssn_pattern` | TaxIdentifier (0085) | `XXX-XX-XXXX` format is distinctive |
| `credit_card_pattern` | PaymentCardData (0070) | Luhn-valid 16-digit sequences |
| `phone_pattern` | PhoneNumber (0074) | E.164 / national format detection |
| `uuid_pattern` | DeviceIdentifier (0013) | RFC 4122 hex format |
| `ipv4_pattern` | ConfigurationData (0041) | Dotted quad notation |
| `url_pattern` | ConfigurationData (0041) | HTTP(S) URL format |

When no patterns are detected, the function returns a *vacuous* mass function (all mass on \\(\Theta\\)), contributing no evidence rather than misleading evidence.

### Name Match → Mass

```
name_match_to_mass(column_name, frame, category_set)
```

Replaces the previous additive boost heuristic with a proper evidence source. Three matching tiers:

| Match Level | Mass on Singleton | Mass on \\(\Theta\\) | Example |
|-------------|-------------------|----------------------|---------|
| Exact | 0.70 | 0.30 | `"tax identifier"` = `"TaxIdentifier"` |
| Abbreviation | 0.50 | 0.50 | `"ssn"` = `"SSN"` (abbrev) |
| Word overlap | 0.30 | 0.70 | `"customer email address"` ⊃ `"email address"` |
| No match | 0.00 | 1.00 | Vacuous — no evidence contributed |

This formalization means name matching no longer inflates confidence scores. Instead, its evidence is combined with other sources via Dempster's rule, where agreement reinforces and disagreement raises the conflict diagnostic.

## Cross-Benchmark Analysis: Cosine Reliability Regimes

Cross-benchmark experiments reveal that cosine similarity evidence is not uniformly helpful — it ranges from near-perfect (99.4% on semantically named columns) to destructive (1.6% on generic names, where it adds pure conflict to CatBoost's 81.6% accuracy).

### Empirical Evidence

On **GitTables** (2517 columns, all generic names): CatBoost standalone achieves 81.6%, but DST fusion with cosine drops to 71.4%. Mean Dempster conflict \\(K = 0.65\\), with 100% of columns exceeding \\(K > 0.5\\). Cosine evidence is near-random and creates systematic conflict.

On the **SIGDG evaluation set** (mixed semantic and opaque names): cosine achieves 99.4% on semantically named columns but only 8.0% on opaque-name columns. CatBoost adds value precisely where cosine fails (29.7% on opaque columns). The union ceiling of both methods reaches 66.0% — 12 points above either alone.

### Three Regimes

| Cosine Confidence | Regime | Observed Behavior |
|-------------------|--------|-------------------|
| > 0.35 | High — cosine is reliable | Cosine near-certain; CatBoost adds marginal value |
| 0.05 - 0.35 | Medium — both sources contribute | Standard Dempster combination is appropriate |
| < 0.05 | Low — cosine has no signal | Cosine creates destructive conflict; CatBoost should dominate |

The current implementation uses fixed discounts (0.3 for cosine, 0.15 for CatBoost). The regime analysis motivates a planned refinement: **confidence-gated adaptive discounting**, where the cosine discount increases when cosine confidence is low and decreases when it is high. This is tracked as part of the [calibration experiment (R-02)](../reference/research-roadmap.md) in the research roadmap.

The regime structure also informs the source independence analysis — cosine and CatBoost share the embedding space, but in different regimes their contributions are nearly orthogonal: cosine dominates on semantic names (where CatBoost is redundant) and CatBoost dominates on opaque names (where cosine is noise).

See [Heuristic Elucidation](./heuristic-elucidation.md#cross-benchmark-validation) for the full cross-benchmark analysis.

## Hierarchical Classification Output

`classify_dst()` returns a `HierarchicalClassification` that provides belief intervals at every level of the taxonomy:

```python
result = classifier.classify_dst(sample, frame, category_set)

# Leaf-level belief interval
bel, pl = result.interval_at("0085")   # TaxIdentifier
# → (0.72, 0.91) — strong evidence, moderate uncertainty

# Parent-level belief interval
bel, pl = result.interval_at("0011")   # GovernmentIdentifier
# → (0.72, 0.95) — higher plausibility at parent level

# Root-level belief interval
bel, pl = result.interval_at("0010")   # IdentityInformation
# → (0.72, 0.98) — near-certain at this level

# Diagnostics
result.uncertainty_gap    # Pl - Bel for predicted leaf
result.conflict           # Dempster conflict K
result.needs_clarification  # gap > 0.3 or K > 0.2
```

### Evidence String Format

When DST is active, the evidence string encodes source contributions and the belief interval for the predicted category:

```
dst(cosine=0.621, catboost=0.834, patterns=0.900) → TaxIdentifier [Bel=0.72, Pl=0.91, K=0.05]
```

### Parquet Output Columns

The `--dst` flag adds 7 columns to the pipeline parquet output:

| Column | Type | Description |
|--------|------|-------------|
| `dst_belief` | float64 | \\(Bel\\) for predicted leaf singleton |
| `dst_plausibility` | float64 | \\(Pl\\) for predicted leaf singleton |
| `dst_uncertainty_gap` | float64 | \\(Pl - Bel\\): width of the belief interval |
| `dst_conflict` | float64 | Dempster conflict \\(K\\) across sources |
| `dst_needs_clarification` | bool | \\(\text{gap} > 0.3\\) or \\(K > 0.2\\) |
| `dst_evidence_sources` | string | JSON: per-source mass summaries |
| `dst_belief_path` | string | JSON: belief intervals at each hierarchy level |

## Relationship to Prior Pipeline

The `classify()` method is unchanged — existing callers see no difference. `classify_dst()` is a parallel path that reuses the same embedding infrastructure but wraps evidence in mass functions before combining:

```d2
direction: right

sample: "ColumnSample" {
  style.fill: "#fff3e0"
}

embed: "Embedding\nEncode" {
  style.fill: "#e8f4f8"
}

classic: "classify()" {
  style.fill: "#e8f8e8"
  cosine: "Cosine\nSimilarity"
  boost: "Name\nBoost"
  out: "Classification\nconfidence: float"
}

dst: "classify_dst()" {
  style.fill: "#f0e8f8"
  mass: "Mass\nFunctions ×4"
  combine: "Dempster\nCombine"
  out: "HierarchicalClassification\n[Bel, Pl] intervals"
}

sample -> embed
embed -> classic.cosine
classic.cosine -> classic.boost -> classic.out

embed -> dst.mass
dst.mass -> dst.combine -> dst.out
```

## Implementation

| File | Purpose |
|------|---------|
| `src/sigint/belief.py` | `FocalElement`, `BeliefAssignment`, `dempster_combine()`, `FrameOfDiscernment` |
| `src/sigint/mass_functions.py` | `cosine_to_mass()`, `catboost_to_mass()`, `pattern_to_mass()`, `name_match_to_mass()` |
| `src/sigint/classifier.py` | `HierarchicalClassification` with belief methods and `from_combined_evidence()` |
| `src/sigint/embedding_classifier.py` | `classify_dst()` orchestration |
| `src/sigint/category_set.py` | `HierarchicalCategorySet` with tree navigation |

### Test Coverage

72 tests cover the DST layer (363 total across the sigint package):

| Test File | Count | Scope |
|-----------|-------|-------|
| `test_belief.py` | 26 | Mass functions, Bel/Pl computation, Dempster combination, frame construction |
| `test_mass_functions.py` | 15 | All 4 converters: high-confidence, uniform, vacuous, edge cases |
| `test_hierarchical_category_set.py` | 16 | Tree navigation, backward compatibility, factory functions |
| `test_hierarchical_classification.py` | 15 | Belief methods, uncertainty diagnostics, classify_dst integration |

## Combination Rule Choice & Limitations

### Why Classical Dempster

The implementation uses Dempster's conjunctive rule with normalization (the orthogonal sum) for several engineering reasons:

1. **Associativity and commutativity.** The combination order does not affect the result. Sources can be added or removed without restructuring the pipeline. `combine_multiple()` applies left-to-right sequential combination, but the final mass function is order-independent.
2. **Traceability.** Every combined mass can be decomposed back to source contributions. The evidence string records per-source mass summaries alongside \\([Bel, Pl, K]\\), making audit straightforward.
3. **Conflict as diagnostic.** Dempster's \\(K\\) is not a flaw — it is a feature. High conflict between sources is a meaningful signal that something is wrong (ambiguous column, mismatched evidence). The `needs_clarification` flag (\\(K > 0.2\\) or gap \\(> 0.3\\)) routes uncertain columns to human review rather than suppressing disagreement.
4. **Restricted focal set efficiency.** With ~53 focal elements and 3 pairwise combinations, the \\(O(F^2)\\) cost per column is negligible. More complex rules (e.g., PCR6) would add implementation complexity without proportional benefit at this scale.

### Known Limitations

**High-conflict sensitivity (Zadeh's paradox).** Classical Dempster with normalization concentrates mass on the intersection even when conflict is extreme. Zadeh (1986) demonstrated that when two sources assign mass to disjoint singletons, the normalized result assigns all mass to a third category with negligible original support. In our setting, this scenario is mitigated by three factors: (a) all four sources operate over the same embedding-derived information, making fully disjoint evidence unlikely in practice; (b) pattern and name-match sources return vacuous mass functions when they have no signal, contributing zero conflict rather than misleading evidence; (c) the \\(K > 0.2\\) flag identifies problematic cases for human review. However, no formal fallback rule is triggered — this is a passive diagnostic, not an active conflict resolution mechanism.

**Source independence.** Dempster's rule assumes independent evidence sources. Cosine similarity and CatBoost both consume the same sentence-transformer embedding vector — they are not independent. Name matching partially overlaps with cosine (column name is part of embedding text). The cross-benchmark regime analysis suggests their contributions are *functionally* orthogonal in most cases (cosine dominates on semantic names, CatBoost on opaque names), but this is an empirical observation, not a theoretical guarantee. Options under consideration include merging cosine and CatBoost into a single source, decoupling their feature spaces, or adopting a cautious rule that does not require independence (Denoeux, 2008). See [R-01: Source Independence Analysis](../reference/research-roadmap.md).

**Heuristic discounting.** The fixed discount constants (cosine: 0.30, CatBoost: 0.15, pattern: 0.10, name match: 0.30/0.50/0.70) were set by engineering judgment. No sensitivity analysis, grid search, or Bayesian optimization has been published. CatBoost's variance-adaptive discount is the one exception — it uses virtual ensemble variance to modulate trust. A systematic calibration experiment ([R-02](../reference/research-roadmap.md)) is planned: sweep constants against held-out data, measure accuracy and Expected Calibration Error (ECE), and extract optimized values with confidence intervals.

**Hierarchical propagation.** Belief and plausibility at internal taxonomy nodes are computed by standard summation over subsets (\\(Bel(A) = \sum_{B \subseteq A} m(B)\\)), which is correct for arbitrary focal sets. The restricted focal set — singletons, internal nodes, confusable pairs, \\(\Theta\\) — means these sums involve only the pre-computed focal elements that are subsets of a given node's descendant set. This is not optimized via dedicated hierarchical algorithms (e.g., Shafer-Logan or evidential network propagation). For the current focal set size (~53 elements), brute-force summation is adequate. Larger taxonomies or dense confusable-pair sets would benefit from lattice-based optimization.

**Closed-world assumption.** The implementation enforces \\(m(\emptyset) = 0\\), appropriate for classification against an exhaustive taxonomy. Mass on \\(\Theta\\) represents "one of these categories, but I don't know which" — not "none of the above." The Transferable Belief Model's open-world extension (Smets, 1990) would allow \\(m(\emptyset) > 0\\) for unknown-category detection. This is a potential extension for schema-drift scenarios where new column types appear that do not map to any SIGDG category.

**Decision mapping.** The pignistic transform (BetP) always selects a leaf singleton for the classification decision. When evidence supports a parent node but is ambiguous among its children, the classifier still commits to a specific leaf — even when \\(Bel(\text{leaf}) \ll Bel(\text{parent})\\). A cautious classification approach following Denoeux & Zouhal (2001) would return the deepest hierarchy node where \\(Bel(A) > \tau\\), preserving the hierarchy's value. See [R-05: Cautious Hierarchical Classification](../reference/research-roadmap.md).

### Alternative Rules Considered

| Rule | Property | Trade-off |
|------|----------|-----------|
| **Yager (1987)** | Conflict mass → \\(\Theta\\) instead of normalization | Conservative; avoids Zadeh paradox but increases ignorance |
| **Dubois-Prade (1988)** | Disjunctive: conflict mass → union \\(A \cup B\\) | Preserves information but produces large focal elements |
| **Murphy (2000)** | Average masses before single Dempster combination | Simple; handles high conflict but loses sequential diagnostics |
| **Denoeux cautious (2008)** | Weight-based; does not require independence | Theoretically cleanest for our setting; more complex to implement |
| **PCR6 (Smarandache-Dezert)** | Proportional conflict redistribution | Addresses Zadeh paradox directly; computationally expensive |

The modular architecture (`belief.py` + `mass_functions.py`) is designed to allow rule substitution — `dempster_combine()` can be swapped for any pairwise combination function with the same signature `(BeliefAssignment, BeliefAssignment) → (BeliefAssignment, float)`. A planned branch will benchmark Murphy averaging and Yager's rule against classical Dempster on high-\\(K\\) synthetic columns.

## References

- Dubois, D. & Prade, H. (1988). Representation and combination of uncertainty with belief functions and possibility measures. *Computational Intelligence*, 4(3), 244-264.
- Denoeux, T. (2008). Conjunctive and disjunctive combination of belief functions induced by nondistinct bodies of evidence. *Artificial Intelligence*, 172(2-3), 234-264.
- Denoeux, T. & Zouhal, L.M. (2001). Handling possibilistic labels in pattern classification using evidential reasoning. *Fuzzy Sets and Systems*, 122(3), 409-424.
- Murphy, C.K. (2000). Combining belief functions when evidence conflicts. *Decision Support Systems*, 29(1), 1-9.
- Sentz, K. & Ferson, S. (2002). Combination of Evidence in Dempster-Shafer Theory. *Sandia National Laboratories*, SAND2002-0835.
- Shafer, G. (1976). *A Mathematical Theory of Evidence*. Princeton University Press.
- Smarandache, F. & Dezert, J. (2005). Information fusion based on new proportional conflict redistribution rules. *Proceedings of Fusion 2005*.
- Smets, P. (1990). The combination of evidence in the Transferable Belief Model. *IEEE Transactions on Pattern Analysis and Machine Intelligence*, 12(5), 447-458.
- Smets, P. & Kennes, R. (1994). The Transferable Belief Model. *Artificial Intelligence*, 66(2), 191-234.
- Yager, R.R. (1987). On the Dempster-Shafer framework and new combination rules. *Information Sciences*, 41(2), 93-137.
- Zadeh, L.A. (1986). A simple view of the Dempster-Shafer theory of evidence and its implication for the rule of combination. *AI Magazine*, 7(2), 85-90.
