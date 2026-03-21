"""Orchestrator: sample → classify → tag."""

from __future__ import annotations

from dataclasses import dataclass, field

from sigint.atlas_client import AtlasClient
from sigint.classifier import Classification, Classifier
from sigint.config import TaggingConfig
from sigint.sampler import ColumnSample, ImpalaSampler, TableSample


def _create_classifier(cfg: TaggingConfig) -> Classifier:
    """Build a classifier from config."""
    if cfg.classifier_type == "llm":
        from sigint.llm_classifier import (
            LLMClassifier,
            LLMClassifierConfig,
            load_annotations,
        )

        vocab = []
        if cfg.annotations_path:
            vocab = load_annotations(cfg.annotations_path)

        llm_cfg = LLMClassifierConfig(
            api_key=cfg.anthropic_api_key,
            model=cfg.anthropic_model,
            annotations_vocabulary=vocab,
        )
        return LLMClassifier(llm_cfg)

    if cfg.classifier_type == "embedding":
        from sigint.embedding_classifier import (
            EmbeddingClassifier,
            EmbeddingClassifierConfig,
        )

        emb_cfg = EmbeddingClassifierConfig(
            model_name=cfg.embedding_model,
            model_path=cfg.model_path,
            confidence_threshold=cfg.confidence_threshold,
            include_values=cfg.embedding_include_values,
        )
        return EmbeddingClassifier(emb_cfg)

    raise ValueError(f"Unknown classifier type: {cfg.classifier_type}")


@dataclass
class TagResult:
    """Result of tagging a single column."""

    table_fqn: str
    column_name: str
    classification: Classification | None
    applied: bool = False
    error: str | None = None


@dataclass
class TagReport:
    """Summary of a tagging run."""

    tables_processed: int = 0
    columns_processed: int = 0
    columns_classified: int = 0
    columns_tagged: int = 0
    results: list[TagResult] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Tables: {self.tables_processed}",
            f"Columns: {self.columns_processed}",
            f"Classified: {self.columns_classified}",
            f"Tagged: {self.columns_tagged}",
        ]
        for r in self.results:
            if r.classification:
                status = "APPLIED" if r.applied else "DRY-RUN"
                if r.error:
                    status = f"ERROR: {r.error}"
                lines.append(
                    f"  {r.table_fqn}.{r.column_name} → "
                    f"{r.classification.category.label} "
                    f"({r.classification.confidence:.2f}) [{status}]"
                )
        return "\n".join(lines)


class Tagger:
    """Orchestrates the sample → classify → tag pipeline."""

    def __init__(self, cfg: TaggingConfig) -> None:
        self._cfg = cfg
        self._sampler = ImpalaSampler(cfg)
        self._classifier = _create_classifier(cfg)
        self._atlas = AtlasClient(cfg)

    def setup_types(self) -> dict:
        """Ensure SIGDG classification types exist in Atlas."""
        return self._atlas.ensure_classification_types()

    def tag_table(self, table_fqn: str, report: TagReport) -> None:
        """Sample, classify, and tag all columns of a table."""
        table_sample = self._sampler.sample_table(table_fqn)
        report.tables_processed += 1

        siblings = table_sample.columns

        for col_sample in table_sample.columns:
            report.columns_processed += 1
            result = TagResult(
                table_fqn=table_fqn,
                column_name=col_sample.column_name,
                classification=None,
            )

            classification = self._classifier.classify(col_sample, siblings)
            result.classification = classification

            if classification:
                report.columns_classified += 1

                if not self._cfg.dry_run:
                    guid = self._atlas.find_column_guid(
                        table_fqn, col_sample.column_name
                    )
                    if guid:
                        ok = self._atlas.apply_classification(
                            guid,
                            classification.atlas_type_name,
                            confidence=classification.confidence,
                            evidence=classification.evidence,
                        )
                        result.applied = ok
                        if ok:
                            report.columns_tagged += 1
                        else:
                            result.error = "Atlas API call failed"
                    else:
                        result.error = "Column entity not found in Atlas"
                else:
                    result.applied = False

            report.results.append(result)

    def run(self) -> TagReport:
        """Run the full tagging pipeline."""
        report = TagReport()

        # Setup classification types (unless dry-run)
        if not self._cfg.dry_run:
            self.setup_types()

        # Process requested tables
        for table_fqn in self._cfg.tables:
            self.tag_table(table_fqn, report)

        return report

    def close(self) -> None:
        self._sampler.close()
