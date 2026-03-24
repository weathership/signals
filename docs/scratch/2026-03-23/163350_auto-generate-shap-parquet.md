# Auto-Generate + SHAP-Enabled Parquet Pipeline

## Summary

Promoted the synthetic data generator into the classification pipeline as a single-command workflow (`--auto-generate`). The pipeline now generates training data, trains CatBoost, classifies, computes per-item SHAP explanations, and writes a parquet suitable for embedding-atlas visualization in one command.

## Changes

### New CLI Flags

- `--auto-generate` — inlines `generate_meta_tagging_train.py` via `importlib.util`, generating synthetic training data to `build/datasets/sigint_train/` before the train/eval phase
- `--variants-per-category N` — controls synthetic data diversity (default: 50 from config)

### Config Keys Added

| HOCON Key | Field | Default |
|-----------|-------|---------|
| `ml.auto_generate` | `auto_generate` | `false` |
| `ml.variants_per_category` | `variants_per_category` | `50` |

### Files Modified

| File | Change |
|------|--------|
| `scripts/build_sigint_embeddings.py` | `--auto-generate`, `--variants-per-category`, importlib inline generation |
| `src/sigint/config.py` | `auto_generate`, `variants_per_category` fields + `_HOCON_MAP` entries |
| `config/base.conf` | `ml.auto_generate`, `ml.variants_per_category` HOCON keys |
| `.env.example` | `SIGINT_AUTO_GENERATE`, `SIGINT_VARIANTS_PER_CATEGORY` env vars |
| `CLAUDE.md` | Updated command examples, added `shap_analysis.py` and `svm_classifier.py` to key files |
| `docs/current/src/architecture/classification-training.md` | Single-command workflow, SHAP section, updated commands |

## Pipeline Results

```
uv run python scripts/build_sigint_embeddings.py \
    --data-dir ~/local/tmp/meta-tagging/ \
    --taxonomy annotations \
    --ground-truth config/sigint/meta_tagging_gt.json \
    --auto-generate --variants-per-category 50 \
    --threshold 0.25 --sage-permutations 0 \
    --output build/sigint_shap_eval.parquet
```

### Accuracy

| Stage | Accuracy |
|-------|----------|
| Cosine (baseline) | 53.7% (188/350) |
| CatBoost train/eval | **83.1% (291/350)** |
| Data columns | 86.9% (152/175) |
| Annotation columns | 79.4% (139/175) |

### Training

- 7,734 synthetic columns (175 categories x ~44 variants each)
- 212 category reference augmentations
- Feature dim: 991 (384 full_emb + 384 vo_emb + 11 discrete + 212 cosine_sim)
- CatBoost: 500 iterations, depth=8, lr=0.08
- 48 annotation columns corrected by paired column propagation

### Output Parquet

53 columns including:
- 6 SHAP columns: `shap_top{1,2,3}_{name,value}`
- 12 `feat_*` transparency features
- 12 `sage_*` feature importance scores
- DST belief intervals (`belief`, `plausibility`, `uncertainty_gap`, `conflict`)
- CatBoost predictions (`ml_tag_code`, `ml_tag_label`, `ml_confidence`, `ml_correct`)

### SHAP Feature Group Rankings

Top 3 feature groups across items (CatBoost TreeSHAP, 9.7s):
1. `value_only_embedding` — most important (bridges opaque names)
2. `cosine_similarities` — second (domain-invariant category knowledge)
3. `full_embedding` — third (strong for semantic names)

## Technical Notes

### importlib Module Registration

When dynamically loading `generate_meta_tagging_train.py` via `importlib.util.spec_from_file_location()`, the module must be registered in `sys.modules` **before** calling `exec_module()`. Otherwise, the `@dataclass` decorator fails with `AttributeError: 'NoneType' object has no attribute '__dict__'` because `sys.modules.get(cls.__module__)` returns `None`.

```python
gen_mod = importlib.util.module_from_spec(mod_spec)
sys.modules["generate_meta_tagging_train"] = gen_mod  # Must be before exec_module
mod_spec.loader.exec_module(gen_mod)
```

### CatBoost Training Time

500 iterations with 991 features, 212 classes, 7,896 training samples took ~70 minutes on CPU (44 cores). The high class count (212) makes each iteration expensive. Consider reducing `iterations` to 250 or using GPU for faster turnaround.

## Test Status

391/391 tests pass (zero regressions).
