# SVM Always-On: 5th DST Evidence Source Integration

## Summary

Made SVM (TF-IDF + LinearSVC) an always-on contributor to the Dempster-Shafer ensemble. Previously SVM existed only as a standalone pilot experiment (`scripts/svm_pilot.py`). Now it trains inline on synthetic data and participates in every `classify()` call.

## Architecture

```
Pipeline Stage 1.5 (new):
  synthetic training data → _build_svm_text() → SVMClassifier.fit() → clf.set_svm_model()

Every classify() call:
  1. cosine_to_mass()      ← embedding similarity
  2. catboost_to_mass()     ← gradient boosting (if model loaded)
  3. pattern_to_mass()      ← regex pattern signals
  4. name_match_to_mass()   ← column name matching
  5. svm_to_mass()          ← TF-IDF + LinearSVC (NEW: always-on)
  → Dempster's Rule combination → belief intervals [Bel, Pl]
```

## Changes

### `scripts/build_sigint_embeddings.py`

- Added `_build_svm_text(record)` helper — builds `"column_name | type | values"` text for TF-IDF
- Added Stage 1.5: SVM training before classification loop
  - Loads synthetic training data (reused by CatBoost in Stage 3.5)
  - Trains `SVMClassifier` on labeled training texts
  - Injects trained model via `clf.set_svm_model(svm)`
- CatBoost Stage 3.5 now reuses cached training data (avoids double I/O)

### `src/sigint/embedding_classifier.py`

- Added `_svm_model`, `_svm_loaded` instance vars
- Added `_get_svm_model()` lazy loader (from `svm_model_path` config or injected model)
- Added `set_svm_model()` injection method for pipeline inline training
- Updated `classify()` source #5 to auto-call SVM when model available
- Fixed `source_masses` type annotation (`dict[str, BeliefAssignment]` instead of `dict[str, object]`)

## SVM Evidence Source Properties

- **Independence**: TF-IDF char n-grams (3-6) + word n-grams (1-2) are architecturally independent from sentence-transformer embeddings
- **Discount**: 0.20 (configured in `svm_to_mass()`)
- **Calibration**: Platt scaling via `CalibratedClassifierCV` — outputs are true probabilities
- **Standalone accuracy**: 84.6% (from pilot experiment)
- **DST impact**: SVM dominates on opaque column names where embedding similarity is weak

## Test Status

397/397 tests pass (zero regressions).
