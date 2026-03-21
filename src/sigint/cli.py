"""CLI entry point: ``uv run python -m sigint``."""

from __future__ import annotations

import argparse
import sys

from sigint.config import TaggingConfig
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
        help="Classify but don't write tags to Atlas",
    )
    p.add_argument(
        "--setup-types",
        action="store_true",
        help="Create SIGDG classification types in Atlas and exit",
    )
    p.add_argument("--impala-host", default="localhost")
    p.add_argument("--impala-port", type=int, default=21050)
    p.add_argument("--atlas-url", default="http://localhost:21000")
    p.add_argument(
        "--sample-size", type=int, default=50, help="Values to sample per column"
    )
    p.add_argument(
        "--sample-strategy",
        choices=["head", "random", "frequent"],
        default="head",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Minimum confidence threshold",
    )
    # Classifier selection
    p.add_argument(
        "--classifier-type",
        choices=["llm", "embedding"],
        default="llm",
        help="Classification method (default: llm)",
    )
    # LLM classifier options
    p.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (or set ANTHROPIC_API_KEY env)",
    )
    p.add_argument(
        "--model",
        default="claude-opus-4-6",
        help="Anthropic model for classification",
    )
    p.add_argument(
        "--annotations",
        default=None,
        help="Path to vocabulary CSV (annotations.csv) for domain context",
    )
    # Embedding classifier options
    p.add_argument(
        "--embedding-model",
        default="all-MiniLM-L6-v2",
        help="SentenceTransformer model name (default: all-MiniLM-L6-v2)",
    )
    p.add_argument(
        "--model-path",
        default=None,
        help="Path to trained CatBoost model (.cbm) for embedding classifier",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    cfg = TaggingConfig(
        impala_host=args.impala_host,
        impala_port=args.impala_port,
        atlas_url=args.atlas_url,
        sample_size=args.sample_size,
        sample_strategy=args.sample_strategy,
        confidence_threshold=args.threshold,
        classifier_type=args.classifier_type,
        dry_run=args.dry_run,
        tables=args.tables,
        anthropic_api_key=args.api_key,
        anthropic_model=args.model,
        annotations_path=args.annotations,
        embedding_model=args.embedding_model,
        model_path=args.model_path,
    )

    tagger = Tagger(cfg)

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
