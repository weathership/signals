"""Embedding-based column classifier using sentence-transformers.

Uses Dempster-Shafer evidence fusion to combine cosine similarity,
CatBoost probabilities, pattern signals, and name-match evidence
into belief intervals.  Returns ``HierarchicalClassification`` with
uncertainty-aware belief/plausibility metrics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sigint.category_set import CategorySet, HierarchicalCategorySet, sigdg_category_set
from sigint.classifier import HierarchicalClassification
from sigint.features import ColumnFeatures
from sigint.ontology import CATEGORIES, DEFAULT_SENSITIVITY
from sigint.sampler import ColumnSample


def _detect_device() -> str:
    """Return 'cuda' if a CUDA GPU is available, else 'cpu'."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


@dataclass
class EmbeddingClassifierConfig:
    """Configuration for the embedding classifier."""

    model_name: str = "all-MiniLM-L6-v2"
    model_path: str | None = None
    cache_dir: str | None = None  # local model cache (air-gap safe)
    confidence_threshold: float = 0.3
    include_values: bool = True
    max_values: int = 5
    batch_size: int = 32
    name_match_boost: bool = True
    device: str = "auto"  # "auto", "cuda", "cuda:0", "cpu"



def _camel_to_words(name: str) -> str:
    """Split CamelCase into lowercase words: 'PaymentCardData' → 'payment card data'."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).lower()


def build_embedding_text(
    sample: ColumnSample,
    siblings: list[ColumnSample] | None = None,
    include_values: bool = True,
    max_values: int = 5,
    *,
    features: ColumnFeatures | None = None,
    feature_mask: dict[str, bool] | None = None,
) -> str:
    """Build a text string for embedding from a ColumnSample.

    When *features* is provided, delegates to ``features.to_embedding_text(mask)``
    for discrete, ablatable feature construction.  Otherwise falls back to the
    original ``name | type | values`` format.

    Args:
        features: Pre-extracted ColumnFeatures.  When set, *include_values* and
            *max_values* are ignored in favour of the feature mask.
        feature_mask: Feature ablation mask passed to ``to_embedding_text()``.
    """
    if features is not None:
        return features.to_embedding_text(feature_mask)

    name_text = sample.column_name.replace("_", " ")
    parts = [name_text]

    if sample.column_type and sample.column_type.upper() not in ("STRING", "VARCHAR"):
        parts.append(sample.column_type.lower())

    if include_values and sample.values:
        parts.append(", ".join(v[:80] for v in sample.values[:max_values]))

    return " | ".join(parts)


def _build_category_text(cat) -> str:
    """Build embedding text for a SIGDG leaf category."""
    label_words = _camel_to_words(cat.label)
    parts = [label_words]
    if cat.abbrev:
        parts.append(cat.abbrev)
    if cat.description:
        parts.append(cat.description)
    return " | ".join(parts)


def _get_leaf_categories() -> list:
    """Return only leaf (non-parent) categories."""
    parent_codes = {c.parent_code for c in CATEGORIES if c.parent_code}
    return [c for c in CATEGORIES if c.code not in parent_codes]


class EmbeddingClassifier:
    """Classify columns via Dempster-Shafer evidence fusion.

    Satisfies the ``Classifier`` protocol.
    """

    def __init__(
        self,
        config: EmbeddingClassifierConfig,
        category_set: CategorySet | None = None,
    ) -> None:
        self._config = config
        self._model = None
        self._category_set = category_set or sigdg_category_set(hierarchical=True)
        # Legacy view for backward-compat with tests that poke _leaf_categories
        self._leaf_categories = (
            _get_leaf_categories()
            if self._category_set.name == "sigdg"
            else self._category_set.categories
        )
        self._category_embeddings = None  # (N, dim) ndarray
        self._cb_model = None
        self._cb_classes = None
        self._hierarchical_cs: CategorySet | None = None
        self._frame = None  # FrameOfDiscernment, lazily built

    # ── Lazy loading ─────────────────────────────────────────────────

    def _get_model(self):
        """Lazily load the SentenceTransformer model.

        When ``config.device`` is ``"auto"``, detects CUDA availability.
        GPU batch sizes are automatically scaled up from the configured
        value when a CUDA device is selected.
        """
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers package required for embedding classification. "
                "Install with: pip install 'signals[embedding]'"
            )

        device = self._config.device
        if device == "auto":
            device = _detect_device()

        kwargs = {"device": device}
        if self._config.cache_dir:
            kwargs["cache_folder"] = str(self._config.cache_dir)
        self._model = SentenceTransformer(self._config.model_name, **kwargs)

        # Scale batch size for GPU — small models like MiniLM-L6 can easily
        # handle 256+ on a modern GPU
        if device.startswith("cuda") and self._config.batch_size <= 64:
            self._config.batch_size = 256

        return self._model

    def _get_category_embeddings(self):
        """Compute and cache reference embeddings for all leaf categories."""
        if self._category_embeddings is not None:
            return self._category_embeddings

        import numpy as np

        model = self._get_model()
        cats = self._category_set.categories
        texts = [c.embedding_text for c in cats]
        self._category_embeddings = model.encode(
            texts, batch_size=self._config.batch_size
        )
        # Normalise for cosine similarity via dot product
        norms = np.linalg.norm(self._category_embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        self._category_embeddings = self._category_embeddings / norms
        return self._category_embeddings

    def _get_cb_model(self):
        """Lazily load a trained CatBoost model if configured."""
        if self._cb_model is not None:
            return self._cb_model, self._cb_classes

        if not self._config.model_path:
            return None, None

        import json as _json
        from pathlib import Path

        model_path = Path(self._config.model_path)
        if not model_path.exists():
            return None, None

        try:
            from catboost import CatBoostClassifier
        except ImportError:
            raise ImportError(
                "catboost package required for CatBoost classification. "
                "Install with: pip install 'signals[embedding-catboost]'"
            )

        self._cb_model = CatBoostClassifier()
        self._cb_model.load_model(str(model_path))

        # Load class label mapping (saved alongside model)
        classes_path = model_path.with_suffix(".classes.json")
        if classes_path.exists():
            self._cb_classes = _json.loads(classes_path.read_text())
        else:
            self._cb_classes = None

        return self._cb_model, self._cb_classes

    # ── Lazy DST infrastructure ────────────────────────────────────

    def _get_hierarchical_cs(self) -> CategorySet:
        """Return or build a HierarchicalCategorySet from the current category set."""
        if self._hierarchical_cs is not None:
            return self._hierarchical_cs

        if isinstance(self._category_set, HierarchicalCategorySet):
            self._hierarchical_cs = self._category_set
        elif self._category_set.name == "sigdg":
            self._hierarchical_cs = sigdg_category_set(hierarchical=True)
        elif self._category_set.name == "annotations":
            # Already built hierarchically at construction time
            self._hierarchical_cs = self._category_set
        else:
            # Generic category set — wrap as flat hierarchy (all leaves, no parents)
            self._hierarchical_cs = HierarchicalCategorySet(
                name=self._category_set.name,
                categories=self._category_set.categories,
                all_categories=self._category_set.categories,
            )
        return self._hierarchical_cs

    def _get_frame(self):
        """Lazily build the FrameOfDiscernment."""
        if self._frame is not None:
            return self._frame

        from sigint.belief import FrameOfDiscernment
        from sigint.confusable_pairs import get_confusable_pairs

        hcs = self._get_hierarchical_cs()
        pairs = get_confusable_pairs(self._category_set.name)
        self._frame = FrameOfDiscernment(hcs, confusable_pairs=pairs)
        return self._frame

    # ── Classification ───────────────────────────────────────────────

    def classify(
        self,
        sample: ColumnSample,
        siblings: list[ColumnSample] | None = None,
        *,
        features: ColumnFeatures | None = None,
        feature_mask: dict[str, bool] | None = None,
        catboost_proba: dict[str, float] | None = None,
    ) -> HierarchicalClassification | None:
        """Classify a column sample via Dempster-Shafer evidence fusion.

        Combines up to 4 evidence sources:
        1. Cosine similarities → mass function
        2. CatBoost probabilities → mass function (if model loaded or proba provided)
        3. Pattern signals → mass function (if features provided)
        4. Name match → mass function (if enabled)

        Args:
            catboost_proba: External CatBoost probabilities {code: prob} from
                e.g. k-fold CV.  When provided, used instead of the loaded model.

        Returns a HierarchicalClassification with belief intervals.
        """
        import numpy as np

        from sigint.mass_functions import (
            catboost_to_mass,
            cosine_to_mass,
            get_pattern_category_map,
            name_match_to_mass,
            pattern_to_mass,
        )

        frame = self._get_frame()
        hierarchical_cs = self._get_hierarchical_cs()

        model = self._get_model()
        text = build_embedding_text(
            sample,
            include_values=self._config.include_values,
            max_values=self._config.max_values,
            features=features,
            feature_mask=feature_mask,
        )
        vec = model.encode([text], batch_size=1)[0]
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        cat_embs = self._get_category_embeddings()
        sims = cat_embs @ vec

        # Build cosine similarity dict
        cats = self._category_set.categories
        sim_dict = {cat.code: float(sims[i]) for i, cat in enumerate(cats)}

        source_masses: dict[str, object] = {}

        # 1. Cosine evidence
        source_masses["cosine"] = cosine_to_mass(sim_dict, frame, discount=0.3)

        # 2. CatBoost evidence (external proba or loaded model)
        if catboost_proba is not None:
            source_masses["catboost"] = catboost_to_mass(catboost_proba, frame)
        else:
            cb, classes = self._get_cb_model()
            if cb is not None:
                vec_2d = model.encode([text], batch_size=1)
                proba = cb.predict_proba(vec_2d)[0]
                proba_dict = {}
                for i, prob in enumerate(proba):
                    if classes and i < len(classes):
                        proba_dict[classes[i]] = float(prob)
                source_masses["catboost"] = catboost_to_mass(proba_dict, frame)

        # 3. Pattern evidence (if features provided)
        if features is not None and features.pattern_signals:
            pattern_map = get_pattern_category_map(self._category_set.name)
            source_masses["patterns"] = pattern_to_mass(
                features.pattern_signals, frame,
                pattern_category_map=pattern_map,
            )

        # 4. Name match evidence (if enabled)
        if self._config.name_match_boost:
            source_masses["name_match"] = name_match_to_mass(
                sample.column_name, frame, self._category_set
            )

        result = HierarchicalClassification.from_combined_evidence(
            source_masses=source_masses,
            frame=frame,
            category_set=hierarchical_cs,
            sensitivity_code=None,
        )

        # Set sensitivity based on the chosen category
        if self._category_set.name == "sigdg":
            sensitivity = DEFAULT_SENSITIVITY.get(result.category.code)
            from dataclasses import replace
            result = replace(result, sensitivity_code=sensitivity)

        return result
