"""Shared helpers for classification BDD step implementations.

All utilities work in-memory without external services (tier-0 safe).
"""

import json
import tempfile
from pathlib import Path


def make_sample(name, col_type="STRING", values=None, null_count=0, total_count=100):
    """Create a ColumnSample for testing."""
    from sigint.sampler import ColumnSample

    return ColumnSample(
        column_name=name,
        column_type=col_type,
        values=values or [],
        null_count=null_count,
        total_count=total_count,
    )


def make_classifier(category_set=None, threshold=0.3, name_match_boost=True):
    """Create an EmbeddingClassifier for testing (CPU only)."""
    from sigint.embedding_classifier import (
        EmbeddingClassifier,
        EmbeddingClassifierConfig,
    )

    cfg = EmbeddingClassifierConfig(
        confidence_threshold=threshold,
        name_match_boost=name_match_boost,
        device="cpu",
    )
    return EmbeddingClassifier(cfg, category_set=category_set)


def make_temp_annotations_csv(categories):
    """Create a temporary annotations CSV with given categories.

    Args:
        categories: list of dicts with keys: code, label, definition, common_names

    Returns:
        Path to temp file (caller must clean up).
    """
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", prefix="bdd_annotations_", delete=False,
    )
    f.write("ID,Ontology,Annotation,Definition,Common Names\n")
    for cat in categories:
        code = cat["code"]
        label = cat.get("label", cat.get("annotation", ""))
        defn = cat.get("definition", "")
        common = cat.get("common_names", "")
        f.write(f"{code},{label},{label},{defn},{common}\n")
    f.close()
    return f.name


def make_temp_vocab_mapping(entries, source_taxonomy="custom", target_taxonomy="sigdg"):
    """Create a temporary vocabulary mapping JSON file.

    Args:
        entries: list of (user_label, code) tuples

    Returns:
        Path to temp file (caller must clean up).
    """
    mapping = {
        "source_taxonomy": source_taxonomy,
        "target_taxonomy": target_taxonomy,
        "mappings": {label: code for label, code in entries},
    }
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="bdd_vocab_", delete=False,
    )
    json.dump(mapping, f)
    f.close()
    return f.name


def register_temp_file(context, path):
    """Register a temp file for cleanup in after_scenario."""
    if not hasattr(context, "_temp_files"):
        context._temp_files = []
    context._temp_files.append(path)
