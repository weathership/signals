"""Persistent homology computation for signals-360.

Wraps Ripser (CPU) today; the in-development signals-360 fused CUDA
kernel will plug in alongside as a second backend, selected at runtime
via :mod:`signals.platform`. The :class:`PersistenceBackend` Protocol
below is the contract that future backend must satisfy — keeping the
public surface (``compute_persistence``) stable across implementations.

Protocol expectations
---------------------
The Ripser API is taken as canonical:

- **Input**: ``X: ndarray`` — either a point cloud
  ``(n_points, n_features)`` or, with ``distance_matrix=True``, a
  square pairwise distance matrix ``(n_points, n_points)``.
- **Configuration**: ``maxdim: int`` (highest homology dimension to
  compute), ``thresh: float`` (filtration radius cap).
- **Output**: a mapping with at minimum:

  - ``'dgms'``: list of ``(k_i, 2)`` ``ndarray`` of ``[birth, death]``
    pairs, one per dimension ``0..maxdim``. Essential classes use
    ``death == +inf``.
  - ``'num_edges'``: ``int`` count of edges in the filtration.

  Backends may attach additional keys (cocycles, permutations, etc.)
  but callers should only depend on the keys above.

Out of scope for this protocol: boundary-matrix-level inputs (the
form OpenPH and similar GPU reducers consume). Such backends bridge
into this protocol via an adapter that constructs the boundary matrix
from the point cloud / distance matrix and decodes the reduced output
into ``dgms``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np


@runtime_checkable
class PersistenceBackend(Protocol):
    """Contract any persistence backend must satisfy."""

    def compute(
        self,
        X: "np.ndarray",
        *,
        maxdim: int = 1,
        thresh: float = float("inf"),
        distance_matrix: bool = False,
    ) -> dict[str, Any]:
        ...


class RipserBackend:
    """Ripser CPU backend (scikit-tda/ripser-py). Always available."""

    def compute(
        self,
        X: "np.ndarray",
        *,
        maxdim: int = 1,
        thresh: float = float("inf"),
        distance_matrix: bool = False,
    ) -> dict[str, Any]:
        from ripser import ripser
        return ripser(
            X,
            maxdim=maxdim,
            thresh=thresh,
            distance_matrix=distance_matrix,
        )


_active_backend: PersistenceBackend | None = None


def get_backend() -> PersistenceBackend:
    """Return the active backend.

    Currently always Ripser. When the signals-360 CUDA kernel lands,
    dispatch will consult :func:`signals.platform.cuda_available` here.
    """
    global _active_backend
    if _active_backend is None:
        _active_backend = RipserBackend()
    return _active_backend


def compute_persistence(
    X: "np.ndarray",
    *,
    maxdim: int = 1,
    thresh: float = float("inf"),
    distance_matrix: bool = False,
) -> dict[str, Any]:
    """Compute Vietoris-Rips persistent homology via the active backend."""
    return get_backend().compute(
        X,
        maxdim=maxdim,
        thresh=thresh,
        distance_matrix=distance_matrix,
    )
