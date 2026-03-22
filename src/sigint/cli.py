"""CLI entry point: ``uv run python -m sigint``."""

from __future__ import annotations

import argparse
import sys

from sigint.config import load_config
from sigint.tagger import Tagger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="sigint",
        description="SIGDG column tagger — classify and tag Impala columns in Atlas",
    )
    p.add_argument(
        "--tables",
        nargs="+",
        required=True,
        help="Fully-qualified table names (db.table)",
    )
    p.add_argument("--database", default=None, help="Default database name")
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Classify but don't write tags to Atlas",
    )
    p.add_argument(
        "--setup-types",
        action="store_true",
        help="Create SIGDG classification types in Atlas and exit",
    )
    # None defaults = fall through to HOCON config
    p.add_argument("--impala-host", default=None, help="Impala host (from config)")
    p.add_argument("--impala-port", type=int, default=None, help="Impala port (from config)")
    p.add_argument("--atlas-url", default=None, help="Atlas URL (from config)")
    p.add_argument(
        "--sample-size", type=int, default=None, help="Values to sample per column (from config)"
    )
    p.add_argument(
        "--sample-strategy",
        choices=["head", "random", "frequent"],
        default=None,
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Minimum confidence threshold (from config)",
    )
    p.add_argument(
        "--classifier-type",
        choices=["llm", "embedding"],
        default=None,
        help="Classification method (from config)",
    )
    p.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (or set ANTHROPIC_API_KEY env)",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Anthropic model for classification (from config)",
    )
    p.add_argument(
        "--annotations",
        default=None,
        help="Path to vocabulary CSV (annotations.csv) for domain context",
    )
    p.add_argument(
        "--embedding-model",
        default=None,
        help="SentenceTransformer model name (from config)",
    )
    p.add_argument(
        "--model-path",
        default=None,
        help="Path to trained CatBoost model (.cbm) for embedding classifier",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Build overrides from explicitly-provided CLI args
    overrides: dict = {}
    if args.impala_host is not None:
        overrides["impala_host"] = args.impala_host
    if args.impala_port is not None:
        overrides["impala_port"] = args.impala_port
    if args.atlas_url is not None:
        overrides["atlas_url"] = args.atlas_url
    if args.sample_size is not None:
        overrides["sample_size"] = args.sample_size
    if args.sample_strategy is not None:
        overrides["sample_strategy"] = args.sample_strategy
    if args.threshold is not None:
        overrides["confidence_threshold"] = args.threshold
    if args.classifier_type is not None:
        overrides["classifier_type"] = args.classifier_type
    if args.api_key is not None:
        overrides["anthropic_api_key"] = args.api_key
    if args.model is not None:
        overrides["anthropic_model"] = args.model
    if args.annotations is not None:
        overrides["annotations_path"] = args.annotations
    if args.embedding_model is not None:
        overrides["embedding_model"] = args.embedding_model
    if args.model_path is not None:
        overrides["model_path"] = args.model_path
    if args.dry_run is not None:
        overrides["dry_run"] = args.dry_run
    if args.tables:
        overrides["tables"] = args.tables

    cfg = load_config(overrides=overrides)
    tc = cfg.to_tagging_config()
    tagger = Tagger(tc)

    try:
        if args.setup_types:
            result = tagger.setup_types()
            print(f"Classification types — created: {result['created']}, "
                  f"existing: {result['existing']}")
            return 0

        report = tagger.run()
        print(report.summary())
        return 0
    finally:
        tagger.close()


if __name__ == "__main__":
    sys.exit(main())
