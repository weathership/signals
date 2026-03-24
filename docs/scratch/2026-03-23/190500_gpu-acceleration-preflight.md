# GPU Acceleration: Preflight Validation + CatBoost GPU

## Summary

Added centralized GPU preflight detection to the sigint pipeline. All GPU-capable components (SentenceTransformer, CatBoost, SAGE) now use a single `preflight_gpu()` function that validates CUDA driver/PyTorch compatibility before any model loads.

## Root Cause: Driver Version Mismatch

| Component | CUDA Built For | Driver Required | Current Driver |
|-----------|---------------|-----------------|----------------|
| PyTorch 2.10.0 | CUDA 12.8 | >=570 | 550.90.07 (CUDA 12.4) |
| CatBoost 1.2.10 | CUDA 12.8 | >=570 | 550.90.07 (CUDA 12.4) |

The cu124 PyTorch wheel index only goes up to `torch 2.6.0+cu124` — there is no `torch 2.10.0+cu124`. The fix is to upgrade the NVIDIA driver, not downgrade PyTorch.

## Fix: Driver Upgrade

```bash
sudo apt install nvidia-driver-570-open && sudo reboot
```

Available: nvidia-driver-570 (570.211.01), 575, 580, 590.

## Changes

### GPU Preflight (`src/sigint/config.py`)

New `GpuInfo` dataclass and `preflight_gpu()` function:

1. Probes `nvidia-smi` for GPU count, driver version, CUDA version
2. Checks `torch.cuda.is_available()` for runtime compatibility
3. Detects version mismatches with actionable fix guidance
4. Returns `GpuInfo.resolved_device` → "cuda" or "cpu"

### CatBoost GPU Support (`scripts/build_sigint_embeddings.py`)

- All 3 `CatBoostClassifier` instantiations now call `_catboost_gpu_kwargs()`
- When CUDA available: adds `task_type="GPU", devices="0"`
- `posterior_sampling=True` dropped on GPU (unsupported by CatBoost GPU)
- Pipeline prints GPU status at startup: `GPU: 6x GPU available (...)`

### SentenceTransformer Device

- `_detect_device()` in `embedding_classifier.py` now delegates to `preflight_gpu()`
- Ensures consistent device detection across all pipeline stages

### Preflight in Tests (`tests/conftest.py`)

- Session-scoped `preflight_gpu_check()` fixture emits UserWarning for GPU issues
- Never blocks tests — CPU fallback is always safe

### Config

- `gpu.devices = "0"` HOCON key (env: `SIGINT_GPU_DEVICES`)
- `gpu_devices: str = "0"` field in PipelineConfig

## Expected Impact After Driver Upgrade

| Component | CPU Time | GPU Time (est.) | Speedup |
|-----------|----------|-----------------|---------|
| CatBoost training (500 iter, 212 classes) | 70 min | ~5 min | 14x |
| SentenceTransformer encoding (7,734 cols) | ~30 sec | ~5 sec | 6x |
| SHAP TreeSHAP (355 items) | 9.7 sec | ~2 sec | 5x |
| SAGE permutations (512) | ~60 sec | ~10 sec | 6x |

## Files Modified

| File | Change |
|------|--------|
| `src/sigint/config.py` | `GpuInfo`, `preflight_gpu()`, `gpu_devices` field |
| `src/sigint/embedding_classifier.py` | `_detect_device()` delegates to `preflight_gpu()` |
| `scripts/build_sigint_embeddings.py` | `_catboost_gpu_kwargs()`, GPU preflight report |
| `tests/conftest.py` | `preflight_gpu_check()` fixture |
| `tests/sigint/test_gpu_preflight.py` | 6 tests for GpuInfo and preflight |
| `config/base.conf` | `gpu.devices` HOCON key |
| `.env.example` | `SIGINT_GPU_DEVICES`, driver upgrade note |

## Test Status

397/397 tests pass (zero regressions, +6 new GPU preflight tests).
