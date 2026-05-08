"""Hardware and OS capability detection for runtime backend selection.

Modules with both CPU and GPU code paths (CatBoost, SAGE, persistent
homology) query this module rather than probing torch/CUDA directly,
so accelerator-selection logic lives in one place.

Distinct from :func:`sigint.config.preflight_gpu`, which produces a
rich startup report (nvidia-smi probing, version-mismatch warnings,
device names). This module provides cheap, cached primitives for
hot-path branching.
"""

from __future__ import annotations

import functools
import importlib
import platform as _platform
from typing import Literal


GpuBackend = Literal["cuda", "mps", "cpu"]


def _try_import_torch():
    """Best-effort torch import; returns the module or None.

    torch is not a top-level dep of signals — it arrives transitively
    via the ``embedding`` extra (sentence-transformers). importlib is
    used so static type checkers don't flag a missing module.
    """
    try:
        return importlib.import_module("torch")
    except Exception:
        return None


@functools.cache
def cuda_available() -> bool:
    """True iff PyTorch reports a usable CUDA runtime."""
    torch = _try_import_torch()
    if torch is None:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


@functools.cache
def gpu_backend() -> GpuBackend:
    """Active accelerator: ``'cuda'``, ``'mps'``, or ``'cpu'``.

    ``'mps'`` indicates Apple Silicon's Metal backend is reachable;
    whether a given workload actually supports MPS is the caller's
    decision (many CUDA-only kernels won't).
    """
    if cuda_available():
        return "cuda"
    torch = _try_import_torch()
    if torch is not None:
        try:
            if torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
    return "cpu"


def is_darwin() -> bool:
    return _platform.system() == "Darwin"


def is_linux() -> bool:
    return _platform.system() == "Linux"
