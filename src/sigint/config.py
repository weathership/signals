"""Configuration dataclass for the tagging service."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaggingConfig:
    """All knobs for the sample → classify → tag pipeline."""

    # Impala connection
    impala_host: str = "localhost"
    impala_port: int = 21050

    # Atlas connection
    atlas_url: str = "http://localhost:21000"
    atlas_user: str = "admin"
    atlas_password: str = "admin"

    # Cluster name for qualified names
    cluster_name: str = "signals"

    # Sampling
    sample_size: int = 50
    sample_strategy: str = "head"  # head | random | frequent

    # Classification
    classifier_type: str = "llm"  # "llm" | "embedding"
    confidence_threshold: float = 0.5
    anthropic_api_key: str | None = None  # or ANTHROPIC_API_KEY env
    anthropic_model: str = "claude-opus-4-6"
    annotations_path: str | None = None  # path to vocabulary CSV

    # Embedding classifier
    embedding_model: str = "all-MiniLM-L6-v2"
    xgboost_model_path: str | None = None
    embedding_include_values: bool = True

    # Databases / tables to process
    databases: list[str] = field(default_factory=lambda: ["default"])
    tables: list[str] = field(default_factory=list)

    # Dry-run mode — classify but don't write to Atlas
    dry_run: bool = False
