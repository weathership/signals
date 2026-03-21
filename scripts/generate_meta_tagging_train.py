#!/usr/bin/env python3
"""Generate synthetic training COLUMNS for CatBoost meta-tagging classifier.

For each of 175 annotation categories, produces ~30 synthetic columns:
  - ~15 semantic-name variants (diverse human-readable column names)
  - ~15 opaque-name variants (random/coded names with category-matching values)

The opaque-name variants force CatBoost to learn from VALUE PATTERNS rather than
column names — critical for classifying annotation columns like attr_1_1_1_8_1.

Output:
  build/datasets/sigint_train/
    ├── synth_001.csv ... synth_NNN.csv   (wide-format, 100 rows each)
    ├── ground_truth.json                  (column → annotation code)
    └── annotations.csv                    (copy of controlled vocabulary)

Usage:
    uv run python scripts/generate_meta_tagging_train.py \
        --data-dir ~/local/tmp/meta-tagging/ \
        --output-dir build/datasets/sigint_train/ \
        --variants-per-category 30
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import re
import string
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

LOG = logging.getLogger(__name__)

# ── Name generation infrastructure ──────────────────────────────────

# Synonym table for common data terms → abbreviations / variants
SYNONYMS: dict[str, list[str]] = {
    "number": ["num", "no", "nbr", "nr"],
    "address": ["addr", "adr"],
    "phone": ["tel", "ph", "phn"],
    "telephone": ["tel", "phone", "ph"],
    "identifier": ["id", "ident"],
    "identification": ["id", "ident"],
    "account": ["acct", "acc"],
    "information": ["info", "inf"],
    "description": ["desc", "dsc"],
    "transaction": ["txn", "trans", "trx"],
    "password": ["pwd", "passwd", "pass"],
    "first": ["given", "fname", "1st"],
    "last": ["family", "surname", "lname"],
    "middle": ["mid", "mname"],
    "name": ["nm"],
    "credit": ["cr", "cred"],
    "payment": ["pay", "pmt"],
    "card": ["crd", "cd"],
    "date": ["dt", "dte"],
    "email": ["mail", "eml"],
    "billing": ["bill", "bll"],
    "shipping": ["ship", "shp"],
    "street": ["str", "st"],
    "city": ["cty"],
    "state": ["st", "province", "prov"],
    "country": ["ctry", "cnty"],
    "postal": ["zip", "postcode"],
    "mobile": ["cell", "mob"],
    "office": ["ofc", "work"],
    "home": ["hm", "residential"],
    "security": ["sec"],
    "question": ["q", "ques"],
    "answer": ["a", "ans"],
    "social": ["soc"],
    "version": ["ver", "v"],
    "serial": ["sn", "ser"],
    "device": ["dev"],
    "digital": ["dgtl", "dig"],
    "organization": ["org"],
    "subscription": ["sub", "subscr"],
    "registration": ["reg"],
    "certificate": ["cert"],
    "document": ["doc"],
    "documentation": ["doc", "docs"],
    "configuration": ["config", "cfg", "conf"],
    "performance": ["perf"],
    "software": ["sw"],
    "hardware": ["hw"],
    "application": ["app"],
    "gender": ["sex"],
    "birthday": ["dob", "birthdate"],
    "signature": ["sig"],
    "permission": ["perm", "priv"],
    "condition": ["cond"],
    "political": ["pol"],
    "relationship": ["rel"],
    "employment": ["emp"],
    "financial": ["fin"],
    "technical": ["tech"],
    "incident": ["inc"],
    "code": ["cd"],
    "value": ["val"],
    "expiration": ["exp"],
    "verification": ["verif"],
    "location": ["loc"],
    "latitude": ["lat"],
    "longitude": ["lon", "lng"],
    "bundle": ["bdl"],
    "session": ["sess"],
    "user": ["usr"],
    "employee": ["emp"],
    "vendor": ["vnd", "vndr"],
}

# Opaque column name prefixes
_OPAQUE_PREFIXES = [
    "field_", "col_", "meta_", "v_", "x_", "dim_", "f_",
    "attr_", "var_", "c_", "d_", "val_", "p_",
]


def _snake_case(s: str) -> str:
    """Convert a label to snake_case."""
    s = re.sub(r"[^a-zA-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower().replace(" ", "_")


def _camel_case(s: str) -> str:
    """Convert snake_case to camelCase."""
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _upper_snake(s: str) -> str:
    """Convert to UPPER_SNAKE_CASE."""
    return s.upper()


def _generate_semantic_names(
    label: str,
    abbrev: str,
    common_names: str,
    rng: random.Random,
    count: int = 15,
) -> list[str]:
    """Generate diverse semantic column name variants for a category."""
    names: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        n = name.strip().strip("_")
        if n and n not in seen and len(n) > 1:
            seen.add(n)
            names.append(n)

    # Base snake_case from label
    base = _snake_case(label)
    _add(base)

    # camelCase and UPPER_SNAKE
    _add(_camel_case(base))
    _add(_upper_snake(base))

    # Abbreviation
    if abbrev:
        a = abbrev.strip().lower()
        _add(a)
        _add(a.upper())

    # Common Names → split on commas, produce snake variants
    if common_names:
        for cn in common_names.split(","):
            cn = cn.strip()
            if cn:
                sn = _snake_case(cn)
                _add(sn)
                _add(_camel_case(sn))

    # Word-level synonym expansion
    words = base.split("_")
    for i, word in enumerate(words):
        if word in SYNONYMS:
            for syn in SYNONYMS[word]:
                variant = "_".join(words[:i] + [syn] + words[i + 1 :])
                _add(variant)

    # Drop single words for multi-word names
    if len(words) >= 3:
        for i in range(len(words)):
            shortened = "_".join(w for j, w in enumerate(words) if j != i)
            _add(shortened)

    # Prefixed variants
    prefixes = ["user_", "primary_", "customer_", "acct_", "src_", "raw_"]
    for prefix in prefixes:
        _add(prefix + base)
        if abbrev:
            _add(prefix + abbrev.strip().lower())

    # Shuffle and take count
    if len(names) > count:
        result = [names[0]]  # Always include the base name
        rest = names[1:]
        rng.shuffle(rest)
        result.extend(rest[: count - 1])
        return result

    return names[:count] if names else [base]


def _generate_opaque_names(rng: random.Random, count: int = 15) -> list[str]:
    """Generate opaque/coded column names."""
    names: list[str] = []
    for _ in range(count):
        prefix = rng.choice(_OPAQUE_PREFIXES)
        suffix_type = rng.randint(0, 3)
        if suffix_type == 0:
            suffix = str(rng.randint(1, 999))
        elif suffix_type == 1:
            suffix = rng.choice(string.ascii_lowercase) + str(rng.randint(1, 99))
        elif suffix_type == 2:
            suffix = "".join(rng.choices(string.ascii_lowercase, k=2)) + str(rng.randint(1, 9))
        else:
            suffix = str(rng.randint(1, 9)) + "_" + str(rng.randint(1, 9))
        names.append(prefix + suffix)
    return names


# ── Value generators ────────────────────────────────────────────────

_FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard",
    "Joseph", "Thomas", "Charles", "Mary", "Patricia", "Jennifer", "Linda",
    "Barbara", "Elizabeth", "Susan", "Jessica", "Sarah", "Karen", "Lisa",
    "Emily", "Amy", "Anna", "Jane", "Emma", "Sophia", "Olivia", "Mia",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Anderson", "Taylor", "Thomas",
    "Jackson", "White", "Harris", "Martin", "Thompson", "Moore", "Lee",
    "Wilson", "Clark", "Lewis", "Robinson", "Walker", "Young", "Allen",
]
_CITIES = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "San Francisco",
    "Seattle", "Denver", "Boston", "Austin", "Portland", "Miami", "Dallas",
    "Atlanta", "San Diego", "Minneapolis", "Detroit", "Philadelphia",
]
_STATES = ["CA", "TX", "NY", "FL", "WA", "IL", "CO", "MA", "GA", "PA", "AZ", "OH", "OR", "MI", "NC"]
_COUNTRIES = ["US", "USA", "CA", "UK", "GB", "DE", "FR", "JP", "AU", "BR", "IN", "MX", "IT", "ES"]
_STREETS = ["Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine Rd", "Elm St", "Birch Way", "Park Blvd", "Lake Dr", "Hill Rd"]
_RELIGIONS = ["Christian", "Muslim", "Buddhist", "Hindu", "Jewish", "Atheist", "Agnostic", "Sikh"]
_MENTAL = ["Depression", "Anxiety", "PTSD", "Bipolar", "OCD", "ADHD", "Insomnia"]
_PHYSICAL = ["Hypertension", "Diabetes", "Asthma", "Heart disease", "Arthritis", "Migraine"]
_GENETIC = ["BRCA1 positive", "BRCA2 negative", "Factor V Leiden", "Sickle cell trait", "Cystic fibrosis carrier"]
_JOB_TITLES = [
    "Software Engineer", "Data Scientist", "Product Manager", "Designer",
    "Marketing Manager", "Sales Director", "HR Coordinator", "DevOps Engineer",
    "Business Analyst", "Project Manager", "QA Engineer", "CTO",
]
_PERF_RATINGS = ["Exceeds Expectations", "Meets Expectations", "Needs Improvement", "Outstanding"]
_EDUCATION = ["High School", "Associate", "Bachelor's", "Master's", "PhD", "Doctorate"]
_DOMAINS = ["gmail.com", "outlook.com", "yahoo.com", "acmemail.com", "protonmail.com", "company.com"]
_APP_BUNDLES = [
    "com.acme.notes", "com.acme.mail", "com.acme.maps", "com.acme.music",
    "com.facebook.Facebook", "com.google.maps", "com.google.mail",
    "com.facebook.app", "com.acme.photos", "com.twitter.app",
]
_CRASH_TYPES = [
    "EXC_BREAKPOINT", "EXC_BAD_ACCESS", "SIGABRT", "SIGSEGV",
    "EXC_CRASH", "EXC_GUARD", "OutOfMemoryError", "NullPointerException",
]
_SEARCH_QUERIES = [
    "reset password", "cloudsync backup", "account recovery", "privacy settings",
    "delete account", "two factor auth", "billing history", "refund request",
    "app update", "device sync", "family sharing", "storage upgrade",
]
_HARDWARE = [
    "Phone 15, 256GB", "Phone 14, 128GB", "Tablet Pro, 256GB",
    "Tablet Air, 64GB", "Laptop Pro 14, 512GB", "Laptop Air, 256GB",
    "Desktop Pro, 1TB", "SmartWatch Ultra, 64GB",
]
_SW_VERSIONS = [
    "MobileOS 17.4.1", "MobileOS 16.7.2", "MobileOS 15.1.3",
    "DesktopOS 14.3.1", "TabletOS 17.4.0", "WearOS 10.3.1",
]
_USER_AGENTS = [
    "Mozilla/5.0 (SmartPhone; CPU PhoneOS 17_0 like Unix)",
    "Mozilla/5.0 (SmartPhone; CPU PhoneOS 16_0 like Unix)",
    "Mozilla/5.0 (Macintosh; Intel DesktopOS 14_0)",
    "Mozilla/5.0 (Tablet; CPU TabletOS 17_0 like Unix)",
]
_SECURITY_QUESTIONS = [
    "What city were you born in?",
    "What was your first pet's name?",
    "What is your mother's maiden name?",
    "What street did you grow up on?",
    "What was the mascot of your high school?",
    "What was your childhood nickname?",
]
_SECURITY_ANSWERS = [
    "Boston", "Rover", "Thompson", "Oak Street", "Eagles", "Buddy",
    "Seattle", "Max", "Garcia", "Elm Ave", "Tigers", "Sparky",
]
_SEC_FILING_TYPES = [
    "10-K Annual Report 2024", "10-Q Q3 2024", "10-Q Q2 2024",
    "10-Q Q1 2024", "8-K Current Report", "DEF 14A Proxy Statement",
]
_WEBSITES = ["acme.com", "support.acme.com", "developer.acme.com", "store.acme.com"]
_PERMISSIONS = ["READ", "WRITE", "EXECUTE", "ADMIN", "DELETE", "CREATE"]
_SYS_GROUPS = ["admin", "wheel", "developers", "staff", "users", "ops"]
_DATA_TYPES = ["STRING", "INTEGER", "BOOLEAN", "DATE", "FLOAT", "TIMESTAMP", "BINARY"]
_REGEXES = ["^[a-zA-Z0-9]+$", "^\\d{3}-\\d{2}-\\d{4}$", "^[a-z]+@[a-z]+\\.[a-z]+$", "^\\d+$"]
_FAMILY_RELATIONS = ["Parent", "Child", "Spouse", "Sibling", "Grandparent", "Cousin", "Guardian"]
_GENDERS = ["Male", "Female", "Non-binary", "Prefer not to say", "Other"]
_RACES = ["Caucasian", "Hispanic", "African American", "Asian", "Mixed", "Other", "Pacific Islander"]
_RELATIONSHIP_STATUSES = ["Single", "Married", "Divorced", "Separated", "Widowed", "In a relationship"]
_SEXUAL_PREFS = ["Heterosexual", "Homosexual", "Bisexual", "Prefer not to say"]
_POLITICAL = ["Democrat", "Republican", "Independent", "Libertarian", "Green", "None"]
_VULNERABLE = ["Student", "Elderly", "Medical patient", "Asylum seeker", "Disabled person"]
_AGE_DIFF = ["child", "teen", "adult", "minor", "senior"]
_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]
_BENEFITS = ["Medical PPO", "Medical HMO", "Dental", "Vision", "401k", "FSA", "HSA", "Life Insurance"]
_BACKGROUND = ["Clear", "Review Required", "Pending"]
_TITLES = ["Mr.", "Mrs.", "Ms.", "Mx.", "Dr.", "Prof.", "Sir"]
_LANGUAGES = ["en", "es", "fr", "de", "ja", "zh", "ko", "pt", "it", "ru"]


def gen_credit_card(rng: random.Random) -> str:
    prefixes = ["4", "5", "37", "6011"]
    prefix = rng.choice(prefixes)
    length = 15 if prefix == "37" else 16
    return prefix + "".join(str(rng.randint(0, 9)) for _ in range(length - len(prefix)))


def gen_cvv(rng: random.Random) -> str:
    return str(rng.randint(100, 9999)).zfill(rng.choice([3, 4]))


def gen_magstripe(rng: random.Random) -> str:
    pan = gen_credit_card(rng)
    name = f"{rng.choice(_LAST_NAMES)}/{rng.choice(_FIRST_NAMES)}"
    exp = f"{rng.randint(24,31):02d}{rng.randint(1,12):02d}"
    svc = f"{rng.randint(100,999):03d}{rng.randint(1000,9999):04d}"
    return f"%B{pan}^{name}^{exp}{svc}?"


def gen_bin(rng: random.Random) -> str:
    return str(rng.randint(100000, 999999))


def gen_last4(rng: random.Random) -> str:
    return str(rng.randint(1000, 9999))


def gen_bank_account(rng: random.Random) -> str:
    length = rng.randint(8, 14)
    return "".join(str(rng.randint(0, 9)) for _ in range(length))


def gen_cc_exp(rng: random.Random) -> str:
    return f"{rng.randint(1,12):02d}/{rng.randint(25,32):02d}"


def gen_masked_pan(rng: random.Random) -> str:
    first6 = "".join(str(rng.randint(0, 9)) for _ in range(6))
    last4 = "".join(str(rng.randint(0, 9)) for _ in range(4))
    return f"{first6}******{last4}"


def gen_debit_pin(rng: random.Random) -> str:
    return str(rng.randint(1000, 9999))


def gen_paypal_id(rng: random.Random) -> str:
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(rng.choices(chars, k=20))
    return f"PAYID-{suffix}"


def gen_invoice_num(rng: random.Random) -> str:
    return f"INV-{rng.randint(2019,2025)}-{rng.randint(10000,99999)}"


def gen_credit_score(rng: random.Random) -> str:
    return str(rng.randint(300, 850))


def gen_fraud_score(rng: random.Random) -> str:
    return f"{rng.random():.2f}"


def gen_salary(rng: random.Random) -> str:
    amount = rng.randint(30, 350) * 1000
    return f"${amount:,}/year"


def gen_stock(rng: random.Random) -> str:
    return f"{rng.randint(100, 10000)} RSUs"


def gen_bonus(rng: random.Random) -> str:
    return f"${rng.randint(1, 100) * 1000:,}"


def gen_date(rng: random.Random, y_lo: int = 1950, y_hi: int = 2025) -> str:
    y = rng.randint(y_lo, y_hi)
    m = rng.randint(1, 12)
    d = rng.randint(1, 28)
    return f"{y:04d}-{m:02d}-{d:02d}"


def gen_timestamp(rng: random.Random) -> str:
    dt = gen_date(rng, 2019, 2025)
    h, mi, s = rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)
    return f"{dt}T{h:02d}:{mi:02d}:{s:02d}.000Z"


def gen_ipv4(rng: random.Random) -> str:
    return ".".join(str(rng.randint(1, 254)) for _ in range(4))


def gen_email(rng: random.Random, domain: str | None = None) -> str:
    first = rng.choice(_FIRST_NAMES).lower()
    last = rng.choice(_LAST_NAMES).lower()
    sep = rng.choice([".", "_", ""])
    num = rng.randint(1, 99)
    dom = domain or rng.choice(_DOMAINS)
    return f"{first}{sep}{last}{num}@{dom}"


def gen_phone(rng: random.Random) -> str:
    return f"+1-{rng.randint(200,999)}-{rng.randint(100,999)}-{rng.randint(1000,9999)}"


def gen_uuid(rng: random.Random) -> str:
    def _hex(n: int) -> str:
        return "".join(rng.choices("0123456789ABCDEF", k=n))
    return f"{_hex(8)}-{_hex(4)}-{_hex(4)}-{_hex(4)}-{_hex(12)}"


def gen_full_address(rng: random.Random) -> str:
    num = rng.randint(1, 9999)
    street = rng.choice(_STREETS)
    city = rng.choice(_CITIES)
    state = rng.choice(_STATES)
    zipcode = f"{rng.randint(10000, 99999)}"
    return f"{num} {street}, {city}, {state} {zipcode}, USA"


def gen_street(rng: random.Random) -> str:
    return f"{rng.randint(1, 9999)} {rng.choice(_STREETS)}"


def gen_postal_code(rng: random.Random) -> str:
    return f"{rng.randint(10000, 99999)}"


def gen_coarse_location(rng: random.Random) -> str:
    areas = [
        "San Francisco Bay Area", "Greater Los Angeles", "New York Metro",
        "Chicago Metro", "Dallas-Fort Worth", "Greater Seattle",
        "Greater Boston", "Denver Metro", "Atlanta Metro",
    ]
    return rng.choice(areas)


def gen_precise_location(rng: random.Random) -> str:
    lat = round(rng.uniform(25.0, 48.0), 6)
    lon = round(rng.uniform(-124.0, -71.0), 6)
    return f"{lat}, {lon}"


def gen_tax_jurisdiction(rng: random.Random) -> str:
    return f"{rng.choice(_STATES)}-JUR-{rng.randint(10000, 99999)}"


def gen_household_income(rng: random.Random) -> str:
    lo = rng.randint(20, 300) * 1000
    hi = lo + rng.randint(10, 80) * 1000
    return f"${lo:,}-${hi:,}"


def gen_login_event(rng: random.Random) -> str:
    ts = gen_timestamp(rng)
    ip = gen_ipv4(rng)
    return f"{ts} login from {ip}"


def gen_sec_ref(rng: random.Random) -> str:
    return f"SEC-{rng.randint(2019, 2025)}-{rng.randint(1000, 9999)}"


def gen_forum_post(rng: random.Random) -> str:
    topics = ["settings", "apps", "privacy", "performance", "battery", "display", "storage"]
    return f"Forum post about {rng.choice(topics)}"


def gen_personal_url(rng: random.Random) -> str:
    platforms = ["twitter.com", "github.com", "linkedin.com", "facebook.com"]
    first = rng.choice(_FIRST_NAMES).lower()
    last = rng.choice(_LAST_NAMES).lower()
    num = rng.randint(1, 99)
    return f"https://{rng.choice(platforms)}/{first}{last}{num}"


def gen_filename(rng: random.Random) -> str:
    exts = ["xlsx", "pdf", "docx", "jpg", "png", "txt", "csv"]
    prefixes = ["report", "document", "data", "output", "backup", "export"]
    return f"{rng.choice(prefixes)}_{rng.randint(1, 9999)}.{rng.choice(exts)}"


def gen_photo(rng: random.Random) -> str:
    return f"IMG_{rng.randint(1000, 9999)}.{rng.choice(['png', 'jpg', 'heic'])}"


def gen_video(rng: random.Random) -> str:
    return f"MOV_{rng.randint(1000, 9999)}.{rng.choice(['mov', 'mp4', 'm4v'])}"


def gen_user_activity(rng: random.Random) -> str:
    actions = ["click", "tap", "swipe", "scroll", "long_press", "double_tap"]
    x, y = rng.randint(0, 2000), rng.randint(0, 1500)
    return f"{rng.choice(actions)} at ({x}, {y})"


def gen_config_json(rng: random.Random) -> str:
    dm = rng.choice(["true", "false"])
    lang = rng.choice(_LANGUAGES)
    return f'{{"darkMode": {dm}, "language": "{lang}"}}'


def gen_device_metrics(rng: random.Random) -> str:
    cpu = rng.randint(1, 99)
    mem = round(rng.uniform(1.0, 16.0), 1)
    bat = rng.randint(1, 100)
    return f"CPU: {cpu}%, Memory: {mem}GB, Battery: {bat}%"


def gen_esign(rng: random.Random) -> str:
    first = rng.choice(_FIRST_NAMES)
    last = rng.choice(_LAST_NAMES)
    return f"/s/ {first} {last}"


def gen_key_material(rng: random.Random) -> str:
    hex_part = "".join(rng.choices("0123456789ABCDEF", k=8))
    hex2 = "".join(rng.choices("0123456789ABCDEF", k=4))
    hex3 = "".join(rng.choices("0123456789ABCDEF", k=2))
    return f"KEY-{hex_part}-{hex2}-{hex3}"


def gen_key_digest(rng: random.Random) -> str:
    h = "".join(rng.choices("0123456789abcdef", k=32))
    return f"SHA256:{h}"


def gen_social_media(rng: random.Random) -> str:
    first = rng.choice(_FIRST_NAMES).lower()
    num = rng.randint(1, 999)
    return f"@{first}{num}"


def gen_full_name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"


def gen_device_name(rng: random.Random) -> str:
    name = rng.choice(_FIRST_NAMES)
    device = rng.choice(["Laptop Pro", "Laptop Air", "SmartPhone", "Tablet", "Desktop Pro"])
    return f"{name}'s {device}"


def gen_passport(rng: random.Random) -> str:
    return str(rng.randint(100000000, 999999999))


def gen_prefixed_id(prefix: str, rng: random.Random, length: int = 6) -> str:
    return prefix + str(rng.randint(10 ** (length - 1), 10**length - 1))


def gen_cpf(rng: random.Random) -> str:
    d = [rng.randint(0, 9) for _ in range(11)]
    return f"{d[0]}{d[1]}{d[2]}.{d[3]}{d[4]}{d[5]}.{d[6]}{d[7]}{d[8]}-{d[9]}{d[10]}"


def gen_india_pan(rng: random.Random) -> str:
    letters = string.ascii_uppercase
    return "".join(rng.choices(letters, k=5)) + str(rng.randint(1000, 9999)) + rng.choice(letters)


def gen_ssn(rng: random.Random) -> str:
    return f"{rng.randint(100,999)}-{rng.randint(10,99)}-{rng.randint(1000,9999)}"


def gen_vatin(rng: random.Random) -> str:
    prefix = rng.choice(["IT", "DE", "FR", "ES", "GB", "NL"])
    return prefix + str(rng.randint(100000000, 999999999))


def gen_drivers_license(rng: random.Random) -> str:
    prefix = rng.choice(["DL", "D", "S", "L"])
    return prefix + str(rng.randint(1000000, 9999999))


def gen_hex_id(rng: random.Random, length: int = 40) -> str:
    return "".join(rng.choices("0123456789ABCDEF", k=length))


def gen_numeric_id(rng: random.Random, length: int = 10) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(length))


def gen_mac_address(rng: random.Random) -> str:
    return ":".join(f"{rng.randint(0, 255):02X}" for _ in range(6))


def gen_serial(rng: random.Random) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(rng.choices(chars, k=12))


def gen_session_id(rng: random.Random) -> str:
    chars = string.ascii_lowercase + string.digits
    return "sess_" + "".join(rng.choices(chars, k=24))


def gen_ldap_group(rng: random.Random) -> str:
    n = rng.randint(1, 100)
    return f"cn=group{n},ou=groups,dc=company"


def gen_session_json(rng: random.Random) -> str:
    uid = rng.randint(1000, 9999)
    y, m, d = rng.randint(2020, 2025), rng.randint(1, 12), rng.randint(1, 28)
    return f'{{"userId": "{uid}", "expires": "{y:04d}-{m:02d}-{d:02d}"}}'


def gen_system_url(rng: random.Random) -> str:
    versions = ["v1", "v2", "v3"]
    hosts = ["api.example.com", "internal.acme.com", "svc.cluster.local"]
    return f"https://{rng.choice(hosts)}/{rng.choice(versions)}"


def gen_cluster_node(rng: random.Random) -> str:
    return f"node{rng.randint(1, 20)}.cluster.local"


def gen_file_path(rng: random.Random) -> str:
    dirs = ["/var/log", "/tmp", "/opt/app", "/data", "/var/run"]
    names = ["app", "service", "worker", "daemon", "api"]
    exts = ["log", "pid", "sock", "conf"]
    return f"{rng.choice(dirs)}/{rng.choice(names)}_{rng.randint(1, 100)}.{rng.choice(exts)}"


def gen_executable(rng: random.Random) -> str:
    bins = ["/usr/bin/python3", "/usr/bin/node", "/usr/bin/java",
            "/usr/local/bin/go", "/usr/bin/ruby", "/usr/bin/perl"]
    return rng.choice(bins)


def gen_runtime_data(rng: random.Random) -> str:
    return f"runtime_data_{rng.randint(1, 100)}"


def gen_document_ref(rng: random.Random) -> str:
    return f"Document_{rng.randint(1000, 9999)}.pdf"


def gen_trade_secret(rng: random.Random) -> str:
    return f"Trade Secret Document #{rng.randint(1000, 9999)}"


def gen_employment_detail(rng: random.Random) -> str:
    dt = gen_date(rng, 2015, 2024)
    manager = gen_full_name(rng)
    return f"Start: {dt}, Manager: {manager}"


def gen_null(rng: random.Random) -> str:
    return "NULL"


def gen_country_code(rng: random.Random) -> str:
    codes = ["+1", "+44", "+49", "+33", "+61", "+91", "+55", "+81", "+86", "+7"]
    return rng.choice(codes)


def gen_area_code(rng: random.Random) -> str:
    return str(rng.randint(200, 999))


def gen_subscriber_number(rng: random.Random) -> str:
    return f"{rng.randint(100,999)}-{rng.randint(1000,9999)}"


def gen_prefix_number(rng: random.Random) -> str:
    return str(rng.randint(100, 999))


def gen_line_number(rng: random.Random) -> str:
    return str(rng.randint(1000, 9999))


def gen_extension(rng: random.Random) -> str:
    return f"x{rng.randint(100, 9999)}"


def gen_bundle_id(rng: random.Random) -> str:
    return rng.choice(_APP_BUNDLES)


def gen_biometric_id(rng: random.Random) -> str:
    h = "".join(rng.choices("0123456789ABCDEF", k=8))
    return f"BIOMETRIC-{h}"


def gen_sec_filing(rng: random.Random) -> str:
    return rng.choice(_SEC_FILING_TYPES)


# ── Category specification ──────────────────────────────────────────


@dataclass
class CategorySpec:
    """Maps an annotation code to its value generator and name metadata."""
    code: str
    label: str
    abbrev: str
    common_names: str
    generator: Callable[[random.Random], str]


def _build_category_specs(annotations_path: Path) -> list[CategorySpec]:
    """Build category specs from annotations.csv.

    Returns only leaf, non-deprecated categories with value generators.
    """
    # Parse annotations CSV
    rows: list[dict] = []
    with open(annotations_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        id_col = "ID"
        if reader.fieldnames:
            for fn in reader.fieldnames:
                if fn.strip("' \ufeff") == "ID":
                    id_col = fn
                    break
        for row in reader:
            row_id = (row.get(id_col) or "").strip()
            if not row_id or not row_id[0].isdigit():
                continue
            row["_id"] = row_id
            rows.append(row)

    all_ids = {r["_id"] for r in rows}

    def _is_leaf(rid: str) -> bool:
        prefix = rid + "."
        return not any(o.startswith(prefix) and o != rid for o in all_ids)

    # Value generator dispatch by annotation code
    generators: dict[str, Callable[[random.Random], str]] = {
        # Payment Card Data
        "1.1.1.1.1.1.1": gen_credit_card,
        "1.1.1.1.1.1.2": gen_cvv,
        "1.1.1.1.1.1.3": gen_magstripe,
        "1.1.1.1.1.1.4": gen_bin,
        "1.1.1.1.1.1.5": gen_last4,
        "1.1.1.1.1.1.6": gen_bank_account,
        "1.1.1.1.1.1.7": gen_cc_exp,
        "1.1.1.1.1.1.8": gen_masked_pan,
        "1.1.1.1.1.1.9": gen_debit_pin,
        # Other Billing
        "1.1.1.1.1.2.1": gen_paypal_id,
        "1.1.1.1.1.2.2": gen_invoice_num,
        # Credit Data
        "1.1.1.1.2.1": gen_credit_score,
        "1.1.1.1.2.2": gen_fraud_score,
        "1.1.1.1.2.3": lambda rng: rng.choice(["Green", "Yellow", "Orange", "Red"]),
        # Demographic - Income
        "1.1.1.2.1.1": gen_salary,
        "1.1.1.2.1.2": gen_stock,
        "1.1.1.2.1.3": gen_bonus,
        "1.1.1.2.1.4": lambda rng: rng.choice(_BENEFITS),
        # Demographic - Core
        "1.1.1.2.2": lambda rng: rng.choice(_GENDERS),
        "1.1.1.2.3.1": lambda rng: str(rng.randint(18, 90)),
        "1.1.1.2.3.2": lambda rng: gen_date(rng, 1940, 2010),
        "1.1.1.2.3.3": lambda rng: str(rng.randint(1940, 2010)),
        "1.1.1.2.3.4.1": lambda rng: rng.choice(["true", "false"]),
        "1.1.1.2.3.4.2": lambda rng: rng.choice(["true", "false"]),
        "1.1.1.2.3.4.3": lambda rng: rng.choice(_AGE_DIFF),
        "1.1.1.2.3.5": lambda rng: rng.choice(_MONTHS),
        "1.1.1.2.3.6": lambda rng: str(rng.randint(1, 31)),
        "1.1.1.2.4": lambda rng: rng.choice(_RACES),
        "1.1.1.2.5.1": lambda rng: rng.choice(_JOB_TITLES),
        "1.1.1.2.5.2": lambda rng: rng.choice(_PERF_RATINGS),
        "1.1.1.2.5.3": gen_employment_detail,
        "1.1.1.2.6": lambda rng: rng.choice(_EDUCATION),
        "1.1.1.2.7": lambda rng: rng.choice(_BACKGROUND),
        "1.1.1.2.8": lambda rng: rng.choice(["Yes", "No"]),
        "1.1.1.2.9": lambda rng: rng.choice(["Yes", "No"]),
        # Psychographic
        "1.1.1.3.1": lambda rng: rng.choice(_RELIGIONS),
        "1.1.1.3.4.1": lambda rng: rng.choice(_RELATIONSHIP_STATUSES),
        "1.1.1.3.4.2": lambda rng: rng.choice(_SEXUAL_PREFS),
        "1.1.1.3.4.3": lambda rng: rng.choice(_POLITICAL),
        "1.1.1.3.4.4": lambda rng: rng.choice(_VULNERABLE),
        # Geographic - Full addresses
        "1.1.1.4.1.1": gen_full_address,
        "1.1.1.4.1.2": gen_full_address,
        # Geographic - Split addresses
        "1.1.1.4.2.1.1": gen_street,
        "1.1.1.4.2.1.2": gen_street,
        "1.1.1.4.2.2.1": lambda rng: rng.choice(_CITIES),
        "1.1.1.4.2.2.2": lambda rng: rng.choice(_CITIES),
        "1.1.1.4.2.3.1": gen_postal_code,
        "1.1.1.4.2.3.2": gen_postal_code,
        "1.1.1.4.2.4.1": lambda rng: rng.choice(_STATES),
        "1.1.1.4.2.4.2": lambda rng: rng.choice(_STATES),
        "1.1.1.4.2.5.1": lambda rng: rng.choice(_COUNTRIES),
        "1.1.1.4.2.5.2": lambda rng: rng.choice(_COUNTRIES),
        # Geographic - Location
        "1.1.1.4.3.1": gen_coarse_location,
        "1.1.1.4.3.2": gen_precise_location,
        "1.1.1.4.4": gen_ipv4,
        "1.1.1.4.6": gen_tax_jurisdiction,
        # Socioeconomic
        "1.1.1.5.1": gen_household_income,
        # Health
        "1.1.1.6.1": lambda rng: rng.choice(_MENTAL),
        "1.1.1.6.2": lambda rng: rng.choice(_PHYSICAL),
        "1.1.1.6.3": lambda rng: rng.choice(_GENETIC),
        "1.1.1.6.4": gen_biometric_id,
        # Product Usage
        "1.1.1.7.1": gen_login_event,
        "1.1.1.7.2": lambda rng: rng.choice(_CRASH_TYPES),
        "1.1.1.7.3.1": gen_sec_ref,
        "1.1.1.7.3.2": gen_sec_ref,
        "1.1.1.7.3.3": gen_sec_ref,
        "1.1.1.7.4.1.1": gen_forum_post,
        "1.1.1.7.4.1.2": gen_personal_url,
        "1.1.1.7.4.1.3": gen_filename,
        "1.1.1.7.4.1.4": lambda rng: rng.choice(_SEARCH_QUERIES),
        "1.1.1.7.4.2.1": gen_photo,
        "1.1.1.7.4.2.2": gen_video,
        "1.1.1.7.4.3": gen_user_activity,
        "1.1.1.7.5": gen_config_json,
        "1.1.1.7.6.1": gen_device_metrics,
        "1.1.1.7.7": lambda rng: rng.choice(_HARDWARE),
        "1.1.1.7.8": lambda rng: rng.choice(_SW_VERSIONS),
        "1.1.1.7.9": gen_bundle_id,
        "1.1.1.7.10": lambda rng: rng.choice(_USER_AGENTS),
        # Authentication
        "1.1.1.8.1": lambda rng: "********",
        "1.1.1.8.2": lambda rng: "****",
        "1.1.1.8.3.1": lambda rng: rng.choice(_SECURITY_QUESTIONS),
        "1.1.1.8.3.2": lambda rng: rng.choice(_SECURITY_ANSWERS),
        "1.1.1.8.4": gen_esign,
        "1.1.1.8.5": gen_key_material,
        "1.1.1.8.6": gen_key_digest,
        # Contact - Names
        "1.1.1.9.1": gen_full_name,
        "1.1.1.9.2.1": lambda rng: rng.choice(_FIRST_NAMES),
        "1.1.1.9.2.2": lambda rng: rng.choice(_FIRST_NAMES),  # middle names from same pool
        "1.1.1.9.2.3": lambda rng: rng.choice(_LAST_NAMES),
        "1.1.1.9.2.4": lambda rng: rng.choice(_FIRST_NAMES),  # nicknames
        "1.1.1.9.2.5": gen_full_name,  # other name
        "1.1.1.9.2.6": lambda rng: rng.choice(_TITLES),
        # Contact - Electronic
        "1.1.1.9.3.1": gen_email,
        "1.1.1.9.3.2": gen_social_media,
        # Contact - Phone Numbers (full)
        "1.1.1.9.4.1": gen_phone,
        "1.1.1.9.4.2": gen_phone,
        "1.1.1.9.4.3": gen_phone,
        "1.1.1.9.4.4": gen_phone,
        "1.1.1.9.4.5": gen_phone,
        # Contact - Phone Number (split)
        "1.1.1.9.5.1": gen_country_code,
        "1.1.1.9.5.2": gen_area_code,
        "1.1.1.9.5.3": gen_subscriber_number,
        "1.1.1.9.5.4": gen_prefix_number,
        "1.1.1.9.5.5": gen_line_number,
        "1.1.1.9.5.6": gen_extension,
        # Contact - Family
        "1.1.1.9.6.1": lambda rng: rng.choice(_FAMILY_RELATIONS),
        # Identity - Government
        "1.1.2.1.1.1": gen_passport,
        "1.1.2.1.1.2": lambda rng: gen_prefixed_id("ESTA-", rng, 9),
        "1.1.2.1.1.3": lambda rng: f"EAD-{rng.choice(string.ascii_uppercase)}{rng.randint(10000000, 99999999)}",
        "1.1.2.1.1.4": lambda rng: gen_prefixed_id("UNION-", rng, 5),
        "1.1.2.1.2.1.1": gen_cpf,
        "1.1.2.1.2.1.2": gen_india_pan,
        "1.1.2.1.2.1.3": gen_ssn,
        "1.1.2.1.2.2.1": gen_vatin,
        "1.1.2.1.3": gen_drivers_license,
        # Identity - Platform
        "1.1.2.2.1.1": lambda rng: gen_numeric_id(rng, 10),
        "1.1.2.2.1.2": lambda rng: gen_email(rng),
        "1.1.2.2.1.3.1": lambda rng: gen_prefixed_id("SETUPBUDDY-", rng, 6),
        "1.1.2.2.1.3.2": lambda rng: f"REG-{rng.randint(2020,2025)}-{rng.randint(100000,999999)}",
        "1.1.2.2.1.3.3": lambda rng: gen_prefixed_id("CASE-", rng, 8),
        "1.1.2.2.1.3.4": lambda rng: f"VENDOR-{rng.choice(string.ascii_uppercase)}{rng.choice(string.ascii_uppercase)}{rng.choice(string.ascii_uppercase)}{rng.randint(100,999)}",
        "1.1.2.2.1.3.5": gen_uuid,
        "1.1.2.2.1.3.6": lambda rng: gen_email(rng, "id.acme.com"),
        "1.1.2.2.1.4": lambda rng: f"E{rng.randint(10000, 99999)}",
        "1.1.2.2.1.5": lambda rng: f"user_{rng.randint(100000, 999999)}",
        "1.1.2.2.1.6": lambda rng: f"ID-{gen_hex_id(rng, 8)}-{rng.randint(100,999):03d}",
        # Identity - Device
        "1.1.2.3.1": lambda rng: gen_hex_id(rng, 40),
        "1.1.2.3.2": lambda rng: gen_numeric_id(rng, 20),
        "1.1.2.3.3": lambda rng: gen_numeric_id(rng, 15),
        "1.1.2.3.4": lambda rng: gen_hex_id(rng, 16),
        "1.1.2.3.5": gen_uuid,
        "1.1.2.3.6": gen_device_name,
        "1.1.2.3.7": lambda rng: gen_hex_id(rng, 14),
        "1.1.2.4.1": gen_serial,
        "1.1.2.4.2": gen_mac_address,
        # Transaction
        "1.2.1.1": lambda rng: gen_prefixed_id("SUB-", rng, 9),
        "1.2.1.2": lambda rng: f"W{rng.randint(10000000000, 99999999999)}",
        "1.2.2": lambda rng: gen_date(rng, 2019, 2025),
        "1.2.4": gen_timestamp,
        "1.2.5": gen_session_id,
        "1.2.6.1": lambda rng: gen_numeric_id(rng, 9),
        "1.2.6.2": gen_bundle_id,
        "1.2.6.3": lambda rng: gen_prefixed_id("ORG-", rng, 5),
        # System - Security Decision Data
        "1.3.1.1": gen_ipv4,
        "1.3.1.2": lambda rng: f"admin_{rng.randint(1, 99)}",
        "1.3.1.3.1": gen_ldap_group,
        "1.3.1.3.2": lambda rng: rng.choice(_SYS_GROUPS),
        "1.3.1.4": lambda rng: rng.choice(_PERMISSIONS),
        "1.3.1.5.1": gen_session_json,
        "1.3.1.6.1": lambda rng: rng.choice(_REGEXES),
        "1.3.1.6.2": lambda rng: rng.choice(_DATA_TYPES),
        # System - State
        "1.3.2.1.1": gen_system_url,
        "1.3.2.1.2": gen_cluster_node,
        "1.3.2.1.3": gen_ipv4,
        "1.3.2.1.4": lambda rng: "***REDACTED***",
        "1.3.2.2.1": gen_runtime_data,
        "1.3.2.2.2": gen_runtime_data,
        "1.3.2.2.3": gen_runtime_data,
        "1.3.2.2.4": gen_runtime_data,
        "1.3.2.2.5": gen_runtime_data,
        "1.3.2.2.6": gen_file_path,
        "1.3.2.2.7": gen_executable,
        # System - Meta
        "1.3.3": gen_null,
        "1.3.4": gen_null,
        # Business
        "1.4.1.1.1": gen_document_ref,
        "1.4.1.1.2": gen_document_ref,
        "1.4.1.1.3": gen_document_ref,
        "1.4.1.1.4": gen_document_ref,
        "1.4.1.1.5": gen_document_ref,
        "1.4.1.1.6": gen_document_ref,
        "1.4.1.1.7": gen_document_ref,
        "1.4.1.2.1": gen_sec_filing,
        "1.4.1.2.2": lambda rng: rng.choice(_WEBSITES),
        "1.4.2": gen_trade_secret,
    }

    specs: list[CategorySpec] = []
    for row in rows:
        rid = row["_id"]
        if not _is_leaf(rid):
            continue
        if rid not in generators:
            LOG.warning("No generator for category %s (%s), skipping",
                        rid, (row.get("Ontology") or "").strip())
            continue

        ontology = (row.get("Ontology") or "").strip()
        annotation = (row.get("Annotation") or "").strip()
        common_names = (row.get("Common Names") or "").strip()

        specs.append(CategorySpec(
            code=rid,
            label=ontology,
            abbrev=annotation,
            common_names=common_names,
            generator=generators[rid],
        ))

    return specs


# ── Output generation ───────────────────────────────────────────────


def generate_columns(
    specs: list[CategorySpec],
    variants_per_category: int,
    rows_per_column: int,
    seed: int,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Generate synthetic columns and ground truth mapping.

    Returns:
        columns: {column_name: [values...]}
        ground_truth: {column_name: annotation_code}
    """
    rng = random.Random(seed)
    columns: dict[str, list[str]] = {}
    ground_truth: dict[str, str] = {}

    n_semantic = max(1, variants_per_category // 2)
    n_opaque = max(1, variants_per_category - n_semantic)

    used_names: set[str] = set()

    for spec in specs:
        cat_rng = random.Random(rng.randint(0, 2**63))

        # Generate semantic name variants
        semantic_names = _generate_semantic_names(
            spec.label, spec.abbrev, spec.common_names, cat_rng, count=n_semantic
        )
        # Generate opaque name variants
        opaque_names = _generate_opaque_names(cat_rng, count=n_opaque)

        all_names = semantic_names + opaque_names

        for name in all_names:
            # Ensure unique column names
            unique_name = name
            counter = 1
            while unique_name in used_names:
                unique_name = f"{name}_{counter}"
                counter += 1
            used_names.add(unique_name)

            # Generate values using the category's generator
            values = [spec.generator(cat_rng) for _ in range(rows_per_column)]
            columns[unique_name] = values
            ground_truth[unique_name] = spec.code

    return columns, ground_truth


def write_output(
    columns: dict[str, list[str]],
    ground_truth: dict[str, str],
    output_dir: Path,
    annotations_src: Path,
    columns_per_file: int = 50,
) -> None:
    """Write synthetic training data as CSV files + ground_truth.json."""
    output_dir.mkdir(parents=True, exist_ok=True)

    col_names = list(columns.keys())
    n_rows = len(next(iter(columns.values()))) if columns else 0

    # Split into multiple CSV files
    file_idx = 1
    for start in range(0, len(col_names), columns_per_file):
        chunk = col_names[start : start + columns_per_file]
        csv_path = output_dir / f"synth_{file_idx:03d}.csv"

        # Use table.column format headers (table = synth_NNN)
        table_name = f"synth_{file_idx:03d}"
        headers = [f"{table_name}.{c}" for c in chunk]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row_idx in range(n_rows):
                writer.writerow([columns[c][row_idx] for c in chunk])

        LOG.info("Wrote %s (%d columns, %d rows)", csv_path.name, len(chunk), n_rows)
        file_idx += 1

    # Write ground truth (with table prefix for each file)
    gt_with_tables: dict[str, str] = {}
    file_idx = 1
    for start in range(0, len(col_names), columns_per_file):
        chunk = col_names[start : start + columns_per_file]
        for c in chunk:
            gt_with_tables[c] = ground_truth[c]
        file_idx += 1

    gt_path = output_dir / "ground_truth.json"
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump({"mappings": gt_with_tables}, f, indent=2)
    LOG.info("Wrote ground truth: %d columns -> %s", len(gt_with_tables), gt_path)

    # Copy annotations.csv
    if annotations_src.exists():
        ann_dest = output_dir / "annotations.csv"
        ann_dest.write_text(annotations_src.read_text(encoding="utf-8"), encoding="utf-8")
        LOG.info("Copied annotations.csv")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate synthetic training columns for CatBoost meta-tagging classifier."
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Path to meta-tagging directory (must contain annotations.csv).",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/datasets/sigint_train"),
        help="Target directory for generated training data.",
    )
    p.add_argument(
        "--variants-per-category",
        type=int,
        default=30,
        help="Number of synthetic columns per category (default: 30).",
    )
    p.add_argument(
        "--rows-per-column",
        type=int,
        default=100,
        help="Number of rows per synthetic column (default: 100).",
    )
    p.add_argument(
        "--columns-per-file",
        type=int,
        default=50,
        help="Max columns per output CSV file (default: 50).",
    )
    p.add_argument("--seed", type=int, default=42, help="Random seed.")
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    data_dir = args.data_dir.expanduser()
    ann_path = data_dir / "annotations.csv"
    if not ann_path.exists():
        LOG.error("annotations.csv not found in %s", data_dir)
        return 1

    LOG.info("Loading categories from %s", ann_path)
    specs = _build_category_specs(ann_path)
    LOG.info("Loaded %d leaf categories with generators", len(specs))

    total_cols = len(specs) * args.variants_per_category
    LOG.info(
        "Generating %d columns (%d categories x %d variants, %d rows each)",
        total_cols, len(specs), args.variants_per_category, args.rows_per_column,
    )

    columns, ground_truth = generate_columns(
        specs,
        variants_per_category=args.variants_per_category,
        rows_per_column=args.rows_per_column,
        seed=args.seed,
    )

    LOG.info("Generated %d synthetic columns", len(columns))

    write_output(
        columns, ground_truth, args.output_dir, ann_path,
        columns_per_file=args.columns_per_file,
    )

    # Summary stats
    codes = set(ground_truth.values())
    LOG.info("Output: %d columns covering %d categories in %s",
             len(ground_truth), len(codes), args.output_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
