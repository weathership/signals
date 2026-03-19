"""Tests for scripts/generate_meta_tagging_train.py name and value generators."""

from __future__ import annotations

import csv
import json
import random
import re
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

# Allow importing from scripts/
_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from generate_meta_tagging_train import (
    CategorySpec,
    _build_category_specs,
    _generate_opaque_names,
    _generate_semantic_names,
    _OPAQUE_PREFIXES,
    gen_bank_account,
    gen_credit_card,
    gen_credit_score,
    gen_cvv,
    gen_date,
    gen_drivers_license,
    gen_email,
    gen_full_address,
    gen_full_name,
    gen_invoice_num,
    gen_ipv4,
    gen_mac_address,
    gen_masked_pan,
    gen_passport,
    gen_paypal_id,
    gen_phone,
    gen_postal_code,
    gen_salary,
    gen_serial,
    gen_session_id,
    gen_ssn,
    gen_timestamp,
    gen_uuid,
    generate_columns,
    write_output,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def rng():
    """Deterministic random generator for reproducible tests."""
    return random.Random(12345)


@pytest.fixture
def annotations_csv(tmp_path: Path) -> Path:
    """Create a minimal annotations.csv for testing."""
    csv_path = tmp_path / "annotations.csv"
    csv_path.write_text(textwrap.dedent("""\
        ID,Ontology,Annotation,Definition,Common Names
        1,Personal Data,PD,,
        1.1,Personal Data - Sensitive,PDS,,
        1.1.1,PII,PII,,
        1.1.1.1,Financial,FIN,,
        1.1.1.1.1,Payment,PAY,,
        1.1.1.1.1.1,Card Data,CD,,
        1.1.1.1.1.1.1,Credit Card Number,CCN,Primary account number,"credit_card,cc_number,pan"
        1.1.1.1.1.1.2,Card Verification Value,CVV,Security code,"cvv,cvc,security_code"
        1.1.1.1.1.1.3,Magnetic Stripe Data,MSD,Track data,mag_stripe
        1.1.1.1.1.1.4,Bank Identification Number,BIN,First 6 digits,bin_number
        1.1.1.1.1.1.5,Last Four Digits,L4D,Truncated PAN,last_four
        1.1.1.1.1.1.6,Bank Account Number,BAN,Account number,"bank_acct,account_number"
        1.1.1.1.1.1.7,Card Expiration Date,CED,Expiry,"cc_exp,expiry_date"
        1.1.1.1.1.1.8,Masked PAN,MPAN,Masked card number,masked_pan
        1.1.1.1.1.1.9,Debit PIN,DPIN,ATM PIN,debit_pin
        1.1.1.9,Contact,CONTACT,,
        1.1.1.9.1,Full Name,FN,Complete name,"full_name,name,person_name"
        1.1.1.9.3,Electronic Contact,EC,,
        1.1.1.9.3.1,Email Address,EMAIL,Email address,"email,email_address,e_mail"
        1.1.1.9.4,Phone Numbers,TEL,,
        1.1.1.9.4.1,Personal Phone,PERS_PHONE,Personal number,"personal_phone,cell_phone"
        1.1.2,Identity,IDT,,
        1.1.2.1,Government ID,GOVID,,
        1.1.2.1.2,National ID,NATID,,
        1.1.2.1.2.1,Country Specific,CS,,
        1.1.2.1.2.1.3,Social Security Number,SSN,US SSN,"ssn,social_security"
        1.1.1.4,Geographic,GEO,,
        1.1.1.4.1,Full Address,ADDR,,
        1.1.1.4.1.1,Home Address,HADDR,Home address,"home_address,residential_address"
        1.1.1.4.4,IP Address,IP,IPv4/IPv6,"ip_address,ipv4"
        1.1.1.2,Demographic,DEMO,,
        1.1.1.2.1,Income,INC,,
        1.1.1.2.1.1,Salary,SAL,Annual salary,"salary,annual_salary,compensation"
    """), encoding="utf-8")
    return csv_path


@pytest.fixture
def small_specs(annotations_csv: Path) -> list[CategorySpec]:
    """Build specs from the minimal annotations.csv fixture."""
    return _build_category_specs(annotations_csv)


# ── Name generation ──────────────────────────────────────────────────


class TestGenerateSemanticNames:
    def test_returns_list_of_strings(self, rng):
        names = _generate_semantic_names("Credit Card Number", "CCN", "cc_number,pan", rng)
        assert isinstance(names, list)
        assert all(isinstance(n, str) for n in names)

    def test_returns_diverse_names(self, rng):
        names = _generate_semantic_names(
            "Credit Card Number", "CCN", "credit_card,cc_number,pan", rng, count=15
        )
        # Should produce multiple unique variants
        assert len(names) >= 3
        assert len(set(names)) == len(names), "names should be unique"

    def test_base_snake_case_included(self, rng):
        names = _generate_semantic_names("Email Address", "EMAIL", "email,e_mail", rng)
        assert names[0] == "email_address"

    def test_camel_case_included(self, rng):
        # Use large count to avoid shuffle truncation
        names = _generate_semantic_names("Email Address", "EMAIL", "", rng, count=50)
        assert "emailAddress" in names

    def test_upper_snake_included(self, rng):
        names = _generate_semantic_names("Email Address", "EMAIL", "", rng)
        assert "EMAIL_ADDRESS" in names

    def test_abbreviation_included(self, rng):
        names = _generate_semantic_names("Social Security Number", "SSN", "", rng)
        assert "ssn" in names

    def test_common_names_expand(self, rng):
        names = _generate_semantic_names(
            "Credit Card Number", "CCN", "pan,card_number", rng, count=30
        )
        assert "pan" in names
        assert "card_number" in names

    def test_synonym_expansion(self, rng):
        names = _generate_semantic_names("Phone Number", "PH", "", rng, count=30)
        # "phone" has synonyms: tel, ph, phn
        # "number" has synonyms: num, no, nbr, nr
        # So we should see variants like "tel_number" or "phone_num"
        synonyms_found = [n for n in names if "tel" in n or "num" == n.split("_")[-1] or "nbr" in n]
        assert len(synonyms_found) > 0

    def test_count_limits_output(self, rng):
        names = _generate_semantic_names(
            "Credit Card Number", "CCN", "cc,pan,card,credit", rng, count=5
        )
        assert len(names) <= 5

    def test_short_label_returns_names(self, rng):
        # Single-char labels get filtered by len(n) > 1 guard, so prefixed
        # variants become the output instead.
        names = _generate_semantic_names("x", "", "", rng)
        assert len(names) >= 1
        # All returned names should contain the base somewhere
        assert any("x" in n for n in names)


class TestGenerateOpaqueNames:
    def test_returns_requested_count(self, rng):
        names = _generate_opaque_names(rng, count=20)
        assert len(names) == 20

    def test_all_have_known_prefix(self, rng):
        names = _generate_opaque_names(rng, count=50)
        for name in names:
            prefix_found = any(name.startswith(p) for p in _OPAQUE_PREFIXES)
            assert prefix_found, f"{name} does not start with a known prefix"

    def test_names_look_coded(self, rng):
        names = _generate_opaque_names(rng, count=30)
        # Each should match prefix + alphanumeric suffix
        pattern = re.compile(r"^[a-z]+_[a-z0-9_]+$")
        for name in names:
            assert pattern.match(name), f"{name} does not match opaque pattern"

    def test_default_count_is_15(self, rng):
        names = _generate_opaque_names(rng)
        assert len(names) == 15


# ── Value generators ─────────────────────────────────────────────────


class TestGenCreditCard:
    def test_length_16_for_visa(self, rng):
        # Seed will produce various prefixes; check all outputs are 15 or 16 digits
        for _ in range(20):
            cc = gen_credit_card(rng)
            assert cc.isdigit()
            assert len(cc) in (15, 16), f"Unexpected length {len(cc)} for {cc}"

    def test_amex_is_15_digits(self):
        # Force AMEX prefix
        r = random.Random(0)
        with patch.object(r, "choice", return_value="37"):
            cc = gen_credit_card(r)
            assert cc.startswith("37")
            assert len(cc) == 15

    def test_visa_prefix(self):
        r = random.Random(0)
        with patch.object(r, "choice", return_value="4"):
            cc = gen_credit_card(r)
            assert cc.startswith("4")
            assert len(cc) == 16


class TestGenEmail:
    def test_contains_at_sign(self, rng):
        for _ in range(20):
            email = gen_email(rng)
            assert "@" in email

    def test_has_domain(self, rng):
        email = gen_email(rng)
        _, domain = email.split("@", 1)
        assert "." in domain

    def test_custom_domain(self, rng):
        email = gen_email(rng, domain="test.example.com")
        assert email.endswith("@test.example.com")


class TestGenPhone:
    def test_starts_with_plus(self, rng):
        for _ in range(20):
            phone = gen_phone(rng)
            assert phone.startswith("+1-")

    def test_format(self, rng):
        phone = gen_phone(rng)
        # Format: +1-NNN-NNN-NNNN
        assert re.match(r"^\+1-\d{3}-\d{3}-\d{4}$", phone), f"Bad phone format: {phone}"


class TestGenSsn:
    def test_format(self, rng):
        for _ in range(20):
            ssn = gen_ssn(rng)
            assert re.match(r"^\d{3}-\d{2}-\d{4}$", ssn), f"Bad SSN format: {ssn}"


class TestGenUuid:
    def test_format(self, rng):
        for _ in range(10):
            uid = gen_uuid(rng)
            # 8-4-4-4-12 hex pattern
            assert re.match(
                r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$",
                uid,
            ), f"Bad UUID format: {uid}"


class TestGenIpv4:
    def test_format(self, rng):
        for _ in range(20):
            ip = gen_ipv4(rng)
            parts = ip.split(".")
            assert len(parts) == 4
            for p in parts:
                val = int(p)
                assert 1 <= val <= 254


class TestGenDate:
    def test_iso_format(self, rng):
        for _ in range(20):
            d = gen_date(rng)
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", d), f"Bad date format: {d}"

    def test_year_range(self, rng):
        d = gen_date(rng, y_lo=2000, y_hi=2000)
        assert d.startswith("2000-")


class TestGenFullName:
    def test_has_first_and_last(self, rng):
        for _ in range(20):
            name = gen_full_name(rng)
            parts = name.split()
            assert len(parts) == 2
            assert parts[0][0].isupper()
            assert parts[1][0].isupper()


class TestGenMaskedPan:
    def test_format(self, rng):
        for _ in range(10):
            masked = gen_masked_pan(rng)
            assert re.match(r"^\d{6}\*{6}\d{4}$", masked), f"Bad masked PAN: {masked}"


class TestGenAddress:
    def test_contains_city_state_zip(self, rng):
        for _ in range(10):
            addr = gen_full_address(rng)
            assert ", USA" in addr
            parts = addr.split(",")
            assert len(parts) >= 3


class TestGenSalary:
    def test_format(self, rng):
        for _ in range(20):
            sal = gen_salary(rng)
            assert sal.startswith("$")
            assert sal.endswith("/year")
            # Middle portion should be a formatted number
            amount_str = sal[1:].split("/")[0].replace(",", "")
            assert amount_str.isdigit()


class TestGenTimestamp:
    def test_iso_format(self, rng):
        ts = gen_timestamp(rng)
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", ts
        ), f"Bad timestamp: {ts}"


