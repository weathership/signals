# SVM as Fifth DST Evidence Source

## Summary

Implemented a TF-IDF + LinearSVC classifier as an optional fifth evidence source
for the Dempster-Shafer evidence fusion pipeline. This directly addresses the
source independence concern (R-01) by providing a genuinely independent evidence
channel that operates on sparse lexical features rather than the shared
sentence-transformer embedding.

## Design Decisions

1. **scikit-learn, not libshorttext**: The original libshorttext library (Yu et al.,
   2013) is unmaintained since ~2014. We use scikit-learn's `TfidfVectorizer` +
   `LinearSVC` + `CalibratedClassifierCV` for the same principles with modern,
   actively maintained code.

2. **TF-IDF feature space**: Character n-grams (3-6) + word bigrams capture
   subword patterns (abbreviations, camelCase fragments, digit sequences) that
   the dense embedding may over-generalize. This creates genuine feature-space
   independence from cosine and CatBoost.

3. **Platt scaling for calibration**: `CalibratedClassifierCV` with sigmoid
   (Platt) method converts LinearSVC decision values into well-calibrated
   probability estimates suitable for direct conversion to mass functions.

4. **Optional integration**: The SVM source is disabled by default (`svm.enabled
   = false`). A pilot experiment script validates improvement before promotion
   to production. The `classify()` method accepts `svm_proba` as an optional
   parameter — when absent, the combination proceeds with only the 4 core sources.

5. **Lower discount (0.20)**: Calibrated SVM probabilities are typically
   well-concentrated on the correct class for short-text classification, warranting
   a lower discount than cosine's softmax-derived estimates (0.30).

## Files Created

| File | Purpose |
|------|---------|
| `src/sigint/svm_classifier.py` | SVMClassifier: TF-IDF + LinearSVC + CalibratedClassifierCV |
| `tests/sigint/test_svm_classifier.py` | 9 tests: train/predict, save/load, config, DST integration |
| `scripts/svm_pilot.py` | Pilot experiment: standalone accuracy, source correlation, 4-vs-5-source DST |

## Files Modified

| File | Change |
|------|--------|
| `src/sigint/mass_functions.py` | Added `svm_to_mass()` converter |
| `src/sigint/embedding_classifier.py` | Added `svm_proba` param to `classify()`, import `svm_to_mass` |
| `src/sigint/config.py` | Added `svm_enabled`, `svm_model_path`, `svm_discount` fields |
| `config/base.conf` | Added `svm {}` config block |
| `.env.example` | Added SVM env vars |
| `tests/sigint/test_mass_functions.py` | Added 5 tests for `svm_to_mass()` |
| `docs/current/src/architecture/evidence-fusion.md` | SVM source in architecture diagram, mass converter docs, updated counts |
| `docs/current/src/introduction.md` | Updated source count (4→5), added SVM to evidence table |
| `docs/current/src/reference/research-roadmap.md` | Added SVM as R-01 approach option 3 (implemented, pilot phase) |

## Test Results

- 377/377 tests pass (363 existing + 14 new)
- New test coverage: svm_to_mass converter (5 tests), SVMClassifier (7 tests), 5-source DST integration (2 tests)
- mdbook builds clean, no warnings

## Pilot Protocol

The `scripts/svm_pilot.py` script implements the pilot protocol:

1. Train SVM on existing synthetic training data (no new labeling)
2. Evaluate standalone hierarchical accuracy
3. Compare 4-source vs 5-source DST fusion (with `--compare-dst`):
   - Accuracy delta
   - Average conflict K delta
   - Average uncertainty gap (Pl - Bel) delta
   - Columns where 5-source fixed 4-source errors

### Success Criteria

- Marginal DST improvement > 5-8% on uncertain cases
- No increase in average Dempster conflict K
- SVM predictions have measurably lower correlation with cosine/CatBoost
