# DST Evidence Fusion Documentation

## Summary

Created academic-quality mdbook documentation for the DST/CatBoost evidence fusion initiative.

## New Pages

### `architecture/evidence-fusion.md`
- Complete theoretical foundation: DST basics, Dempster's rule, closed-world assumption
- Architecture diagram (D2): evidence sources → mass functions → Dempster combination → decision layer
- Restricted focal set explanation with complexity analysis (~220 elements vs 2^175)
- All 4 mass function converters documented with formulas and rationale
- Hierarchical classification output: API examples, evidence string format, parquet schema
- Relationship diagram (D2): classify() vs classify_dst() parallel paths
- Implementation file index and test coverage table
- Full references: Shafer 1976, Smets & Kennes 1994, Smets 1990, Denoeux 2008, Denoeux & Zouhal 2001

### `reference/research-roadmap.md`
- 10 work items (R-01 through R-10) with priority classification (P0/P1/P2)
- Each item: problem statement, impact assessment, approach options, acceptance criteria, estimated scope
- P0 blockers: source independence analysis, constant calibration experiment
- P1 items: conflict metric correction, CatBoost mass normalization, cautious hierarchical classification
- P2 items: pattern frequency, name ambiguity, confusable pairs, uniform discounting, virtual ensembles
- Dependency graph (D2) showing critical path: R-01 + R-03 + R-04 → R-02 → R-05
- Cautious classification diagram (D2) showing hierarchy-level decision making
- Evaluation protocol: accuracy, ECE, uncertainty separation, conflict utility, hierarchy utility
- Full references

## Updated Pages

### `architecture/classification-training.md`
- XGBoost → CatBoost throughout
- Removed self-training section (target leakage — eliminated)
- Added CatBoost Migration section: leakage explanation, ordered boosting, hyperparameter mapping
- Added evidence fusion integration note
- Updated commands section with `--dst` example

### `architecture/context-engineering.md`
- XGBoost → CatBoost in pipeline diagram, accuracy table, output schema
- Added evidence fusion cross-reference

### `architecture/meta-tagging.md`
- Added evidence fusion reference
- Updated near-term plan with calibration work item

### `SUMMARY.md`
- Added Evidence Fusion under Architecture
- Added Research Roadmap under Reference

## D2 Diagrams

5 D2 diagrams across the new pages:
1. Evidence fusion architecture (sources → mass → combine → decide)
2. Restricted focal set hierarchy (frame structure)
3. classify() vs classify_dst() comparison
4. Cautious classification tree (belief thresholds per level)
5. Research roadmap dependency graph (critical path)
