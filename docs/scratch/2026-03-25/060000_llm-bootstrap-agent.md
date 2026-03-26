# LLM Bootstrap Agent Implementation

## Summary

Implemented a complete LLM-driven bootstrap agent for classifying novel tables without ground truth. The agent uses DST conflict K as a convergence signal, iteratively refining LLM classifications with ML pipeline feedback until agreement is reached.

## Architecture

- **Dual LLM backend**: `AnthropicBackend` (Claude Opus 4.6) + `OpenAICompatibleBackend` (vLLM/Devstral for air-gap)
- **Convergence loop**: ML-only baseline → selective LLM → label propagation → ML retrain → disagreement revisit → convergence check
- **K-based revisiting**: High-K columns are re-sent to LLM with enriched ML context (prediction, belief interval, confusable pair)
- **Tiered sampling**: High-K priority, low-confidence, random calibration — minimizes LLM calls
- **Label propagation**: Confident LLM labels propagate to similar unlabeled columns via embedding cosine similarity > 0.85
- **LLM as 6th DST source**: `llm_to_mass()` with 0.10 discount (lower than cosine 0.30, SVM 0.20)
- **Output**: Ground truth JSON compatible with `--ground-truth` / `--self-train`

## Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `src/sigint/llm_backend.py` | 330 | Dual LLM backend abstraction |
| `src/sigint/bootstrap_agent.py` | 370 | Convergence loop agent |
| `scripts/bootstrap_classify.py` | 240 | CLI entry point |
| `tests/sigint/test_llm_backend.py` | 230 | 24 tests for LLM backend |
| `tests/sigint/test_bootstrap_agent.py` | 310 | 17 tests for agent loop |
| `tests/sigint/test_bootstrap_config.py` | 100 | 35 tests for config |
| `tests/sigint/test_llm_to_mass.py` | 90 | 10 tests for mass function |
| `docs/current/src/architecture/bootstrap-agent.md` | 140 | Architecture page |

## Files Modified

| File | Change |
|------|--------|
| `src/sigint/mass_functions.py` | Added `llm_to_mass()` converter |
| `src/sigint/config.py` | +15 HOCON mappings, +16 PipelineConfig fields |
| `config/base.conf` | `bootstrap {}` block with 15 keys |
| `.env.example` | Bootstrap env vars section |
| `docs/current/src/SUMMARY.md` | Added bootstrap-agent page |
| `docs/current/src/reference/research-roadmap.md` | Added bootstrap agent to completed items |
| `CLAUDE.md` | Added llm_backend.py, bootstrap_agent.py, bootstrap_classify.py |

## Config Keys (15 new)

| HOCON Key | Default | Description |
|-----------|---------|-------------|
| `bootstrap.max_iterations` | 5 | Max convergence iterations |
| `bootstrap.k_threshold` | 0.2 | DST K threshold for LLM revisit |
| `bootstrap.coverage_target` | 0.95 | Target label coverage |
| `bootstrap.confidence_floor` | 0.5 | Min ML confidence for acceptance |
| `bootstrap.propagation_similarity` | 0.85 | Cosine sim for label propagation |
| `bootstrap.max_total_llm_calls` | 200 | Budget cap |
| `bootstrap.columns_per_call` | 10 | Batch size |
| `bootstrap.llm_backend` | anthropic | anthropic / openai_compatible |
| `bootstrap.llm_model` | claude-opus-4-6 | LLM model name |
| `bootstrap.llm_discount` | 0.10 | DST discount for LLM mass function |

## Test Results

513/513 tests pass (98 new, 415 existing). Zero regressions.

## Usage

```bash
# Bootstrap with Claude (default)
uv run python scripts/bootstrap_classify.py \
    --data-dir ~/data/novel_tables/ \
    --taxonomy sigdg --threshold 0.25 \
    --output build/bootstrap_gt.json

# Bootstrap with local Devstral via vLLM (air-gap)
uv run python scripts/bootstrap_classify.py \
    --data-dir ~/data/novel_tables/ \
    --llm-backend openai_compatible \
    --llm-base-url http://localhost:8000/v1 \
    --llm-model devstral-small-2 \
    --output build/bootstrap_gt.json

# Self-training with bootstrap output
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/data/novel_tables/ \
    --ground-truth build/bootstrap_gt.json \
    --self-train --auto-generate \
    --output build/sigint_final.parquet
```
