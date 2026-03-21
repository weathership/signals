# DST Belief Functions + CatBoost Implementation

## Summary

Replaced XGBoost with CatBoost and added Dempster-Shafer belief functions for hierarchical uncertainty management across the sigint classification pipeline.

## Changes by Phase

### Phase 1: CatBoost Swap + Self-Training Leak Fix
- `pyproject.toml`: xgboost → catboost in deps and optional extras
- `src/sigint/embedding_classifier.py`: `_xgb_model`/`_xgb_classes` → `_cb_model`/`_cb_classes`, `xgboost_model_path` → `model_path`, CatBoostClassifier replaces XGBClassifier
- `scripts/build_sigint_embeddings.py`: All XGBoost refs → CatBoost, hyperparameter mapping (objective→loss_function, n_estimators→iterations, etc.), `posterior_sampling=True`, **removed self-training pseudo-label block** (lines ~390-411)
- `scripts/train_catboost.py`: New file (renamed from train_xgboost.py)
- `tests/sigint/test_embedding_classifier.py`: TestXGBoostDispatch → TestCatBoostDispatch

### Phase 2: Hierarchical CategorySet
- `src/sigint/category_set.py`: Added `parent_code` field to `ReferenceCategory`, new `HierarchicalCategorySet(CategorySet)` subclass with `children`, `parent`, `leaf_codes`, `descendants()`, `ancestors()`, `all_by_code`
- Updated `sigdg_category_set(hierarchical=bool)` and `annotation_category_set(csv_path, hierarchical=bool)` factories
- `tests/sigint/test_hierarchical_category_set.py`: 16 tests

### Phase 3: DST Core
- `src/sigint/belief.py`: `FocalElement`, `BeliefAssignment` (belief, plausibility, pignistic), `dempster_combine()`, `combine_multiple()`, `FrameOfDiscernment` (restricted focal set ~220 elements)
- `src/sigint/mass_functions.py`: `cosine_to_mass()`, `catboost_to_mass()`, `pattern_to_mass()`, `name_match_to_mass()` — 4 independent evidence sources
- `tests/sigint/test_belief.py`: 26 tests
- `tests/sigint/test_mass_functions.py`: 15 tests

### Phase 4: HierarchicalClassification
- `src/sigint/classifier.py`: `HierarchicalClassification` frozen dataclass with `belief_at()`, `plausibility_at()`, `interval_at()`, `uncertainty_gap`, `needs_clarification`, `from_combined_evidence()` classmethod
- `src/sigint/embedding_classifier.py`: `classify_dst()` method combines cosine + catboost + patterns + name_match masses via Dempster's rule
- `tests/sigint/test_hierarchical_classification.py`: 15 tests

### Phase 5: Pipeline Integration
- `scripts/build_sigint_embeddings.py`: `--dst` CLI flag, builds HierarchicalCategorySet + FrameOfDiscernment once, calls `classify_dst()` per column
- 7 new parquet columns: `dst_belief`, `dst_plausibility`, `dst_uncertainty_gap`, `dst_conflict`, `dst_needs_clarification`, `dst_evidence_sources`, `dst_belief_path`
- Report JSON: `dst_enabled` flag, `dst_summary` with avg uncertainty gap, avg conflict, clarification count
- `src/sigint/run_report.py`: Optional DST fields on `ColumnResult`

## Test Results

280 tests pass (up from 208). No regressions.

## Key Design Decisions
- Restricted focal set (~220 elements) avoids 2^175 combinatorial explosion
- CatBoost `posterior_sampling=True` provides ordered boosting (eliminates self-training leakage)
- `classify()` unchanged — existing callers unaffected
- DST columns default to 0/empty when `--dst` is off — backward compatible parquet schema