class TestGenMacAddress:
    def test_format(self, rng):
        for _ in range(10):
            mac = gen_mac_address(rng)
            assert re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", mac), f"Bad MAC: {mac}"


class TestGenSessionId:
    def test_prefix(self, rng):
        sid = gen_session_id(rng)
        assert sid.startswith("sess_")
        assert len(sid) == 5 + 24  # "sess_" + 24 chars


class TestGenPassport:
    def test_is_9_digits(self, rng):
        for _ in range(10):
            p = gen_passport(rng)
            assert p.isdigit()
            assert len(p) == 9


class TestGenSerial:
    def test_length_and_chars(self, rng):
        s = gen_serial(rng)
        assert len(s) == 12
        assert re.match(r"^[A-Z0-9]{12}$", s)


class TestGenPostalCode:
    def test_5_digits(self, rng):
        for _ in range(10):
            pc = gen_postal_code(rng)
            assert pc.isdigit()
            assert len(pc) == 5


class TestGenDriversLicense:
    def test_format(self, rng):
        for _ in range(10):
            dl = gen_drivers_license(rng)
            assert re.match(r"^(DL|D|S|L)\d{7}$", dl), f"Bad DL: {dl}"


class TestGenPaypalId:
    def test_prefix(self, rng):
        pid = gen_paypal_id(rng)
        assert pid.startswith("PAYID-")
        assert len(pid) == 6 + 20


