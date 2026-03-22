"""sigint — SIGDG column tagging service for Signals 360."""

__version__ = "0.1.0"

from sigint.classifier import Classification, Classifier, HierarchicalClassification
from sigint.config import PipelineConfig, TaggingConfig, load_config
from sigint.ontology import CATEGORIES, SENSITIVITY_LEVELS, Category, SensitivityLevel

__all__ = [
    "CATEGORIES",
    "Category",
    "Classification",
    "Classifier",
    "HierarchicalClassification",
    "PipelineConfig",
    "SENSITIVITY_LEVELS",
    "SensitivityLevel",
    "TaggingConfig",
    "load_config",
]
