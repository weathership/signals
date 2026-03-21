"""Tests for HierarchicalCategorySet and hierarchical factory functions."""

from __future__ import annotations

from sigint.category_set import (
    CategorySet,
    HierarchicalCategorySet,
    ReferenceCategory,
    annotation_category_set,
    sigdg_category_set,
)


class TestSigdgHierarchical:
    def test_preserves_leaves(self):
        """Leaf count is unchanged between flat and hierarchical."""
        flat = sigdg_category_set(hierarchical=False)
        hier = sigdg_category_set(hierarchical=True)
        assert len(hier.categories) == len(flat.categories)

    def test_all_categories_includes_parents(self):
        """all_categories includes parent nodes not in .categories."""
        hier = sigdg_category_set(hierarchical=True)
        assert isinstance(hier, HierarchicalCategorySet)
        # SIGDG has 42 total nodes (from ontology.py CATEGORIES tuple)
        from sigint.ontology import CATEGORIES
        assert len(hier.all_categories) == len(CATEGORIES)
        # all_categories > leaves
        assert len(hier.all_categories) > len(hier.categories)

    def test_children_map(self):
        """IdentityInformation (0010) has children: 0011, 0012, 0013."""
        hier = sigdg_category_set(hierarchical=True)
        children_of_0010 = set(hier.children.get("0010", []))
        assert "0011" in children_of_0010
        assert "0012" in children_of_0010
        assert "0013" in children_of_0010

    def test_descendants_returns_leaves(self):
        """PersonalInformation (0020) descendants include PaymentCardData (0070)."""
        hier = sigdg_category_set(hierarchical=True)
        desc = hier.descendants("0020")
        # PaymentCardData is under Personal > Financial > Payment
        assert "0070" in desc
        # All descendants should be leaf codes
        assert desc.issubset(hier.leaf_codes)

    def test_ancestors(self):
        """TaxIdentifier (0085) → [0011, 0010, 0001]."""
        hier = sigdg_category_set(hierarchical=True)
        anc = hier.ancestors("0085")
        assert anc == ["0011", "0010", "0001"]

    def test_backward_compatible_isinstance(self):
        """HierarchicalCategorySet is a CategorySet."""
        hier = sigdg_category_set(hierarchical=True)
        assert isinstance(hier, CategorySet)

    def test_leaf_codes_are_correct(self):
        """leaf_codes matches the flat category set's codes."""
        flat = sigdg_category_set(hierarchical=False)
        hier = sigdg_category_set(hierarchical=True)
        flat_codes = frozenset(c.code for c in flat.categories)
        assert hier.leaf_codes == flat_codes

    def test_all_by_code_lookup(self):
        """Can look up any node by code."""
        hier = sigdg_category_set(hierarchical=True)
        root = hier.all_by_code.get("0001")
        assert root is not None
        assert root.label == "InformationEntity"
        leaf = hier.all_by_code.get("0085")
        assert leaf is not None
        assert leaf.label == "TaxIdentifier"

    def test_parent_map(self):
        """parent[code] returns correct parent_code."""
        hier = sigdg_category_set(hierarchical=True)
        assert hier.parent["0085"] == "0011"
        assert hier.parent["0001"] is None

    def test_descendants_of_leaf_is_singleton(self):
        """Descendants of a leaf is just that leaf."""
        hier = sigdg_category_set(hierarchical=True)
        desc = hier.descendants("0085")
        assert desc == frozenset({"0085"})


class TestAnnotationHierarchical:
    def _make_csv(self, tmp_path):
        ann_csv = tmp_path / "annotations.csv"
        ann_csv.write_text(
            'ID,Ontology,Annotation,Definition,Common Names,"Specifics, Examples and/or Additional Context",Deprecated\n'
            '1.1,Personally Identifiable Data,C_PID,Aggregated PII data,,test,no\n'
            '1.1.1,Personal Data,C_PD,Personal data elements,,test,no\n'
            '1.1.1.1,Financial Data,C_FD,Financial data elements,,test,no\n'
            '1.1.1.1.1,Payment Data,C_BD,Payment data elements,,test,no\n'
            '1.1.1.1.1.1,Payment Card Data,C_PCD,Payment card elements,,test,no\n'
            '1.1.1.1.1.1.1,Payment Card Number,PAN,The number on a credit card,Credit Card,examples,no\n'
            '1.1.1.1.1.1.2,Card Verification Value,CVV2,CVV 3 or 4 digits,CVV,,no\n'
        )
        return ann_csv

    def test_annotation_hierarchical_tree(self, tmp_path):
        """Annotation hierarchical set builds tree from dot notation."""
        ann_csv = self._make_csv(tmp_path)
        hier = annotation_category_set(ann_csv, hierarchical=True)
        assert isinstance(hier, HierarchicalCategorySet)

        # Leaves should be the same as flat
        flat = annotation_category_set(ann_csv, hierarchical=False)
        leaf_codes = {c.code for c in hier.categories}
        flat_codes = {c.code for c in flat.categories}
        assert leaf_codes == flat_codes

    def test_annotation_parent_codes(self, tmp_path):
        """Parent nodes are present in all_categories."""
        ann_csv = self._make_csv(tmp_path)
        hier = annotation_category_set(ann_csv, hierarchical=True)
        all_codes = {c.code for c in hier.all_categories}
        # Parents from CSV
        assert "1.1" in all_codes
        assert "1.1.1" in all_codes
        assert "1.1.1.1.1.1" in all_codes

    def test_annotation_ancestors(self, tmp_path):
        """PAN (1.1.1.1.1.1.1) has correct ancestor path."""
        ann_csv = self._make_csv(tmp_path)
        hier = annotation_category_set(ann_csv, hierarchical=True)
        anc = hier.ancestors("1.1.1.1.1.1.1")
        assert "1.1.1.1.1.1" in anc
        assert "1.1" in anc

    def test_annotation_children(self, tmp_path):
        """Payment Card Data (1.1.1.1.1.1) has children PAN and CVV2."""
        ann_csv = self._make_csv(tmp_path)
        hier = annotation_category_set(ann_csv, hierarchical=True)
        children = set(hier.children.get("1.1.1.1.1.1", []))
        assert "1.1.1.1.1.1.1" in children
        assert "1.1.1.1.1.1.2" in children

    def test_flat_annotation_unchanged(self, tmp_path):
        """Flat annotation_category_set still returns plain CategorySet."""
        ann_csv = self._make_csv(tmp_path)
        flat = annotation_category_set(ann_csv, hierarchical=False)
        assert isinstance(flat, CategorySet)
        assert not isinstance(flat, HierarchicalCategorySet)

    def test_parent_code_on_leaf_refs(self, tmp_path):
        """Leaf ReferenceCategory nodes have parent_code set."""
        ann_csv = self._make_csv(tmp_path)
        hier = annotation_category_set(ann_csv, hierarchical=True)
        pan = hier.by_code.get("1.1.1.1.1.1.1")
        assert pan is not None
        assert pan.parent_code == "1.1.1.1.1.1"
