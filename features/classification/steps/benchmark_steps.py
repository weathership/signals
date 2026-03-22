"""Step definitions for benchmark_gittables.feature."""

import json
from pathlib import Path

from behave import given, then, when

from features.classification.steps.helpers import make_classifier, make_sample

# GitTables dataset path (relative to project root)
_GITTABLES_DIR = "build/datasets/gittables"
_SKIP_MSG = (
    "GitTables dataset not found. Download with:\n"
    "  uv run python scripts/download_gittables_benchmark.py "
    "--output-dir build/datasets/gittables/"
)


def _project_root():
    """Get project root relative to this file."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _gittables_dir():
    return _project_root() / _GITTABLES_DIR


@given("the GitTables taxonomy is loaded with 122 DBpedia types")
def step_load_gittables_taxonomy(context):
    import sys

    taxonomy_path = _project_root() / "config" / "sigint"
    sys.path.insert(0, str(taxonomy_path))
    from gittables_taxonomy import gittables_category_set

    context.gittables_cs = gittables_category_set()


@given("the GitTables benchmark dataset is available")
def step_load_gittables_dataset(context):
    data_dir = _gittables_dir()
    columns_path = data_dir / "gittables_columns.parquet"
    if not columns_path.exists():
        context.scenario.skip(_SKIP_MSG)
        return

    from sigint.csv_loader import load_parquet_columns

    context.gittables_columns = load_parquet_columns(columns_path)


@then("the dataset contains at least {n:d} columns")
def step_dataset_count(context, n):
    assert len(context.gittables_columns) >= n, (
        f"Expected >= {n} columns, got {len(context.gittables_columns)}"
    )


@then("each column has a source_table, column_name, and column_type")
def step_columns_have_fields(context):
    for col in context.gittables_columns[:10]:  # spot check
        assert "source_table" in col, f"Missing source_table: {col.keys()}"
        assert "column_name" in col, f"Missing column_name: {col.keys()}"
        assert "column_type" in col, f"Missing column_type: {col.keys()}"


@given("an EmbeddingClassifier is configured for GitTables")
def step_gittables_classifier(context):
    context.gittables_clf = make_classifier(category_set=context.gittables_cs)


@when("I classify all GitTables columns")
def step_classify_all(context):
    clf = context.gittables_clf
    results = []
    # Classify a subset for speed in BDD (first 50)
    columns = context.gittables_columns[:50]
    for col in columns:
        sample = make_sample(
            col["column_name"],
            col_type=col.get("column_type", "STRING"),
            values=col.get("sample_values", []),
        )
        result = clf.classify(sample)
        results.append((col, result))
    context.gittables_results = results


@then("every classification has a belief interval")
def step_all_have_belief(context):
    for col, result in context.gittables_results:
        if result is None:
            continue
        assert result.belief_assignment is not None, (
            f"Column {col['column_name']} has no belief assignment"
        )


@then("belief <= plausibility for each result")
def step_bel_le_pl(context):
    for col, result in context.gittables_results:
        if result is None:
            continue
        code = result.category.code
        bel = result.belief_at(code)
        pl = result.plausibility_at(code)
        assert bel <= pl + 1e-9, (
            f"Column {col['column_name']}: belief ({bel}) > pl ({pl})"
        )


# ── Ground truth evaluation ──────────────────────────────────────────

@given("the GitTables ground truth mapping is available")
def step_load_gt(context):
    gt_path = _gittables_dir() / "gittables_gt.json"
    if not gt_path.exists():
        context.scenario.skip(f"Ground truth not found: {gt_path}")
        return
    raw = json.loads(gt_path.read_text())
    # GT file may have a top-level "mappings" key
    context.gittables_gt = raw.get("mappings", raw)


@given("all GitTables columns have been classified")
def step_ensure_classified(context):
    if hasattr(context, "gittables_results"):
        return
    # Trigger classification
    step_load_gittables_dataset(context)
    if not hasattr(context, "gittables_columns"):
        return  # skipped
    step_gittables_classifier(context)
    step_classify_all(context)


@when("I evaluate classifications against the ground truth")
def step_evaluate_accuracy(context):
    gt = context.gittables_gt
    correct = 0
    wrong = 0
    total = 0
    for col, result in context.gittables_results:
        # GT keys are "source_table.column_name"
        key = f"{col.get('source_table', '')}.{col['column_name']}"
        gt_label = gt.get(key) or gt.get(col["column_name"])
        if gt_label is None:
            continue
        total += 1
        if result and result.category.label.lower() == gt_label.lower():
            correct += 1
        else:
            wrong += 1
    context.accuracy_metrics = {
        "correct": correct, "wrong": wrong, "total": total,
    }


@then("accuracy is reported with correct, wrong, and total counts")
def step_accuracy_reported(context):
    m = context.accuracy_metrics
    assert m["total"] > 0, "No columns matched ground truth"
    assert "correct" in m and "wrong" in m, f"Missing metrics: {m}"


# ── High uncertainty ─────────────────────────────────────────────────

@then("at least one classification has uncertainty_gap > {threshold:g}")
def step_high_uncertainty(context, threshold):
    found = False
    for _, result in context.gittables_results:
        if result and result.uncertainty_gap > threshold:
            found = True
            break
    assert found, (
        f"No classification had uncertainty_gap > {threshold}"
    )


# ── SAGE ─────────────────────────────────────────────────────────────

@when("I run SAGE analysis with {n:d} permutations on a subset")
def step_sage_analysis(context, n):
    import numpy as np

    from sigint.features import extract_features
    from sigint.sage_analysis import run_sage_analysis

    # Use a small subset for speed
    columns = context.gittables_columns[:20]
    all_features = []
    for col in columns:
        sample = make_sample(
            col["column_name"],
            col_type=col.get("column_type", "STRING"),
            values=col.get("sample_values", []),
        )
        all_features.append(extract_features(sample))

    # Build ground truth indices from classifications (use predicted as proxy)
    cats = list(context.gittables_cs.by_code.keys())
    gt_indices = np.zeros(len(all_features), dtype=int)
    for i, (col, result) in enumerate(context.gittables_results[:20]):
        if result and result.category.code in cats:
            gt_indices[i] = cats.index(result.category.code)

    sage_result = run_sage_analysis(
        all_features=all_features,
        ground_truth_indices=gt_indices,
        classifier=context.gittables_clf,
        category_set=context.gittables_cs,
        n_permutations=n,
    )
    context.sage_result = sage_result


@then("SAGE returns importance values for all 12 features")
def step_sage_12_features(context):
    from sigint.features import FEATURE_NAMES

    assert len(context.sage_result.feature_names) == len(FEATURE_NAMES), (
        f"Expected {len(FEATURE_NAMES)} features, "
        f"got {len(context.sage_result.feature_names)}"
    )
    assert len(context.sage_result.importance_values) == len(FEATURE_NAMES)
