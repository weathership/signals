#!/usr/bin/env python3
"""Bootstrap classification for novel tables without ground truth.

Uses an LLM-driven outer loop to classify columns from novel metadata,
converging via DST conflict K as a disagreement signal between LLM and
ML pipeline predictions.

Output: a ground truth JSON file compatible with --ground-truth / --self-train.

Usage:
    # Bootstrap with Claude (default)
    uv run python scripts/bootstrap_classify.py \
        --data-dir ~/data/novel_tables/ \
        --taxonomy sigdg --threshold 0.25 \
        --output build/bootstrap_gt.json

    # Bootstrap with local Devstral via vLLM (air-gap)
    uv run python scripts/bootstrap_classify.py \
        --data-dir ~/data/novel_tables/ \
        --taxonomy sigdg --threshold 0.25 \
        --llm-backend openai_compatible \
        --llm-base-url http://localhost:8000/v1 \
        --llm-model devstral-small-2 \
        --output build/bootstrap_gt.json

    # Then: self-training with bootstrap output
    uv run python scripts/build_sigint_embeddings.py \
        --data-dir ~/data/novel_tables/ \
        --ground-truth build/bootstrap_gt.json \
        --self-train --auto-generate \
        --output build/sigint_final.parquet
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from sigint.config import load_config


def _build_category_table(category_set) -> str:
    """Build markdown table of leaf categories for LLM system prompt."""
    lines = ["| Code | Label | Description |", "|------|-------|-------------|"]
    for cat in category_set.categories:
        desc = getattr(cat, "description", "") or ""
        lines.append(f"| {cat.code} | {cat.label} | {desc} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Bootstrap classification for novel tables (LLM outer loop)",
    )
    p.add_argument("--data-dir", required=True, help="Path to data directory (CSV/parquet)")
    p.add_argument("--output", default=None, help="Output ground truth JSON")
    p.add_argument(
        "--taxonomy", default=None, choices=["sigdg", "annotations"],
        help="Taxonomy name (default: from config)",
    )
    p.add_argument("--threshold", type=float, default=None, help="Confidence threshold")
    p.add_argument(
        "--input-format", default=None, choices=["csv", "parquet"],
        help="Input file format (default: from config)",
    )

    # LLM backend
    p.add_argument(
        "--llm-backend", default=None,
        choices=["anthropic", "openai_compatible", "cerebras"],
        help="LLM backend (default: from config)",
    )
    p.add_argument("--llm-base-url", default=None, help="Base URL for OpenAI-compatible backend")
    p.add_argument("--llm-model", default=None, help="LLM model name")
    p.add_argument("--api-key", default=None, help="API key for LLM backend")

    # Bootstrap tuning
    p.add_argument("--max-iterations", type=int, default=None, help="Max convergence iterations")
    p.add_argument("--k-threshold", type=float, default=None, help="DST K threshold for LLM revisit")
    p.add_argument("--coverage-target", type=float, default=None, help="Target label coverage")
    p.add_argument("--max-llm-calls", type=int, default=None, help="Max total LLM API calls")
    p.add_argument("--columns-per-call", type=int, default=None, help="Columns per LLM batch call")

    # Data elements
    p.add_argument("--data-elements", action="store_true", help="Enable data element discovery")
    p.add_argument("--de-output", default=None, help="Output path for data elements JSON")

    # Embedding
    p.add_argument("--embedding-model", default="all-MiniLM-L6-v2", help="Sentence-transformer model")
    p.add_argument("--no-name-boost", action="store_true", help="Disable name-match boost")

    args = p.parse_args(argv)

    # ── Load config ──────────────────────────────────────────────
    overrides = {}
    if args.taxonomy:
        overrides["taxonomy_name"] = args.taxonomy
    if args.threshold is not None:
        overrides["confidence_threshold"] = args.threshold
    if args.input_format:
        overrides["input_format"] = args.input_format
    if args.output:
        overrides["bootstrap_output"] = args.output
    if args.llm_backend:
        overrides["bootstrap_llm_backend"] = args.llm_backend
    if args.llm_base_url:
        overrides["bootstrap_llm_base_url"] = args.llm_base_url
    if args.llm_model:
        overrides["bootstrap_llm_model"] = args.llm_model
    if args.api_key:
        overrides["bootstrap_llm_api_key"] = args.api_key
    if args.max_iterations is not None:
        overrides["bootstrap_max_iterations"] = args.max_iterations
    if args.k_threshold is not None:
        overrides["bootstrap_k_threshold"] = args.k_threshold
    if args.coverage_target is not None:
        overrides["bootstrap_coverage_target"] = args.coverage_target
    if args.max_llm_calls is not None:
        overrides["bootstrap_max_total_llm_calls"] = args.max_llm_calls
    if args.columns_per_call is not None:
        overrides["bootstrap_columns_per_call"] = args.columns_per_call

    cfg = load_config(overrides=overrides)

    # ── Backfill args from config ────────────────────────────────
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: data directory not found: {data_dir}", file=sys.stderr)
        return 1

    # ── Load data ────────────────────────────────────────────────
    print(f"Loading data from {data_dir} ...")
    from sigint.csv_loader import load_csv_columns, load_parquet_columns, group_by_table

    input_format = cfg.input_format
    if input_format == "parquet":
        records = load_parquet_columns(data_dir)
    else:
        records = load_csv_columns(data_dir)

    if not records:
        print("Error: no columns found in data directory", file=sys.stderr)
        return 1

    print(f"  {len(records)} columns loaded")

    # ── Build taxonomy and classifier ────────────────────────────
    category_set = cfg.build_category_set()
    category_table = _build_category_table(category_set)

    from sigint.embedding_classifier import EmbeddingClassifier, EmbeddingClassifierConfig
    from sigint.sampler import ColumnSample

    ecfg = EmbeddingClassifierConfig(
        model_name=args.embedding_model,
        confidence_threshold=cfg.confidence_threshold,
        name_match_boost=not args.no_name_boost,
    )
    classifier = EmbeddingClassifier(ecfg, category_set=category_set)

    # ── Build samples and siblings ───────────────────────────────
    tables = group_by_table(records)
    samples: dict[str, ColumnSample] = {}
    siblings_map: dict[str, list[ColumnSample]] = {}
    column_names: list[str] = []
    embeddings: dict[str, any] = {}

    print("Extracting features and computing embeddings ...")
    import numpy as np

    model = classifier._get_model()

    for rec in records:
        name = rec["column_name"]
        column_names.append(name)
        sample = ColumnSample(
            column_name=name,
            column_type=rec.get("column_type", "STRING"),
            values=rec.get("sample_values", []),
        )
        samples[name] = sample

        # Compute embedding for propagation
        from sigint.embedding_classifier import build_embedding_text
        text = build_embedding_text(sample, include_values=True)
        emb = model.encode([text], batch_size=1)[0]
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        embeddings[name] = emb

    # Build siblings map and column→table mapping
    column_table: dict[str, str] = {}
    for table_name, table_records in tables.items():
        table_samples = [samples[r["column_name"]] for r in table_records if r["column_name"] in samples]
        for rec in table_records:
            name = rec["column_name"]
            if name in samples:
                siblings_map[name] = table_samples
                column_table[name] = table_name

    # ── Data element discovery ────────────────────────────────────
    data_elements = None
    if args.data_elements:
        from sigint.schema_discovery import discover_elements
        data_elements = discover_elements(tables)
        if data_elements.elements:
            print(f"  Discovered {len(data_elements.elements)} data elements:")
            for de in data_elements.elements:
                print(f"    - {de.name} ({de.domain}): {len(de.members)} columns across {len(de.tables)} tables")
        else:
            print("  No data elements discovered from naming patterns")

    # ── Configure LLM backend ───────────────────────────────────
    from sigint.llm_backend import LLMBackendConfig, create_backend

    backend_cfg = LLMBackendConfig(
        backend=cfg.bootstrap_llm_backend,
        api_key=args.api_key or cfg.bootstrap_llm_api_key or cfg.anthropic_api_key,
        model=cfg.bootstrap_llm_model,
        base_url=cfg.bootstrap_llm_base_url,
        max_tokens=cfg.bootstrap_llm_max_tokens,
        batch_size=cfg.bootstrap_columns_per_call,
    )
    backend = create_backend(backend_cfg)

    print(f"LLM backend: {cfg.bootstrap_llm_backend} (model={backend._config.model}, max_tokens={backend._config.max_tokens})")

    # Health check
    if not backend.health_check():
        print("Warning: LLM backend health check failed — proceeding anyway",
              file=sys.stderr)

    # ── Configure bootstrap agent ────────────────────────────────
    from sigint.bootstrap_agent import BootstrapAgent, BootstrapConfig

    bootstrap_cfg = BootstrapConfig(
        max_iterations=cfg.bootstrap_max_iterations,
        k_threshold=cfg.bootstrap_k_threshold,
        uncertainty_gap_threshold=cfg.bootstrap_uncertainty_gap_threshold,
        coverage_target=cfg.bootstrap_coverage_target,
        confidence_floor=cfg.bootstrap_confidence_floor,
        initial_sample_fraction=cfg.bootstrap_initial_sample_fraction,
        propagation_similarity_threshold=cfg.bootstrap_propagation_similarity,
        max_llm_calls_per_iteration=cfg.bootstrap_max_llm_calls_per_iteration,
        max_total_llm_calls=cfg.bootstrap_max_total_llm_calls,
        columns_per_call=cfg.bootstrap_columns_per_call,
        output_path=cfg.bootstrap_output,
        llm_discount=cfg.bootstrap_llm_discount,
    )

    agent = BootstrapAgent(
        config=bootstrap_cfg,
        llm_backend=backend,
        embedding_classifier=classifier,
        category_set=category_set,
        column_names=column_names,
        samples=samples,
        siblings_map=siblings_map,
        category_table=category_table,
        embeddings=embeddings,
        column_table=column_table if cfg.bootstrap_table_aware_batching else None,
        data_elements=data_elements,
    )

    # ── Run bootstrap loop ───────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"\n[{ts}] Starting bootstrap classification ...")
    print(f"  Columns: {len(column_names)}")
    print(f"  Max iterations: {bootstrap_cfg.max_iterations}")
    print(f"  K threshold: {bootstrap_cfg.k_threshold}")
    print(f"  Coverage target: {bootstrap_cfg.coverage_target:.0%}")
    print(f"  Max LLM calls: {bootstrap_cfg.max_total_llm_calls}")
    print()

    result = agent.run(progress_callback=lambda msg: print(msg))

    # ── Write output ─────────────────────────────────────────────
    output_path = agent.write_ground_truth(result)

    print(f"\n{'='*60}")
    print(f"Bootstrap complete")
    print(f"  Converged: {result.converged}")
    print(f"  Iterations: {result.iterations}")
    print(f"  Coverage: {result.final_coverage:.1%}")
    print(f"  Mean K: {result.final_mean_k:.3f}")
    print(f"  LLM calls: {result.llm_calls}")
    print(f"  Tokens: {result.tokens_input:,} in / {result.tokens_output:,} out")
    print(f"  Ground truth: {output_path} ({len(result.ground_truth)} columns)")

    # Source breakdown
    sources = {}
    for source in result.source_map.values():
        sources[source] = sources.get(source, 0) + 1
    if sources:
        parts = [f"{k}={v}" for k, v in sorted(sources.items())]
        print(f"  Sources: {', '.join(parts)}")

    # ── Data element refinement and output ────────────────────────
    if args.data_elements and data_elements is not None:
        from sigint.schema_discovery import refine_elements
        data_elements = refine_elements(data_elements, result.ground_truth, tables)
        de_path = Path(args.de_output or "build/data_elements.json")
        data_elements.write(de_path)
        print(f"  Data elements: {de_path} ({len(data_elements.elements)} elements)")

    print(f"\nNext step:")
    print(f"  uv run python scripts/build_sigint_embeddings.py \\")
    print(f"      --data-dir {data_dir} \\")
    print(f"      --ground-truth {output_path} \\")
    print(f"      --self-train --auto-generate \\")
    print(f"      --output build/sigint_final.parquet")

    return 0


if __name__ == "__main__":
    sys.exit(main())
