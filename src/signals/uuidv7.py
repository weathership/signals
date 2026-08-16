"""RFC 9562 UUID version 7 — warehouse ``tx_id`` / details ``t``.

Implementations SHOULD use v7 over v1 and v6 (RFC 9562 §4). Canonical
string form sorts by time. Kudu range *unit* is ``epoch_hour`` (week tablets).
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid
from typing import Any

RFC_9562 = "RFC 9562 §5.7"
VERSION_NIBBLE = 0x7
VARIANT_RFC = 0b10

_lock = threading.Lock()
_last_ms = 0
_seq = 0


def unix_ms() -> int:
    return time.time_ns() // 1_000_000


def mint(now_ms: int | None = None) -> str:
    """Monotonic UUIDv7 (RFC 9562 §6.2 method 2: counter in rand_a)."""
    global _last_ms, _seq
    ms = int(now_ms if now_ms is not None else unix_ms()) & 0xFFFFFFFFFFFF
    with _lock:
        if ms < _last_ms:
            ms = _last_ms
        if ms == _last_ms:
            _seq = (_seq + 1) & 0x0FFF
            if _seq == 0:
                ms = (ms + 1) & 0xFFFFFFFFFFFF
                _seq = 0
        else:
            _seq = secrets.randbits(12)
        _last_ms = ms
        seq = _seq
    rand_b = secrets.randbits(62)
    value = (ms << 80) | (VERSION_NIBBLE << 76) | (seq << 64) | (VARIANT_RFC << 62) | rand_b
    return str(uuid.UUID(int=value))


def parse(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError):
        return None


def is_uuidv7(value: str) -> bool:
    u = parse(value)
    return u is not None and u.version == 7


def unix_ms_of(value: str) -> int | None:
    u = parse(value)
    if u is None or u.version != 7:
        return None
    return u.int >> 80


def epoch_hour_of(value: str) -> int | None:
    ms = unix_ms_of(value)
    if ms is None:
        return None
    return ms // 3_600_000


def epoch_day_of(value: str) -> int | None:
    hour = epoch_hour_of(value)
    if hour is None:
        return None
    return hour // 24


class NonUuid7TxId(ValueError):
    """Peer-supplied tx_id is not RFC 9562 version 7. Do not land it."""

    def __init__(self, tx_id: str, *, product_id: str = "", source: str = ""):
        self.tx_id = tx_id
        self.product_id = product_id
        self.source = source
        super().__init__(
            f"tx_id {tx_id!r} is not UUID version 7 (RFC 9562); "
            "source must remint — warehouse will not store it"
        )

    def boundary_signal(self) -> dict[str, Any]:
        """Fields for zndx.engine.v1.BoundarySignal (TX_ID_NOT_UUIDV7)."""
        return {
            "kind": "TX_ID_NOT_UUIDV7",
            "kind_number": 5,
            "subject": self.product_id or "signals_dataproducts.tx",
            "offending": self.tx_id,
            "reason": (
                "tx_id MUST be RFC 9562 UUID version 7. "
                "Implementations SHOULD utilize v7 over v1 and v6. Remint and resubmit."
            ),
            "authority": RFC_9562,
            "source": self.source,
        }
