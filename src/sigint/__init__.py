"""sigint — SIGDG column tagging service for Signals 360."""

__version__ = "0.1.0"

from sigint.classifier import Classification, Classifier
from sigint.config import TaggingConfig
from sigint.ontology import CATEGORIES, SENSITIVITY_LEVELS, Category, SensitivityLevel

__all__ = [
    "CATEGORIES",
    "Category",
    "Classification",
    "Classifier",
    "SENSITIVITY_LEVELS",
    "SensitivityLevel",
    "TaggingConfig",
]
