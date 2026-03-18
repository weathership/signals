"""Tests for OWL serialization of the SIGDG ontology."""

from pathlib import Path

from sigint.ontology import CATEGORIES, SENSITIVITY_LEVELS
from sigint.owl import ONTOLOGY_IRI, serialize_owl


class TestSerializeOwl:
    def test_creates_file(self, tmp_path):
        out = tmp_path / "sigdg.owl"
        result = serialize_owl(out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_output_is_rdfxml(self, tmp_path):
        out = tmp_path / "sigdg.owl"
        serialize_owl(out)
        content = out.read_text()
        assert '<?xml version="1.0"?>' in content
        assert "rdf:RDF" in content

    def test_contains_category_iris(self, tmp_path):
        out = tmp_path / "sigdg.owl"
        serialize_owl(out)
        content = out.read_text()

        # Spot-check key categories exist as class IRIs
        for label in ["InformationEntity", "TaxIdentifier", "PaymentCardData",
                       "EmailAddress", "Anonymization"]:
            assert label in content, f"Missing category {label} in OWL output"

    def test_contains_sensitivity_levels(self, tmp_path):
        out = tmp_path / "sigdg.owl"
        serialize_owl(out)
        content = out.read_text()

        for sl in SENSITIVITY_LEVELS:
            assert sl.label in content, f"Missing sensitivity {sl.label}"

    def test_contains_bfo_anchors(self, tmp_path):
        out = tmp_path / "sigdg.owl"
        serialize_owl(out)
        content = out.read_text()
        assert "BFO_0000031" in content
        assert "BFO_0000019" in content

    def test_roundtrip_owlready2(self, tmp_path):
        """Generate OWL, reload it, and verify class count."""
        from owlready2 import default_world, get_ontology

        out = tmp_path / "sigdg.owl"
        serialize_owl(out)

        # Clear and reload
        default_world.ontologies.clear()
        onto = get_ontology(str(out)).load()
        classes = list(onto.classes())

        # 42 SIGDG categories + 4 sensitivity levels + 2 BFO anchors = 48
        expected = len(CATEGORIES) + len(SENSITIVITY_LEVELS) + 2
        assert len(classes) >= expected, (
            f"Expected >= {expected} classes, got {len(classes)}"
        )

    def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "sub" / "dir" / "sigdg.owl"
        serialize_owl(out)
        assert out.exists()

    def test_idempotent(self, tmp_path):
        """Calling twice doesn't error."""
        out = tmp_path / "sigdg.owl"
        serialize_owl(out)
        serialize_owl(out)
        assert out.exists()