class TestGenInvoiceNum:
    def test_format(self, rng):
        inv = gen_invoice_num(rng)
        assert re.match(r"^INV-\d{4}-\d{5}$", inv), f"Bad invoice: {inv}"


class TestGenCreditScore:
    def test_range(self, rng):
        for _ in range(20):
            score = gen_credit_score(rng)
            assert score.isdigit()
            assert 300 <= int(score) <= 850


class TestGenBankAccount:
    def test_length_and_digits(self, rng):
        for _ in range(20):
            acct = gen_bank_account(rng)
            assert acct.isdigit()
            assert 8 <= len(acct) <= 14


class TestGenCvv:
    def test_length(self, rng):
        for _ in range(20):
            cvv = gen_cvv(rng)
            assert cvv.isdigit()
            assert len(cvv) in (3, 4)


# ── Category spec building ───────────────────────────────────────────


class TestBuildCategorySpecs:
    def test_returns_only_leaf_categories(self, small_specs):
        # Non-leaf IDs like "1.1.1.1.1.1" should not appear
        codes = {s.code for s in small_specs}
        # "1.1.1.1.1.1" has children (.1 through .9), so it is not a leaf
        assert "1.1.1.1.1.1" not in codes
        assert "1.1.1.9" not in codes  # has children .1, .3, .4

    def test_all_specs_have_callable_generator(self, small_specs):
        for spec in small_specs:
            assert callable(spec.generator), f"spec {spec.code} generator not callable"

    def test_generators_produce_output(self, small_specs, rng):
        for spec in small_specs:
            value = spec.generator(rng)
            assert isinstance(value, str)
            assert len(value) > 0

    def test_leaf_categories_present(self, small_specs):
        codes = {s.code for s in small_specs}
        # These are leaf nodes in our fixture
        expected_leaves = {
            "1.1.1.1.1.1.1",  # Credit Card Number
            "1.1.1.1.1.1.2",  # CVV
            "1.1.1.1.1.1.3",  # Magnetic Stripe
            "1.1.1.9.1",      # Full Name
            "1.1.1.9.3.1",    # Email Address
            "1.1.1.9.4.1",    # Personal Phone
            "1.1.2.1.2.1.3",  # SSN
            "1.1.1.4.1.1",    # Home Address
            "1.1.1.4.4",      # IP Address
            "1.1.1.2.1.1",    # Salary
        }
        for code in expected_leaves:
            assert code in codes, f"Expected leaf {code} not in specs"

    def test_spec_fields_populated(self, small_specs):
        for spec in small_specs:
            assert spec.code, "code must be set"
            assert spec.label, "label (ontology) must be set"


