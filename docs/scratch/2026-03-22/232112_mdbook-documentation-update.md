# mdbook Documentation Update — Post Tier-1 Validation

## Summary

Updated mdbook documentation to reflect the validated BDD framework (74/74 scenarios passing),
air-gap isolation, and meta-tagging pipeline completion.

## Files Updated

### `scenarios/testing.md` — Complete rewrite
- Updated from 18 to 74 scenarios across 16 features
- Added tier-0 classification section (40 scenarios, 8 features)
- Expanded tier-1 to show health (22 scenarios) + integration (12 scenarios)
- Added air-gap testing section (HF_HUB_OFFLINE, model cache)
- Added config-driven BDD section (HOCON single source of truth)
- Added cross-domain step discovery documentation
- Added planned data lifecycle section (5 scenarios, not yet passing)
- Added unit test reference (363 pytest tests)

### `scenarios/overview.md` — Restructured
- Active domains: classification (40), health (22), integration (12)
- Planned enhancement: data lifecycle (5 scenarios)
- Backlog domains: S01-S06 archived in features_archive/
- Updated current status table

### `reference/roadmap.md` — Updated milestones
- BDD coverage: 18 → 74 scenarios, 6 → 16 features
- AI/ML Metadata Tagging: checked off tagging service, Atlas write-back, air-gap, BDD validation
- Added backlog section documenting archived S01-S06 and gRPC engine features
- Added air-gap isolation to Infrastructure (complete) section

### `infrastructure/zarf.md` — ML model artifacts
- Added "ML Model Artifacts" section
- Documented model cache bootstrap (just cache-models)
- Documented runtime isolation (HF_HUB_OFFLINE, SENTENCE_TRANSFORMERS_HOME)
- Documented Zarf packaging options (container bake-in, S3 staging, Zarf files)

### `architecture/meta-tagging.md` — Validated pipeline
- Replaced "Near-Term Plan" with "Validated Pipeline" section
- Documented the working Tagger pipeline (sample → classify → tag)
- Added "Running the Pipeline" with just commands
- Added "Next Steps" with event-driven tagging, calibration, OWL, Ranger, feedback loop

### `SUMMARY.md` — Restructured scenarios
- Moved Test Infrastructure above backlog scenarios
- Grouped S01-S06 under "Backlog" heading

## Verification

- `mdbook build docs/current` — clean build, no warnings
