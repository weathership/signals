"""Tests for the SIGDG ontology module."""

from sigint.ontology import (
    CATEGORIES,
    CATEGORY_BY_CODE,
    CATEGORY_BY_LABEL,
    DEFAULT_SENSITIVITY,
    SENSITIVITY_LEVELS,
    atlas_classification_defs,
)


class TestCategories:
    def test_category_count(self):
        assert len(CATEGORIES) == 42

    def test_root_has_no_parent(self):
        root = CATEGORY_BY_CODE["0001"]
        assert root.parent_code is None
        assert root.label == "InformationEntity"

    def test_all_parents_exist(self):
        for cat in CATEGORIES:
            if cat.parent_code is not None:
                assert cat.parent_code in CATEGORY_BY_CODE, (
                    f"{cat.curie} references unknown parent {cat.parent_code}"
                )

    def test_curie_format(self):
        for cat in CATEGORIES:
            assert cat.curie.startswith("SIGDG:")
            assert cat.curie == f"SIGDG:{cat.code}"

    def test_atlas_type_name_no_colons(self):
        for cat in CATEGORIES:
            name = cat.atlas_type_name
            assert ":" not in name
            assert name.startswith("SIGDG_")

    def test_label_lookup(self):
        assert CATEGORY_BY_LABEL["GovernmentIdentifier"].code == "0011"
        assert CATEGORY_BY_LABEL["PaymentInformation"].code == "0022"

    def test_abbrev_field(self):
        assert CATEGORY_BY_CODE["0070"].abbrev == "PCD"
        assert CATEGORY_BY_CODE["0085"].abbrev == "TIN"
        assert CATEGORY_BY_CODE["0076"].abbrev == "EMAIL"
        # Root has no abbrev
        assert CATEGORY_BY_CODE["0001"].abbrev == ""

    def test_new_leaves_exist(self):
        new_codes = [
            "0070", "0071", "0072", "0073", "0074", "0075", "0076",
            "0077", "0078", "0079", "0080", "0081", "0082", "0083",
            "0084", "0085", "0086", "0087", "0088", "0089", "0090", "0091",
        ]
        for code in new_codes:
            assert code in CATEGORY_BY_CODE, f"Missing new leaf {code}"

    def test_unique_codes(self):
        codes = [c.code for c in CATEGORIES]
        assert len(codes) == len(set(codes)), "Duplicate category codes"

    def test_unique_labels(self):
        labels = [c.label for c in CATEGORIES]
        assert len(labels) == len(set(labels)), "Duplicate category labels"


class TestSensitivityLevels:
    def test_four_levels(self):
        assert len(SENSITIVITY_LEVELS) == 4

    def test_ordering(self):
        codes = [s.code for s in SENSITIVITY_LEVELS]
        assert codes == ["1010", "1020", "1030", "1040"]

    def test_labels(self):
        labels = {s.label for s in SENSITIVITY_LEVELS}
        assert labels == {"Public", "Internal", "Confidential", "Restricted"}


class TestDefaultSensitivity:
    def test_all_leaves_have_sensitivity(self):
        leaf_codes = {c.code for c in CATEGORIES} - {
            c.parent_code for c in CATEGORIES if c.parent_code
        }
        for code in leaf_codes:
            assert code in DEFAULT_SENSITIVITY, (
                f"Leaf category {code} missing default sensitivity"
            )

    def test_government_id_leaves_are_restricted(self):
        assert DEFAULT_SENSITIVITY["0083"] == "1040"  # Passport
        assert DEFAULT_SENSITIVITY["0084"] == "1040"  # DriversLicense
        assert DEFAULT_SENSITIVITY["0085"] == "1040"  # TaxIdentifier

    def test_transformation_leaves(self):
        assert DEFAULT_SENSITIVITY["0089"] == "1010"  # Hashing → Public
        assert DEFAULT_SENSITIVITY["0088"] == "1030"  # Encryption → Confidential


class TestAtlasTypeDefs:
    def test_only_leaf_categories(self):
        defs = atlas_classification_defs()
        parent_codes = {c.parent_code for c in CATEGORIES if c.parent_code}
        for d in defs:
            # Extract code from name like SIGDG_0011_GovernmentIdentifier
            code = d["name"].split("_")[1]
            assert code not in parent_codes, (
                f"Non-leaf category {code} should not be a classification def"
            )

    def test_has_confidence_and_evidence(self):
        defs = atlas_classification_defs()
        for d in defs:
            attr_names = {a["name"] for a in d["attributeDefs"]}
            assert "confidence" in attr_names
            assert "evidence" in attr_names

    def test_def_count(self):
        defs = atlas_classification_defs()
        leaf_codes = {c.code for c in CATEGORIES} - {
            c.parent_code for c in CATEGORIES if c.parent_code
        }
        assert len(defs) == len(leaf_codes)