# ── Column generation ────────────────────────────────────────────────


class TestGenerateColumns:
    def test_produces_expected_column_count(self, small_specs):
        variants = 4
        columns, gt = generate_columns(small_specs, variants_per_category=variants,
                                        rows_per_column=10, seed=42)
        expected_total = len(small_specs) * variants
        assert len(columns) == expected_total
        assert len(gt) == expected_total

    def test_ground_truth_covers_all_categories(self, small_specs):
        columns, gt = generate_columns(small_specs, variants_per_category=6,
                                        rows_per_column=5, seed=99)
        gt_codes = set(gt.values())
        spec_codes = {s.code for s in small_specs}
        assert gt_codes == spec_codes, (
            f"Missing: {spec_codes - gt_codes}, Extra: {gt_codes - spec_codes}"
        )

    def test_each_column_has_expected_rows(self, small_specs):
        n_rows = 25
        columns, _ = generate_columns(small_specs, variants_per_category=4,
                                       rows_per_column=n_rows, seed=7)
        for col_name, values in columns.items():
            assert len(values) == n_rows, f"Column {col_name} has {len(values)} rows, expected {n_rows}"

    def test_column_names_are_unique(self, small_specs):
        columns, _ = generate_columns(small_specs, variants_per_category=30,
                                       rows_per_column=5, seed=1)
        assert len(columns) == len(set(columns.keys()))

    def test_semantic_and_opaque_split(self, small_specs):
        # With 4 variants: 2 semantic + 2 opaque per category
        variants = 4
        columns, gt = generate_columns(small_specs, variants_per_category=variants,
                                        rows_per_column=5, seed=42)
        # We cannot easily distinguish semantic vs opaque names externally,
        # but we can verify the total count is correct
        assert len(columns) == len(small_specs) * variants


