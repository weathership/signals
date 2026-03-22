# GitTables CTA Benchmark — Baseline Scores

**Date**: 2026-03-22
**Branch**: `rch/sage-gpu-accel`
**Model**: `all-MiniLM-L6-v2` (384-dim, CPU)

## Headline Metrics

| Metric                  | Score   |
|-------------------------|---------|
| Micro-F1                | 0.0163  |
| Macro-F1                | 0.0025  |
| Exact match accuracy    | 1.6%    |
| Hierarchical accuracy   | 1.6%    |
| Mean belief             | 0.1205  |
| Mean uncertainty gap    | 0.2662  |
| Mean conflict (K)       | 0.1180  |
| Clarification rate      | 41.6%   |

Previous run (before value descriptions): micro-F1 = 0.0099.
Improvement: +64% relative, but still effectively random.

## SOTA Comparison

| Method                      | Micro-F1 |
|-----------------------------|----------|
| ArcheType-GPT4 (LLM)       | ~0.86    |
| ChatGPT (LLM)              | ~0.85    |
| SemTab 2021 winner          | ~0.59    |
| **DST evidence fusion**    | **0.0163** |

## Dataset Characteristics

- **2517** target columns, all from CSV tables with generic positional headers
- **100%** of column names are generic (`col0`, `col1`, empty string, etc.)
- **211** columns (8%) have no sample values at all — these get zero value signal
- **92%** of columns got value description substitution (non-empty values available)

## Archetype Classification

The value description heuristics correctly bucket columns into archetypes.
Accuracy **within** each archetype is near zero — the problem is disambiguation
among 122 fine-grained types within each coarse shape:

| Value Archetype                     |   N  | Accuracy |
|-------------------------------------|------|----------|
| Sequential integers (id-like)       |  556 |   2.7%   |
| Short text labels or names          |  568 |   1.6%   |
| Categorical labels or codes         |  343 |   0.9%   |
| Text values (generic)               |  241 |   5.8%   |
| Decimal numeric measurements        |  226 |   0.0%   |
| No sample values (name only)        |  211 |   0.0%   |
| Integer values                      |  178 |   0.0%   |
| UUID identifiers                    |   99 |   0.0%   |
| Long text content                   |   70 |   0.0%   |
| Text phrases                        |   16 |   0.0%   |
| Date (YYYY-MM-DD)                   |    6 |   0.0%   |
| URLs                                |    3 |   0.0%   |

## Primary Confusion Patterns

| GT Type (top 10)  | Count | Correct | Top Misclassification |
|-------------------|-------|---------|-----------------------|
| id                |   323 |      15 | name (302)            |
| comment           |   228 |       0 | long name (209)       |
| min               |   224 |       0 | author (91)           |
| name              |   211 |      10 | class (94)            |
| type              |   144 |       3 | id (45)               |
| status            |   106 |       0 | value (82)            |
| year              |   102 |       0 | long name (63)        |
| note              |   102 |       0 | id (41)               |
| rank              |   100 |       0 | id (96)               |
| genus             |    98 |       2 | long name (63)        |

## Analysis

### What worked
1. Value description substitution fires for 92% of columns
2. Archetypes are correctly identified (dates, sequential ints, categoricals, etc.)
3. Pattern detection correctly tags date/email/URL/UUID columns
4. Enriched category embedding_text includes value-pattern descriptions

### Why the score is still near-random

**Within-archetype ambiguity**: The classifier correctly identifies that a column
contains "sequential integers, likely identifiers or index" but cannot distinguish
whether this should map to `id`, `rank`, `year`, `number`, or `parent` (all of
which contain sequential integers in GitTables). With 122 categories and MiniLM-L6
(384 dimensions), the softmax over cosine similarities is too flat to separate
semantically similar types.

**Specific failure modes**:
- `id` → `name`: 302/323 id columns predicted as name. Both categories mention
  "high cardinality" and "unique" in their enriched text.
- `comment` → `long name`: 209/228. Comment values are long text strings that
  the classifier can't distinguish from "long name" descriptions.
- `rank` → `id`: 96/100. Rank values are integers, indistinguishable from id
  without column name context.
- `status` → `value`: 82/106. Status values (often encoded as integers like 0/1)
  look like generic numeric values.

**Root cause**: This benchmark has **zero semantic column headers**. All 2517
columns are `col0`, `col1`, etc. Our classifier's strength (name matching,
name-informed embedding) is completely neutralized. What remains is cosine
similarity between value-shape descriptions and category descriptions —
insufficient for 122-way classification.

### The gap to SOTA is expected

LLM-based approaches (ArcheType-GPT4 at 0.86) use GPT-4 to **reason** about
value patterns, relationships, and context — far beyond cosine similarity.
SemTab 2021 (0.59) uses table-level context and external knowledge bases.
Our approach uses only local value statistics and a frozen 384-dim embedding,
which was never designed for 122-way fine-grained CTA.

## Next Steps (if pursuing higher scores)

1. **Reduce to coarse archetypes**: Instead of 122 types, classify into ~8-10
   coarse buckets matching our value descriptions. Expected: 30-50% accuracy.
2. **Table-level features**: Use cross-column correlations (if col0=int and
   col1=text, col0 is more likely id than rank).
3. **CatBoost training**: Train on a split of the GitTables data itself.
4. **Larger embedding model**: Replace MiniLM-L6 with a model trained on
   tabular data (e.g., DODUO, TURL).
5. **LLM-in-the-loop**: Use an LLM for the within-archetype disambiguation step.
