"""Schema discovery — detect Data Elements from table structure.

Two discovery strategies run before LLM classification:

1. **Naming convention patterns**: Match column names against well-known
   data element signatures (PaymentCard, PostalAddress, PersonName, etc.).

2. **Foreign-key hints**: Detect ``<entity>_id`` column patterns that
   suggest cross-table relationships.

A third strategy (category co-occurrence) runs *after* classification
when ground-truth labels are available — see ``refine_elements()``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sigint.data_element import DataElement, DataElementCatalog, DataElementMember


# ── Well-known data element patterns ────────────────────────────


@dataclass(frozen=True)
class _DEPattern:
    name: str
    domain: str
    definition: str
    indicators: tuple[str, ...]
    min_match: int = 2  # minimum indicator hits to declare a match


DE_PATTERNS: tuple[_DEPattern, ...] = (
    _DEPattern(
        "PaymentCard", "finance",
        "Payment card attributes (PAN, CVV, expiry, cardholder)",
        ("card_number", "pan", "cvv", "expiry", "cardholder",
         "card_type", "payment_card", "card_brand"),
    ),
    _DEPattern(
        "PostalAddress", "contact",
        "Postal mailing address components",
        ("street", "city", "state", "zip", "postal_code",
         "country", "address_line", "zip_code", "province"),
    ),
    _DEPattern(
        "PersonName", "identity",
        "Personal name components",
        ("first_name", "last_name", "full_name", "middle_name",
         "given_name", "surname", "family_name", "name_prefix"),
    ),
    _DEPattern(
        "ContactInfo", "contact",
        "Communication contact attributes",
        ("email", "phone", "mobile", "fax", "telephone",
         "phone_number", "email_address", "contact_number"),
    ),
    _DEPattern(
        "BankAccount", "finance",
        "Bank account attributes (account number, routing, IBAN)",
        ("account_number", "routing_number", "iban", "swift",
         "bank_code", "sort_code", "bic", "account_type"),
    ),
    _DEPattern(
        "GovernmentID", "identity",
        "Government-issued identification attributes",
        ("ssn", "social_security", "tax_id", "passport",
         "driver_license", "national_id", "tin", "ein"),
    ),
    _DEPattern(
        "BiospecimenCollection", "healthcare",
        "Biological sample collection attributes",
        ("sample_location", "specimen_type", "collection_date",
         "anatomical_site", "instrument", "biopsy", "tissue",
         "sample_id", "specimen_id", "pathology"),
    ),
    _DEPattern(
        "PatientDemographics", "healthcare",
        "Patient demographic and clinical attributes",
        ("date_of_birth", "gender", "sex", "ethnicity", "race",
         "marital_status", "blood_type", "patient_id", "mrn"),
    ),
    _DEPattern(
        "GeoLocation", "spatial",
        "Geographic coordinate and location attributes",
        ("latitude", "longitude", "lat", "lng", "lon",
         "geo_location", "coordinates", "altitude", "geohash"),
    ),
    _DEPattern(
        "DeviceIdentity", "technology",
        "Device and platform identifier attributes",
        ("device_id", "mac_address", "ip_address", "imei",
         "serial_number", "hostname", "uuid", "hardware_id"),
    ),
    _DEPattern(
        "Credential", "security",
        "Authentication credential attributes",
        ("password", "pin", "secret", "token", "api_key",
         "passphrase", "auth_token", "access_key"),
    ),
)


# ── Normalisation helpers ────────────────────────────────────────


def _normalise(name: str) -> str:
    """Normalise a column name to lowercase underscore form."""
    # camelCase → snake_case
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    return s.lower().replace("-", "_").strip()


# ── Discovery functions ──────────────────────────────────────────


def discover_elements(
    tables: dict[str, list[dict]],
) -> DataElementCatalog:
    """Discover data elements from table schemas via naming patterns.

    Args:
        tables: Output of ``group_by_table()`` — ``{table_name: [records]}``.
            Each record must have at least ``column_name``.

    Returns:
        Catalog of discovered data elements.
    """
    elements: list[DataElement] = []

    for table_name, records in tables.items():
        col_names = [r["column_name"] for r in records]
        col_norm = {name: _normalise(name) for name in col_names}

        for pattern in DE_PATTERNS:
            matched_cols: list[str] = []
            for col_name, norm in col_norm.items():
                for indicator in pattern.indicators:
                    # Substring match: "payment_card_number" contains "card_number"
                    if indicator in norm or norm in indicator:
                        matched_cols.append(col_name)
                        break
                    # Word overlap: {"card", "number"} ⊆ {"payment", "card", "number"}
                    ind_words = set(indicator.split("_"))
                    col_words = set(norm.split("_"))
                    if len(ind_words) > 1 and ind_words.issubset(col_words):
                        matched_cols.append(col_name)
                        break

            if len(matched_cols) >= pattern.min_match:
                members = [
                    DataElementMember(
                        column_name=c,
                        source_table=table_name,
                        role=_infer_role(c),
                    )
                    for c in matched_cols
                ]
                elements.append(DataElement(
                    name=pattern.name,
                    domain=pattern.domain,
                    definition=pattern.definition,
                    members=members,
                    source="discovered",
                ))

    # Deduplicate: if same DE name found in multiple tables, merge members
    merged = _merge_same_name(elements)
    return DataElementCatalog(elements=merged)


def discover_fk_hints(
    tables: dict[str, list[str]],
) -> list[tuple[str, str, str]]:
    """Detect cross-table foreign-key hints via ``<entity>_id`` naming.

    Args:
        tables: ``{table_name: [column_names]}``.

    Returns:
        List of ``(source_table, column_name, target_table)`` tuples.
    """
    table_names_lower = {t.lower(): t for t in tables}
    hints: list[tuple[str, str, str]] = []

    for table_name, col_names in tables.items():
        for col in col_names:
            norm = _normalise(col)
            if norm.endswith("_id"):
                entity = norm[:-3]  # "instrument_id" → "instrument"
                # Check for plural and singular table matches
                for candidate in (entity, entity + "s", entity + "es"):
                    if candidate in table_names_lower and candidate != table_name.lower():
                        hints.append((table_name, col, table_names_lower[candidate]))
                        break

    return hints


def refine_elements(
    catalog: DataElementCatalog,
    ground_truth: dict[str, str],
    tables: dict[str, list[dict]],
) -> DataElementCatalog:
    """Refine data elements using post-classification category co-occurrence.

    After bootstrap classification, columns have category codes. Tables
    whose columns fall into known affinity groups suggest data elements
    that naming patterns alone might miss.

    Args:
        catalog: Existing catalog from ``discover_elements()``.
        ground_truth: ``{column_name: category_code}`` from bootstrap.
        tables: ``{table_name: [records]}``.

    Returns:
        Augmented catalog with co-occurrence-discovered elements.
    """
    new_elements = list(catalog.elements)
    existing_names = {e.name for e in catalog.elements}

    for table_name, records in tables.items():
        col_codes = {}
        for r in records:
            name = r["column_name"]
            if name in ground_truth:
                col_codes[name] = ground_truth[name]

        if not col_codes:
            continue

        code_set = set(col_codes.values())
        for de_name, affinity in CATEGORY_AFFINITIES.items():
            overlap = code_set & affinity
            if len(overlap) >= 2 and de_name not in existing_names:
                members = [
                    DataElementMember(
                        column_name=name,
                        source_table=table_name,
                        role=_infer_role(name),
                    )
                    for name, code in col_codes.items()
                    if code in affinity
                ]
                if members:
                    info = _AFFINITY_INFO.get(de_name, {})
                    new_elements.append(DataElement(
                        name=de_name,
                        domain=info.get("domain", ""),
                        definition=info.get("definition", ""),
                        members=members,
                        source="co-occurrence",
                    ))
                    existing_names.add(de_name)

    return DataElementCatalog(elements=new_elements)


# ── Category affinity groups (SIGDG codes) ───────────────────────


CATEGORY_AFFINITIES: dict[str, set[str]] = {
    "PaymentCard": {"0070", "0073", "0075"},       # PCD + Name + Address
    "CustomerIdentity": {"0085", "0084", "0073"},  # SSN + DL + Name
    "FinancialAccount": {"0071", "0070", "0073"},   # BAN + PCD + Name
    "EmployeeRecord": {"0085", "0073", "0026"},     # SSN + Name + Credential
}

_AFFINITY_INFO: dict[str, dict] = {
    "PaymentCard": {
        "domain": "finance",
        "definition": "Payment card with cardholder identity and billing address",
    },
    "CustomerIdentity": {
        "domain": "identity",
        "definition": "Customer identification with government IDs",
    },
    "FinancialAccount": {
        "domain": "finance",
        "definition": "Financial account with associated identity",
    },
    "EmployeeRecord": {
        "domain": "human_resources",
        "definition": "Employee record with credentials and identity",
    },
}


# ── Helpers ──────────────────────────────────────────────────────


def _infer_role(column_name: str) -> str:
    """Infer a member role from the column name."""
    norm = _normalise(column_name)
    if norm.endswith("_id") or norm == "id":
        return "identifier"
    if any(kw in norm for kw in ("date", "time", "timestamp", "created", "updated")):
        return "temporal"
    if norm.endswith("_id") or "_ref" in norm or "_fk" in norm:
        return "reference"
    return "attribute"


def _merge_same_name(elements: list[DataElement]) -> list[DataElement]:
    """Merge elements with the same name (from different tables)."""
    by_name: dict[str, DataElement] = {}
    for e in elements:
        if e.name in by_name:
            existing = by_name[e.name]
            existing.members.extend(e.members)
        else:
            by_name[e.name] = DataElement(
                name=e.name,
                domain=e.domain,
                definition=e.definition,
                members=list(e.members),
                source=e.source,
            )
    return list(by_name.values())
