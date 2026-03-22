# DST-Bootstrapped Ground Truth: From 352 Labels to Formal Reference

## Thesis

The DST promotion gives us three things no prior system had:

1. **Calibrated uncertainty** — `Pl - Bel` tells you *how much* the classifier
   doesn't know, not just what it guesses
2. **Conflict detection** — `K` tells you when evidence sources *disagree*,
   not just when confidence is low
3. **Confusable pair awareness** — mass on `{ADID, GUID}` honestly represents
   "I know it's one of these two but can't tell which"

These are exactly the signals you need for an *active learning* loop that
converges on ground truth without exhaustive human labeling.

## Current State

| Metric | Value |
|--------|-------|
| Leaf categories | 175 |
| Existing GT mappings | 352 (column→code) |
| CatBoost accuracy (train→eval) | 95.4% |
| Remaining errors | 16/350, all confusable pairs |
| Confusable pairs defined | 11 |
| Evidence sources | 4 (cosine, catboost, patterns, name_match) |

The 95.4% number is misleading in isolation — the 4.6% error is *structurally
irreducible* with binary classification because every error is a confusable
pair (ADID/GUID, BillingStreet/ShippingStreet, etc.). DST doesn't force a
binary choice on these — it assigns mass to the pair focal element.

## The Bootstrap Loop

### Phase 1: Partition by Epistemic State

Run `classify()` on the full corpus. Every column falls into one of four bins:

| Bin | Condition | Action |
|-----|-----------|--------|
| **Certain** | `Bel > 0.6, gap < 0.15, K < 0.1` | Accept as ground truth |
| **Likely** | `Bel > 0.3, gap < 0.3, K < 0.15` | Accept with audit flag |
| **Confusable** | `needs_clarification` AND mass on a confusable pair > 0.15 | Resolve at *pair* level, not leaf level |
| **Uncertain** | Everything else | Queue for targeted evidence |

The key insight: **Certain** bins don't need human review. The belief
interval is narrow, conflict is low, multiple evidence sources agree.
These are as reliable as expert labels — arguably more so, because they're
reproducible and auditable.

### Phase 2: Confusable Pair Resolution

For the ~16 structurally ambiguous columns, DST already tells you *which*
pair is confusable. The resolution strategy per pair type:

| Pair Type | Resolution Signal | Example |
|-----------|------------------|---------|
| **Billing/Shipping** | Table name or sibling column context | `billing_address` table → BillingStreet |
| **ADID/GUID** | Value format (ADID has vendor prefix) | `gaid_` prefix → ADID |
| **Under13/Under18** | Column name semantics or business context | `coppa_flag` → Under13 |
| **SecurityFlaw/0-day** | Value content analysis | Temporal markers → 0-day |

These are not ML problems — they're *contextual disambiguation* problems.
A new mass function `context_to_mass()` that examines table name, sibling
columns, or value structure can crack each pair with ~0.5 mass on the
correct singleton, collapsing the confusable pair uncertainty.

### Phase 3: Iterative Refinement

```
while quality_metric < target:
    1. Classify full corpus
    2. Partition into bins
    3. For Uncertain bin:
       a. Identify which evidence source has lowest mass
       b. Add targeted evidence (new pattern, new mass function)
       c. Re-classify
    4. For Confusable bin:
       a. Add context_to_mass for the specific pair
       b. Re-classify
    5. Promote Likely → Certain when gap shrinks below threshold
    6. Export Certain + resolved Confusable as ground truth
```

Each iteration *provably* increases the mass on correct singletons or
honestly widens the belief interval (which is itself useful information).

### Phase 4: Formal Ground Truth Export

The output is not just `{column: code}` — it's:

```json
{
  "column_name": {
    "code": "1.1.1.1.1.1.1",
    "belief": 0.82,
    "plausibility": 0.91,
    "conflict": 0.03,
    "evidence_sources": {"cosine": 0.7, "name_match": 0.6, "patterns": 0.9},
    "belief_path": [
      {"code": "1.1.1.1.1.1.1", "label": "PAN", "bel": 0.82, "pl": 0.91},
      {"code": "1.1.1.1.1.1", "label": "Payment Card Data", "bel": 0.85, "pl": 0.95},
      {"code": "1.1.1.1.1", "label": "Payment Data", "bel": 0.88, "pl": 0.97}
    ],
    "provenance": "dst_bootstrap_v1",
    "audit_status": "certain"
  }
}
```

Every label carries its own confidence certificate. Downstream consumers
can threshold on `belief` for their own risk tolerance.

## New Mass Functions Needed

### `context_to_mass(sample, siblings, table_name, frame)`

Table-level and sibling-level contextual evidence. When `billing` appears
in the table name and the column is in a Billing/Shipping confusable pair,
assign 0.6 mass to the Billing singleton.

### `value_structure_to_mass(sample, frame)`

Deep value analysis beyond pattern matching:
- UUID vendor prefixes (Google GAID vs generic UUID)
- Temporal markers in security data
- Numeric range analysis (age fields, zip codes)
- String length distributions

### `cross_column_to_mass(sample, siblings, frame)`

Co-occurrence evidence: if sibling columns are already classified with
high belief, use that to constrain this column. A table with `billing_city`
(Bel=0.8) and an ambiguous address column → mass toward BillingStreet.

## Why This Is Superior to Expert Labeling

1. **Reproducible**: Run the same pipeline, get the same labels with the
   same belief intervals. No inter-annotator disagreement.

2. **Self-auditing**: Every label carries a formal uncertainty certificate.
   You don't trust labels — you trust the math.

3. **Incrementally improvable**: Adding one new mass function (say,
   value_structure_to_mass) re-grades the entire corpus. Expert labels
   are static.

4. **Honest about ambiguity**: When ADID and GUID are genuinely
   indistinguishable from column data alone, the system says so
   (`mass({ADID,GUID}) = 0.4`) instead of flipping a coin.

5. **Hierarchically consistent**: Bel(Payment Card Data) >= Bel(PAN) is
   guaranteed by construction. Expert labels don't enforce this.

## Quality Target

| Metric | Current | Target |
|--------|---------|--------|
| Certain bin (Bel>0.6, gap<0.15) | ~85% of corpus (est.) | >95% |
| Confusable resolved | 0/11 pairs | 11/11 |
| Remaining Uncertain | ~10% (est.) | <2% |
| Effective accuracy | 95.4% (binary) | 98%+ (with honest uncertainty) |

The "98%+" is not a binary accuracy number — it means 98% of columns have
`Bel > 0.5` on the correct leaf, and the remaining 2% have honest
uncertainty intervals that flag them for human review rather than
silently miscategorizing.

## Implementation Order

1. **Partition script** — Run classify on full corpus, bin by epistemic state,
   report bin sizes and the specific categories/pairs in each bin.
   (~2 hours, validates the thesis)

2. **`context_to_mass`** — Table name + sibling context mass function.
   (~3 hours, resolves Billing/Shipping pairs)

3. **`value_structure_to_mass`** — ADID vendor prefix, age range analysis.
   (~3 hours, resolves ADID/GUID and Under13/18)

4. **Export pipeline** — Formal GT JSON with belief certificates.
   (~1 hour, just serialization)

5. **Validation** — Compare DST-bootstrapped GT against existing
   `meta_tagging_gt.json` on the 352 labeled columns. Should agree on
   >95% and honestly flag the confusable-pair cases where the existing GT
   may itself be wrong.

Total: ~1.5 days to a formally grounded reference that's better than
what months of expert labeling would produce.
