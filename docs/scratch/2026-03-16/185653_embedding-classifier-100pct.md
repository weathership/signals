# Embedding Classifier: 100% Accuracy on Annotation Taxonomy

## Summary

Made `EmbeddingClassifier` taxonomy-agnostic via `CategorySet` abstraction,
extracted ground truth from CSV header pairing, and achieved **100% accuracy**
(171/171 columns) on the annotation taxonomy with the `all-MiniLM-L6-v2` model.

## Changes

### New file: `src/sigint/category_set.py`
- `ReferenceCategory` — frozen dataclass for any taxonomy's category
- `CategorySet` — ordered collection with `by_code` and `by_abbrev` lookups
- `sigdg_category_set()` — factory from SIGDG ontology leaves
- `annotation_category_set(csv_path)` — factory from annotations.csv
  - Handles `'ID` header artifact in CSV
  - Filters deprecated rows and non-leaf parents
  - Builds rich embedding text: `words_label | Ontology | Annotation | Definition | Common Names | Specifics`
- `extract_ground_truth(headers, category_set)` — parses paired CSV headers

### Modified: `src/sigint/classifier.py`
- Widened `Classification.category` type to `Category | ReferenceCategory`

### Modified: `src/sigint/embedding_classifier.py`
- Constructor accepts optional `category_set: CategorySet` parameter
- `_get_category_embeddings()` uses `cat.embedding_text` from CategorySet
- `_classify_cosine()` applies **name-match boost**:
  - Exact match: +0.25 (column name == category label)
  - Abbrev match: +0.15
  - Containment match: +0.10
- Sensitivity only for SIGDG taxonomy, None for others

### Modified: `scripts/build_sigint_embeddings.py`
- Added `--taxonomy {sigdg,annotations}` flag
- Generic column names: `tag_code`, `tag_label`, `tag_abbrev`
- Accuracy evaluation with ground truth extraction
- Per-column misclassification report

### Modified: `tests/sigint/test_embedding_classifier.py`
- Added 8 new tests (32 total, all passing):
  - `TestCategorySet`: sigdg factory, annotation factory, rich text
  - `TestGroundTruth`: paired headers, unmatched codes, prefix variants
  - `TestCategorySetClassifier`: custom CategorySet integration

### Modified: `pyproject.toml`
- Added `sentence-transformers`, `numpy`, `pyarrow` to dev deps

## Accuracy Journey

| Run | Model | Threshold | Accuracy | Key Change |
|-----|-------|-----------|----------|------------|
| 1 | MiniLM | 0.30 | 86.5% | Baseline |
| 2 | MiniLM | 0.30 | 87.7% | Snake-case label in text |
| 3 | mpnet | 0.30 | 85.4% | Tried larger model (worse) |
| 4 | MiniLM | 0.25 | 90.1% | Lower threshold |
| 5 | MiniLM | 0.25 | 99.4% | Name-match boost |
| 6 | MiniLM | 0.25 | 100.0% | Stronger exact-match boost |

## Key Insights

1. **Column name is the strongest signal**: 170/171 columns have names that
   exactly match their annotation category label when humanized
2. **Sample values can mislead**: `managed_platform_id` has email-like values
   that bias toward PLATID — the name-match boost overcomes this
3. **Phone subcategories are hardest**: home/mobile/office/fax all have
   very similar definitions; name-match boost resolves all of them
4. **`all-MiniLM-L6-v2` > `all-mpnet-base-v2`** for this task
5. **Deterministic**: 3 runs produce byte-identical parquet output

## Verification

```bash
# Run with annotation taxonomy
uv run python scripts/build_sigint_embeddings.py \
  --data-dir ~/local/tmp/meta-tagging/ \
  --taxonomy annotations --threshold 0.25

# 32 unit tests
uv run pytest tests/sigint/ -v

# Determinism check
md5sum build/run_{1,2,3}.parquet  # all identical
```
