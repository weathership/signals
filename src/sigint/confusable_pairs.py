"""Registry of confusable category pairs for Dempster-Shafer belief functions.

These pairs were identified through error analysis — categories that are
frequently confused by the classifier due to semantic similarity. When
evidence is ambiguous between pair members, mass goes to the pair focal
element, producing honest uncertainty intervals instead of false confidence.
"""

from __future__ import annotations

ANNOTATION_CONFUSABLE_PAIRS: list[tuple[str, str]] = [
    ("1.1.2.2.1.3.5", "1.1.2.3.5"),      # ADID / GUID
    ("1.1.1.2.3.4.2", "1.1.1.2.3.4.1"),  # Under13 / Under18
    ("1.1.1.4.1.1", "1.1.1.4.1.2"),      # BillingAddressFull / ShippingAddressFull
    ("1.1.1.4.2.1.1", "1.1.1.4.2.1.2"),  # BillingStreet / ShippingStreet
    ("1.1.1.4.2.2.1", "1.1.1.4.2.2.2"),  # BillingCity / ShippingCity
    ("1.1.1.4.2.3.1", "1.1.1.4.2.3.2"),  # BillingPostal / ShippingPostal
    ("1.1.1.4.2.4.1", "1.1.1.4.2.4.2"),  # BillingState / ShippingState
    ("1.1.1.4.2.5.1", "1.1.1.4.2.5.2"),  # BillingCountry / ShippingCountry
    ("1.1.1.7.3.1", "1.1.1.7.3.2"),      # SecurityFlaw / CriticalSourceCode
    ("1.1.1.7.3.1", "1.1.1.7.3.3"),      # SecurityFlaw / 0-day
    ("1.1.1.7.3.2", "1.1.1.7.3.3"),      # CriticalSourceCode / 0-day
]

SIGDG_CONFUSABLE_PAIRS: list[tuple[str, str]] = [
    ("0013", "0012"),  # DeviceIdentifier / PlatformIdentifier
]


def get_confusable_pairs(taxonomy: str) -> list[tuple[str, str]]:
    """Return confusable pairs for the given taxonomy type."""
    if taxonomy == "annotations":
        return ANNOTATION_CONFUSABLE_PAIRS
    elif taxonomy == "sigdg":
        return SIGDG_CONFUSABLE_PAIRS
    elif taxonomy == "gittables":
        from config.sigint.gittables_taxonomy import GITTABLES_CONFUSABLE_PAIRS
        return GITTABLES_CONFUSABLE_PAIRS
    return []