# ── Output writing ───────────────────────────────────────────────────


class TestWriteOutput:
    def test_creates_csv_and_ground_truth(self, tmp_path: Path, annotations_csv: Path):
        columns = {
            "col_a": ["v1", "v2", "v3"],
            "col_b": ["v4", "v5", "v6"],
        }
        gt = {"col_a": "1.1.1", "col_b": "1.1.2"}
        output_dir = tmp_path / "out"

        write_output(columns, gt, output_dir, annotations_csv, columns_per_file=50)

        assert output_dir.exists()
        assert (output_dir / "synth_001.csv").exists()
        assert (output_dir / "ground_truth.json").exists()
        assert (output_dir / "annotations.csv").exists()

    def test_csv_has_correct_headers_and_rows(self, tmp_path: Path, annotations_csv: Path):
        columns = {
            "alpha": ["a1", "a2"],
            "beta": ["b1", "b2"],
        }
        gt = {"alpha": "1.0", "beta": "2.0"}
        output_dir = tmp_path / "out"

        write_output(columns, gt, output_dir, annotations_csv, columns_per_file=50)

        csv_path = output_dir / "synth_001.csv"
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Header row should have table.column format
        assert rows[0] == ["synth_001.alpha", "synth_001.beta"]
        # Data rows
        assert rows[1] == ["a1", "b1"]
        assert rows[2] == ["a2", "b2"]

    def test_splits_into_multiple_files(self, tmp_path: Path, annotations_csv: Path):
        # 5 columns with columns_per_file=2 => 3 CSV files
        columns = {f"c{i}": [f"v{i}"] for i in range(5)}
        gt = {f"c{i}": f"1.{i}" for i in range(5)}
        output_dir = tmp_path / "out"

        write_output(columns, gt, output_dir, annotations_csv, columns_per_file=2)

        assert (output_dir / "synth_001.csv").exists()
        assert (output_dir / "synth_002.csv").exists()
        assert (output_dir / "synth_003.csv").exists()
        assert not (output_dir / "synth_004.csv").exists()

    def test_ground_truth_json_structure(self, tmp_path: Path, annotations_csv: Path):
        columns = {"x": ["1"], "y": ["2"]}
        gt = {"x": "1.1", "y": "1.2"}
        output_dir = tmp_path / "out"

        write_output(columns, gt, output_dir, annotations_csv)

        gt_path = output_dir / "ground_truth.json"
        with open(gt_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "mappings" in data
        assert data["mappings"]["x"] == "1.1"
        assert data["mappings"]["y"] == "1.2"

    def test_copies_annotations_csv(self, tmp_path: Path, annotations_csv: Path):
        columns = {"z": ["val"]}
        gt = {"z": "1.0"}
        output_dir = tmp_path / "out"

        write_output(columns, gt, output_dir, annotations_csv)

        copied = output_dir / "annotations.csv"
        assert copied.exists()
        assert copied.read_text(encoding="utf-8") == annotations_csv.read_text(encoding="utf-8")

    def test_missing_annotations_does_not_crash(self, tmp_path: Path):
        columns = {"z": ["val"]}
        gt = {"z": "1.0"}
        output_dir = tmp_path / "out"
        fake_ann = tmp_path / "nonexistent.csv"

        # Should not raise
        write_output(columns, gt, output_dir, fake_ann)

        assert (output_dir / "ground_truth.json").exists()
        assert not (output_dir / "annotations.csv").exists()
