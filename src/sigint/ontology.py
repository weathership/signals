"""SIGDG ontology — categories, sensitivity levels, and Atlas type mapping.

The Signals Data Governance ontology (prefix SIGDG) is grounded in BFO 2020.
See docs/current/src/architecture/meta-tagging.md for the full hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    """An information-entity category in the SIGDG hierarchy."""

    curie: str  # e.g. "SIGDG:0011"
    code: str  # e.g. "0011"
    label: str  # e.g. "GovernmentIdentifier"
    parent_code: str | None  # e.g. "0010", None for root
    description: str = ""
    abbrev: str = ""  # terse code, e.g. "PCD", "SSN", "DL"

    @property
    def atlas_type_name(self) -> str:
        """Atlas classification type name (colons not allowed)."""
        return f"SIGDG_{self.code}_{self.label}"


@dataclass(frozen=True)
class SensitivityLevel:
    """A sensitivity quality in the SIGDG ontology."""

    curie: str
    code: str
    label: str
    description: str = ""


# ── Sensitivity levels ────────────────────────────────────────────────────

SENSITIVITY_LEVELS: tuple[SensitivityLevel, ...] = (
    SensitivityLevel("SIGDG:1010", "1010", "Public",
                     "Intended for unrestricted disclosure"),
    SensitivityLevel("SIGDG:1020", "1020", "Internal",
                     "Not public but no harm if disclosed internally"),
    SensitivityLevel("SIGDG:1030", "1030", "Confidential",
                     "Disclosure causes measurable harm"),
    SensitivityLevel("SIGDG:1040", "1040", "Restricted",
                     "Disclosure causes severe harm; regulated by law"),
)

# ── Information entity hierarchy ──────────────────────────────────────────

CATEGORIES: tuple[Category, ...] = (
    # Root
    Category("SIGDG:0001", "0001", "InformationEntity", None,
             "data that can be stored and transferred"),
    # ── Identity ──────────────────────────────────────────────────────
    Category("SIGDG:0010", "0010", "IdentityInformation", "0001",
             "data that identifies a natural or legal person", "ID"),
    Category("SIGDG:0011", "0011", "GovernmentIdentifier", "0010",
             "state-issued ID: passport, SSN, driver's license", "GOVID"),
    Category("SIGDG:0083", "0083", "Passport", "0011",
             "travel document number", "PASS"),
    Category("SIGDG:0084", "0084", "DriversLicense", "0011",
             "driving permit number", "DL"),
    Category("SIGDG:0085", "0085", "TaxIdentifier", "0011",
             "SSN, TIN, VATIN, CPF", "TIN"),
    Category("SIGDG:0012", "0012", "PlatformIdentifier", "0010",
             "account-scoped ID: username, email, employee ID", "PLAT"),
    Category("SIGDG:0013", "0013", "DeviceIdentifier", "0010",
             "hardware-bound ID: IMEI, MAC address, UDID", "DEV"),
    # ── Personal ──────────────────────────────────────────────────────
    Category("SIGDG:0020", "0020", "PersonalInformation", "0001",
             "data about a natural person", "PII"),
    Category("SIGDG:0021", "0021", "FinancialInformation", "0020",
             "monetary data: balances, scores, compensation", "FIN"),
    Category("SIGDG:0022", "0022", "PaymentInformation", "0021",
             "payment instruments: card numbers, bank accounts", "PAY"),
    Category("SIGDG:0070", "0070", "PaymentCardData", "0022",
             "card number, CVV, expiry, mag stripe", "PCD"),
    Category("SIGDG:0071", "0071", "BankAccountData", "0022",
             "bank account, routing number, IBAN", "BANK"),
    Category("SIGDG:0072", "0072", "CreditData", "0021",
             "credit score, fraud score, lending", "CRED"),
    Category("SIGDG:0023", "0023", "DemographicInformation", "0020",
             "attributes: age, gender, ethnicity, education", "DEMO"),
    Category("SIGDG:0077", "0077", "AgeInformation", "0023",
             "DOB, age, birth year", "AGE"),
    Category("SIGDG:0078", "0078", "IncomeData", "0023",
             "salary, wage, compensation", "INCOME"),
    Category("SIGDG:0024", "0024", "HealthInformation", "0020",
             "medical conditions, biometrics, genetic data", "PHI"),
    Category("SIGDG:0079", "0079", "Diagnosis", "0024",
             "medical diagnosis, ICD codes", "DX"),
    Category("SIGDG:0080", "0080", "Medication", "0024",
             "prescriptions, drug names", "RX"),
    Category("SIGDG:0081", "0081", "BiometricData", "0024",
             "fingerprint, face scan, voice", "BIO"),
    Category("SIGDG:0082", "0082", "GeneticData", "0024",
             "DNA, genome, genetic markers", "GEN"),
    Category("SIGDG:0025", "0025", "ContactInformation", "0020",
             "addresses, phone numbers, email", "CONTACT"),
    Category("SIGDG:0073", "0073", "FullName", "0025",
             "legal name and components", "NAME"),
    Category("SIGDG:0074", "0074", "PhoneNumber", "0025",
             "phone, mobile, fax", "PHONE"),
    Category("SIGDG:0075", "0075", "PostalAddress", "0025",
             "street, city, zip, postal", "ADDR"),
    Category("SIGDG:0076", "0076", "EmailAddress", "0025",
             "electronic mail address", "EMAIL"),
    Category("SIGDG:0026", "0026", "CredentialInformation", "0020",
             "passwords, PINs, keys, security questions", "CREDS"),
    # ── Business ──────────────────────────────────────────────────────
    Category("SIGDG:0030", "0030", "BusinessInformation", "0001",
             "data about an enterprise", "BIZ"),
    Category("SIGDG:0031", "0031", "ProprietaryInformation", "0030",
             "trade secrets, technical documentation", "PROP"),
    Category("SIGDG:0032", "0032", "RegulatoryInformation", "0030",
             "SEC filings, compliance records", "REG"),
    # ── System ────────────────────────────────────────────────────────
    Category("SIGDG:0040", "0040", "SystemInformation", "0001",
             "infrastructure and configuration data", "SYS"),
    Category("SIGDG:0041", "0041", "ConfigurationData", "0040",
             "IPs, cluster membership, file paths", "CFG"),
    Category("SIGDG:0042", "0042", "AccessControlData", "0040",
             "permissions, LDAP groups, session state", "ACL"),
    Category("SIGDG:0086", "0086", "SecurityDecision", "0040",
             "audit events, vuln reports", "SECDEC"),
    Category("SIGDG:0087", "0087", "RuntimeData", "0040",
             "crash reports, metrics", "RTDATA"),
    # ── Transaction ───────────────────────────────────────────────────
    Category("SIGDG:0050", "0050", "TransactionInformation", "0001",
             "event records: orders, sessions, timestamps", "TXN"),
    # ── Transformation ────────────────────────────────────────────────
    Category("SIGDG:0060", "0060", "TransformationMetadata", "0001",
             "provenance: encryption, masking, hashing records", "XFORM"),
    Category("SIGDG:0088", "0088", "Encryption", "0060",
             "encrypted data, key metadata", "ENC"),
    Category("SIGDG:0089", "0089", "Hashing", "0060",
             "hash digests, checksums", "HASH"),
    Category("SIGDG:0090", "0090", "Masking", "0060",
             "masked/redacted data", "MASK"),
    Category("SIGDG:0091", "0091", "Anonymization", "0060",
             "anonymized/pseudonymized data", "ANON"),
)

# Lookup helpers
CATEGORY_BY_CODE: dict[str, Category] = {c.code: c for c in CATEGORIES}
CATEGORY_BY_LABEL: dict[str, Category] = {c.label: c for c in CATEGORIES}

# Default sensitivity mapping: category code → sensitivity code
DEFAULT_SENSITIVITY: dict[str, str] = {
    # Identity
    "0012": "1030",  # PlatformIdentifier → Confidential
    "0013": "1030",  # DeviceIdentifier → Confidential
    "0083": "1040",  # Passport → Restricted
    "0084": "1040",  # DriversLicense → Restricted
    "0085": "1040",  # TaxIdentifier → Restricted
    # Financial / Payment
    "0070": "1040",  # PaymentCardData → Restricted
    "0071": "1040",  # BankAccountData → Restricted
    "0072": "1030",  # CreditData → Confidential
    # Demographic
    "0077": "1030",  # AgeInformation → Confidential
    "0078": "1030",  # IncomeData → Confidential
    # Health
    "0079": "1040",  # Diagnosis → Restricted
    "0080": "1040",  # Medication → Restricted
    "0081": "1040",  # BiometricData → Restricted
    "0082": "1040",  # GeneticData → Restricted
    # Contact
    "0073": "1030",  # FullName → Confidential
    "0074": "1030",  # PhoneNumber → Confidential
    "0075": "1030",  # PostalAddress → Confidential
    "0076": "1030",  # EmailAddress → Confidential
    "0026": "1040",  # CredentialInformation → Restricted
    # Business
    "0031": "1030",  # ProprietaryInformation → Confidential
    "0032": "1030",  # RegulatoryInformation → Confidential
    # System
    "0041": "1020",  # ConfigurationData → Internal
    "0042": "1030",  # AccessControlData → Confidential
    "0086": "1030",  # SecurityDecision → Confidential
    "0087": "1020",  # RuntimeData → Internal
    # Transaction
    "0050": "1020",  # TransactionInformation → Internal
    # Transformation
    "0088": "1030",  # Encryption → Confidential
    "0089": "1010",  # Hashing → Public
    "0090": "1020",  # Masking → Internal
    "0091": "1020",  # Anonymization → Internal
}


def atlas_classification_defs() -> list[dict]:
    """Return Atlas classificationDefs for every leaf category.

    Each classification type carries ``confidence`` and ``evidence``
    attribute definitions so the basis for every tag is recorded.
    """
    defs = []
    leaf_codes = {c.code for c in CATEGORIES} - {
        c.parent_code for c in CATEGORIES if c.parent_code
    }
    for cat in CATEGORIES:
        if cat.code not in leaf_codes:
            continue
        defs.append({
            "name": cat.atlas_type_name,
            "description": f"SIGDG {cat.curie}: {cat.description}",
            "attributeDefs": [
                {
                    "name": "confidence",
                    "typeName": "float",
                    "isOptional": True,
                    "cardinality": "SINGLE",
                },
                {
                    "name": "evidence",
                    "typeName": "string",
                    "isOptional": True,
                    "cardinality": "SINGLE",
                },
            ],
        })
    return defs
