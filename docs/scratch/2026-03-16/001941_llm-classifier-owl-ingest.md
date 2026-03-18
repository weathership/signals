# LLM Classifier, OWL Ontology, and Ingest Script

## Summary

Replaced rule-based classifier with zero-shot LLM classifier (Claude via Anthropic API), expanded SIGDG ontology to 42 categories with OWL serialization, and added a standalone CSV ingest script.

## Changes

### Deleted (6 files)
- `src/sigint/rules/` — entire directory (3 files: `__init__.py`, `name_rules.py`, `value_rules.py`)
- `tests/sigint/test_rules.py`
- `tests/sigint/test_classifier.py`

### Created (5 files)
- `src/sigint/llm_classifier.py` — Claude-based classifier implementing `Classifier` Protocol
- `src/sigint/owl.py` — SIGDG → OWL/RDF-XML serialization via owlready2
- `scripts/ingest_csvs.py` — CSV → Impala → Atlas → tag workflow
- `tests/sigint/test_llm_classifier.py` — 10 mocked tests
- `tests/sigint/test_owl.py` — 8 tests including round-trip validation

### Modified (7 files)
- `src/sigint/ontology.py` — added `abbrev` field, expanded from 20 to 42 categories with deeper hierarchy (codes 0070-0091)
- `src/sigint/classifier.py` — removed `RuleBasedClassifier`, kept `Classifier` Protocol + `Classification` dataclass
- `src/sigint/config.py` — added `classifier_type`, `anthropic_api_key`, `anthropic_model`, `annotations_path`
- `src/sigint/tagger.py` — classifier factory (`_create_classifier()`), removed rule-based import
- `src/sigint/cli.py` — added `--api-key`, `--model`, `--annotations` flags
- `src/sigint/__init__.py` — removed `RuleBasedClassifier` export
- `src/sigint/atlas_client.py` — added `register_table()` method (bulk entity create)
- `tests/sigint/test_ontology.py` — updated for 42 categories, new tests for `abbrev`, new leaves, uniqueness
- `pyproject.toml` — added `anthropic` and `owlready2` as optional deps + dev deps

## Test Results

37/37 tests pass:
- 19 ontology tests (expanded from 10)
- 10 LLM classifier tests (all mocked, no API key needed)
- 8 OWL serialization tests (including owlready2 round-trip)

## Architecture Decisions

- **Zero-shot classification**: SIGDG category table (~42 rows) fits in system prompt; no fine-tuning needed
- **Runtime vocabulary**: `annotations_path` loads domain context into prompt but doesn't change target categories
- **MMR context**: sibling column names included in user prompt (from reveal's key insight)
- **Lazy client init**: Anthropic client created on first classify() call, not at construction
- **OWL anchors**: BFO:0000031 (generically dependent continuant) for categories, BFO:0000019 (quality) for sensitivity levels
