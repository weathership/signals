# Embedding Classifier Generality Audit

## Summary

Audited the embedding classifier implementation for generality — ensuring it
works with unseen tables, columns, row data, and annotations.  Fixed 5 issues.
75 tests pass (7 new), 100% accuracy maintained on meta-tagging dataset.

## Issues Found and Fixed

### 1. Meta-tagging-specific logic in general classifier module (P0)

**Problem**: `is_data_column()` and `_ANNOTATION_PREFIXES` lived in
`embedding_classifier.py` but encode knowledge specific to the meta-tagging CSV
format.  Production columns named `data_source`, `key_material`, `val_amount`
would be incorrectly filtered out.

**Fix**: Moved `is_data_column()` and `_ANNOTATION_PREFIXES` to `category_set.py`
alongside `extract_ground_truth()` (both are meta-tagging-specific).  Updated
imports in `build_sigint_embeddings.py` and tests.  Added docstring noting this
is dataset-specific, not for general production column filtering.

### 2. Duplicate `_ANNOTATION_PREFIXES` (P0)

**Problem**: The same prefix list was defined in both `embedding_classifier.py`
and `category_set.py`.

**Fix**: Single source of truth in `category_set.py`.

### 3. Misleading evidence string (P0)

**Problem**: Evidence reported "cosine similarity 0.850" when the actual score
was cosine 0.600 + name boost 0.250.  A user would think embedding similarity
is very high when it's actually moderate with a string-match assist.

**Fix**: Evidence now reports raw cosine and boost separately:
- With boost: `cosine=0.600 + name_boost=0.25 → 0.850 to Payment Card Number`
- Without boost: `cosine=0.750 to Email`

### 4. Fragile substring containment check (P0)

**Problem**: `cat_words in col_words` substring matching produced false matches:
- "name" in "username" would match a "Name" category
- "line" in "offline" would match a "Line" category

**Fix**: Replaced substring containment with word-set overlap.  Now requires ALL
category words to appear as whole words in the column name, and only fires for
multi-word categories (single-word categories like "Age" are too ambiguous for
overlap matching — they can only get exact or abbrev match).

```python
# Before (fragile):
elif len(cat_words) > 3 and (cat_words in col_words or col_words in cat_words):
    sims[i] += 0.10

# After (word-boundary):
cat_word_set = set(cat_words.split())
if len(cat_word_set) > 1 and cat_word_set.issubset(col_word_set):
    boosts[i] = 0.10
```

### 5. Silent failure on wrong CSV format (P1)

**Problem**: `annotation_category_set()` would silently return an empty
CategorySet if the CSV had wrong column names.

**Fix**: Added validation — raises `ValueError` listing missing required
columns (`Ontology`, `Annotation`, `Definition`) with the actual columns found.

## New Tests (7)

| Test | Verifies |
|------|----------|
| `test_cosine_only_path_when_name_does_not_match` | Cosine-only classification when column name doesn't match any category label (the "unseen data" path) |
| `test_name_boost_exact_match_evidence` | Evidence format shows both cosine and boost |
| `test_name_boost_abbrev_match` | Abbreviation matching works and is reported |
| `test_word_overlap_requires_all_words` | Word overlap doesn't false-match substrings ("username" vs "First Name") |
| `test_single_word_category_no_overlap_boost` | Single-word categories ("Age") don't get spurious overlap boost |
| `test_annotation_csv_missing_columns_raises` | Wrong CSV format raises clear error |
| (implicit in `test_cosine_only_path...`) | No "name_boost" in evidence when pure cosine |

## Files Modified

| File | Change |
|------|--------|
| `src/sigint/embedding_classifier.py` | Removed `is_data_column`, `_ANNOTATION_PREFIXES`; replaced substring containment with word-set overlap; separated cosine/boost in evidence |
| `src/sigint/category_set.py` | Consolidated `is_data_column` here; added CSV column validation |
| `scripts/build_sigint_embeddings.py` | Updated import path for `is_data_column` |
| `tests/sigint/test_embedding_classifier.py` | Updated import path; 7 new generality tests |

## Remaining Observations (not fixed — low priority)

- **`CategorySet.by_abbrev` collision risk**: Multiple categories with same
  abbreviation would silently keep only the last.  Not a problem currently but
  could surface with a different taxonomy.
- **`build_embedding_text` unused `siblings` parameter**: Accepted but never
  used.  Table context could help disambiguation in future.
- **`_load_csv_columns` hardcoded skip list**: `annotations.csv`, `metadata.csv`
  are hardcoded.  Fine for the build script but not configurable.

## Verification

```bash
uv run pytest tests/sigint/ -v          # 75 passed
uv run python scripts/build_sigint_embeddings.py \
  --data-dir ~/local/tmp/meta-tagging/ \
  --taxonomy annotations --threshold 0.25  # 171/171 = 100%
```
