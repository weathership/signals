"""Configuration loading: HOCON + env vars + CLI overrides.

HOCON (config/base.conf) is the single source of truth for all application
config. No module should access os.environ directly for configuration
values. Environment variables are captured by HOCON via ${?VAR} substitution.

Precedence (highest wins):
  1. CLI arguments (passed as overrides dict)
  2. Environment variables (picked up by HOCON ${?VAR} substitution)
  3. config/base.conf defaults

Usage::

    # Load with defaults only
    cfg = load_config()

    # Load with CLI overrides
    cfg = load_config(overrides={"taxonomy_name": "annotations"})

    # Get legacy TaggingConfig for backward compat
    tc = cfg.to_tagging_config()

    # Materialize and validate resolved config
    materialize_config(cfg, "build/config/sigint.env")
    errors = validate_materialized_config("build/config/sigint.env")

Preflight:
    Run ``just resolve-config`` to materialize config, then
    ``just preflight`` (or ``uv run pytest``) to validate.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONF = _PROJECT_ROOT / "config" / "base.conf"


# ── HOCON path → (field_name, type) mapping ──────────────────────

_HOCON_MAP: dict[str, tuple[str, type]] = {
    "impala.host": ("impala_host", str),
    "impala.port": ("impala_port", int),
    "atlas.url": ("atlas_url", str),
    "atlas.user": ("atlas_user", str),
    "atlas.password": ("atlas_password", str),
    "atlas.cluster_name": ("cluster_name", str),
    "sampling.size": ("sample_size", int),
    "sampling.strategy": ("sample_strategy", str),
    "classifier.type": ("classifier_type", str),
    "classifier.confidence_threshold": ("confidence_threshold", float),
    "classifier.name_match_boost": ("name_match_boost", bool),
    "classifier.dry_run": ("dry_run", bool),
    "embedding.model": ("embedding_model", str),
    "embedding.model_path": ("model_path", str),
    "embedding.cache_dir": ("embedding_cache_dir", str),
    "embedding.include_values": ("embedding_include_values", bool),
    "embedding.device": ("device", str),
    "embedding.batch_size": ("batch_size", int),
    "llm.api_key": ("anthropic_api_key", str),
    "llm.model": ("anthropic_model", str),
    "taxonomy.name": ("taxonomy_name", str),
    "taxonomy.hierarchical": ("hierarchical", bool),
    "taxonomy.annotations_path": ("annotations_path", str),
    "taxonomy.taxonomy_file": ("taxonomy_file", str),
    "vocabulary_mapping.enabled": ("vocab_mapping_enabled", bool),
    "vocabulary_mapping.mapping_file": ("vocab_mapping_file", str),
    "svm.model_path": ("svm_model_path", str),
    "svm.discount": ("svm_discount", float),
    "sage.permutations": ("sage_permutations", int),
    "shap.enabled": ("shap_enabled", bool),
    "ml.folds": ("ml_folds", int),
    "ml.train_dir": ("train_dir", str),
    "ml.concat_features": ("concat_features", bool),
    "ml.auto_generate": ("auto_generate", bool),
    "ml.variants_per_category": ("variants_per_category", int),
    "ml.self_train": ("self_train", bool),
    "ml.self_train_rounds": ("self_train_rounds", int),
    "ml.self_train_threshold": ("self_train_threshold", float),
    "gpu.devices": ("gpu_devices", str),
    "bootstrap.max_iterations": ("bootstrap_max_iterations", int),
    "bootstrap.k_threshold": ("bootstrap_k_threshold", float),
    "bootstrap.uncertainty_gap_threshold": ("bootstrap_uncertainty_gap_threshold", float),
    "bootstrap.coverage_target": ("bootstrap_coverage_target", float),
    "bootstrap.confidence_floor": ("bootstrap_confidence_floor", float),
    "bootstrap.initial_sample_fraction": ("bootstrap_initial_sample_fraction", float),
    "bootstrap.propagation_similarity": ("bootstrap_propagation_similarity", float),
    "bootstrap.max_llm_calls_per_iteration": ("bootstrap_max_llm_calls_per_iteration", int),
    "bootstrap.max_total_llm_calls": ("bootstrap_max_total_llm_calls", int),
    "bootstrap.columns_per_call": ("bootstrap_columns_per_call", int),
    "bootstrap.output": ("bootstrap_output", str),
    "bootstrap.llm_backend": ("bootstrap_llm_backend", str),
    "bootstrap.llm_base_url": ("bootstrap_llm_base_url", str),
    "bootstrap.llm_model": ("bootstrap_llm_model", str),
    "bootstrap.llm_api_key": ("bootstrap_llm_api_key", str),
    "bootstrap.llm_max_tokens": ("bootstrap_llm_max_tokens", int),
    "bootstrap.llm_discount": ("bootstrap_llm_discount", float),
    "bootstrap.table_aware_batching": ("bootstrap_table_aware_batching", bool),
    "data.dir": ("data_dir", str),
    "data.input_format": ("input_format", str),
    "data.ground_truth": ("ground_truth", str),
    "data.output": ("output", str),
}

# Reverse: field_name → SIGINT_* env var name
_FIELD_TO_ENV: dict[str, str] = {}
for _hocon_path, (_field, _) in _HOCON_MAP.items():
    _env = "SIGINT_" + _hocon_path.replace(".", "_").upper()
    # Special case: ANTHROPIC_API_KEY keeps its standard name
    if _field == "anthropic_api_key":
        _env = "ANTHROPIC_API_KEY"
    _FIELD_TO_ENV[_field] = _env


@dataclass
class PipelineConfig:
    """Resolved pipeline configuration."""

    # Infrastructure
    impala_host: str = "127.0.0.1"
    impala_port: int = 21050
    atlas_url: str = "http://localhost:21000"
    atlas_user: str = "admin"
    atlas_password: str = "admin"
    cluster_name: str = "signals"

    # Sampling
    sample_size: int = 50
    sample_strategy: str = "head"

    # Classifier
    classifier_type: str = "embedding"
    confidence_threshold: float = 0.3
    name_match_boost: bool = True
    dry_run: bool = False

    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"
    model_path: str | None = None
    embedding_cache_dir: str = "build/models"
    embedding_include_values: bool = True
    device: str = "auto"
    batch_size: int = 32

    # LLM
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-6"

    # Taxonomy
    taxonomy_name: str = "sigdg"
    hierarchical: bool = True
    annotations_path: str | None = None
    taxonomy_file: str | None = None

    # Vocabulary mapping
    vocab_mapping_enabled: bool = False
    vocab_mapping_file: str | None = None

    # SVM classifier (5th DST evidence source — always active when model available)
    svm_model_path: str | None = None
    svm_discount: float = 0.20

    # SAGE
    sage_permutations: int = 512

    # SHAP
    shap_enabled: bool = True

    # GPU
    gpu_devices: str = "0"

    # ML
    ml_folds: int = 5
    train_dir: str | None = None
    concat_features: bool = True
    auto_generate: bool = False
    variants_per_category: int = 50
    self_train: bool = False
    self_train_rounds: int = 1
    self_train_threshold: float = 0.80

    # Bootstrap agent
    bootstrap_max_iterations: int = 5
    bootstrap_k_threshold: float = 0.2
    bootstrap_uncertainty_gap_threshold: float = 0.3
    bootstrap_coverage_target: float = 0.95
    bootstrap_confidence_floor: float = 0.5
    bootstrap_initial_sample_fraction: float = 0.3
    bootstrap_propagation_similarity: float = 0.85
    bootstrap_max_llm_calls_per_iteration: int = 500
    bootstrap_max_total_llm_calls: int = 5000
    bootstrap_columns_per_call: int = 50
    bootstrap_output: str = "build/bootstrap_gt.json"
    bootstrap_llm_backend: str = "cerebras"
    bootstrap_llm_api_key: str | None = None
    bootstrap_llm_base_url: str | None = None
    bootstrap_llm_model: str = "claude-opus-4-6"
    bootstrap_llm_max_tokens: int = 65536
    bootstrap_llm_discount: float = 0.10
    bootstrap_table_aware_batching: bool = True

    # Data paths
    data_dir: str | None = None
    input_format: str = "csv"
    ground_truth: str | None = None
    output: str = "build/sigint_embeddings.parquet"

    # Scope
    databases: list[str] = field(default_factory=lambda: ["default"])
    tables: list[str] = field(default_factory=list)

    def to_tagging_config(self) -> TaggingConfig:
        """Convert to legacy TaggingConfig for backward compat."""
        return TaggingConfig(
            impala_host=self.impala_host,
            impala_port=self.impala_port,
            atlas_url=self.atlas_url,
            atlas_user=self.atlas_user,
            atlas_password=self.atlas_password,
            cluster_name=self.cluster_name,
            sample_size=self.sample_size,
            sample_strategy=self.sample_strategy,
            classifier_type=self.classifier_type,
            confidence_threshold=self.confidence_threshold,
            anthropic_api_key=self.anthropic_api_key,
            anthropic_model=self.anthropic_model,
            annotations_path=self.annotations_path,
            embedding_model=self.embedding_model,
            model_path=self.model_path,
            embedding_cache_dir=self.embedding_cache_dir,
            embedding_include_values=self.embedding_include_values,
            databases=self.databases,
            tables=self.tables,
            dry_run=self.dry_run,
        )

    def build_category_set(self, *, hierarchical: bool | None = None):
        """Build the appropriate CategorySet from taxonomy config.

        Centralizes the taxonomy factory logic that was previously
        duplicated across CLI scripts.

        Args:
            hierarchical: Override the config's hierarchical setting.
                If None, uses self.hierarchical.

        Returns:
            CategorySet or HierarchicalCategorySet
        """
        hier = hierarchical if hierarchical is not None else self.hierarchical

        if self.taxonomy_file:
            return _load_custom_taxonomy(self.taxonomy_file, hierarchical=hier)

        if self.taxonomy_name == "annotations":
            from sigint.category_set import annotation_category_set

            if not self.annotations_path:
                raise ValueError(
                    "taxonomy.annotations_path is required when "
                    "taxonomy.name = 'annotations'"
                )
            return annotation_category_set(
                self.annotations_path, hierarchical=hier,
            )

        if self.taxonomy_name == "sigdg":
            from sigint.category_set import sigdg_category_set

            return sigdg_category_set(hierarchical=hier)

        # Try as a taxonomy_file path for backward compat
        raise ValueError(
            f"Unknown taxonomy: {self.taxonomy_name!r}. "
            f"Use 'sigdg', 'annotations', or set taxonomy_file."
        )


def _load_custom_taxonomy(taxonomy_file: str, *, hierarchical: bool = False):
    """Load a custom taxonomy from a Python module.

    The module must export a function matching *_category_set()
    that accepts a hierarchical keyword argument.
    """
    import importlib.util

    path = Path(taxonomy_file).resolve()
    spec = importlib.util.spec_from_file_location("custom_taxonomy", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load taxonomy module: {path}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Find *_category_set() function
    for name in dir(mod):
        if name.endswith("_category_set") and callable(getattr(mod, name)):
            factory = getattr(mod, name)
            try:
                return factory(hierarchical=hierarchical)
            except TypeError:
                # Factory doesn't accept hierarchical kwarg
                return factory()

    raise ValueError(
        f"Taxonomy module {path} has no *_category_set() function"
    )


# ── Legacy TaggingConfig (backward compat) ───────────────────────


@dataclass
class TaggingConfig:
    """All knobs for the sample -> classify -> tag pipeline."""

    # Impala connection
    impala_host: str = "127.0.0.1"
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
    model_path: str | None = None
    embedding_cache_dir: str = "build/models"
    embedding_include_values: bool = True

    # Databases / tables to process
    databases: list[str] = field(default_factory=lambda: ["default"])
    tables: list[str] = field(default_factory=list)

    # Dry-run mode — classify but don't write to Atlas
    dry_run: bool = False


# ── HOCON loading ────────────────────────────────────────────────


def _coerce(val: Any, target_type: type) -> Any:
    """Coerce a HOCON value to the target Python type."""
    if val is None:
        return None
    if target_type is bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)
    if target_type is int:
        return int(val)
    if target_type is float:
        return float(val)
    return str(val)


def _hocon_to_dict(conf) -> dict[str, Any]:
    """Extract values from a pyhocon ConfigTree using the mapping table."""
    result: dict[str, Any] = {}
    for hocon_path, (field_name, field_type) in _HOCON_MAP.items():
        try:
            val = conf.get(hocon_path)
        except Exception:
            continue
        if val is None:
            continue
        result[field_name] = _coerce(val, field_type)

    # List fields need special handling
    try:
        result["databases"] = list(conf.get_list("scope.databases"))
    except Exception:
        pass
    try:
        tables = list(conf.get_list("scope.tables"))
        if tables:
            result["tables"] = tables
    except Exception:
        pass

    return result


def load_config(
    conf_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> PipelineConfig:
    """Load configuration with three-layer precedence.

    1. Start from config/base.conf defaults (with env var substitution)
    2. Apply explicit CLI overrides

    Args:
        conf_path: Path to HOCON config file. Defaults to config/base.conf.
        overrides: CLI overrides as ``{field_name: value}`` dict. Only
            non-None values are applied (highest precedence).
    """
    from pyhocon import ConfigFactory

    conf_path = Path(conf_path) if conf_path else _DEFAULT_CONF

    if conf_path.exists():
        conf = ConfigFactory.parse_file(str(conf_path))
    else:
        conf = ConfigFactory.parse_string("")

    values = _hocon_to_dict(conf)

    # Apply CLI overrides (highest precedence)
    if overrides:
        for key, val in overrides.items():
            if val is not None:
                values[key] = val

    return PipelineConfig(**values)


def materialize_config(
    cfg: PipelineConfig,
    output_path: str | Path,
) -> Path:
    """Write resolved config as flat key=value file for shell consumption.

    Output format (sourceable by shell)::

        ANTHROPIC_API_KEY=sk-ant-...
        SIGINT_ATLAS_URL=http://localhost:21000
        SIGINT_CONFIDENCE_THRESHOLD=0.3
        ...

    Returns:
        The output path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for f in dataclasses.fields(cfg):
        val = getattr(cfg, f.name)
        if val is None:
            continue

        env_name = _FIELD_TO_ENV.get(f.name, f"SIGINT_{f.name.upper()}")

        if isinstance(val, bool):
            val_str = "true" if val else "false"
        elif isinstance(val, list):
            val_str = ",".join(str(v) for v in val)
        else:
            val_str = str(val)

        lines.append(f"{env_name}={val_str}")

    output_path.write_text("\n".join(sorted(lines)) + "\n")
    return output_path


# ── Preflight validation ─────────────────────────────────────────

# Keys that must be present and non-empty in the materialized config
# for the pipeline to function. These are the baseline keys — every
# resolved config must have them regardless of operational mode.
REQUIRED_KEYS: list[str] = [
    "SIGINT_CLASSIFIER_CONFIDENCE_THRESHOLD",
    "SIGINT_CLASSIFIER_TYPE",
    "SIGINT_EMBEDDING_MODEL",
    "SIGINT_TAXONOMY_NAME",
]

# Keys required only when specific features are enabled.
# Each entry: (condition_key, condition_value, required_keys).
CONDITIONAL_KEYS: list[tuple[str, str, list[str]]] = [
    (
        "SIGINT_CLASSIFIER_TYPE", "llm",
        ["ANTHROPIC_API_KEY"],
    ),
    (
        "SIGINT_TAXONOMY_NAME", "annotations",
        ["SIGINT_TAXONOMY_ANNOTATIONS_PATH"],
    ),
    (
        "SIGINT_VOCABULARY_MAPPING_ENABLED", "true",
        ["SIGINT_VOCABULARY_MAPPING_MAPPING_FILE"],
    ),
]

_MATERIALIZED_PATH = _PROJECT_ROOT / "build" / "config" / "sigint.env"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a flat key=value env file into a dict."""
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def validate_materialized_config(
    path: str | Path | None = None,
) -> list[str]:
    """Validate the materialized config file for completeness.

    Returns a list of error strings. Empty list means valid.

    Args:
        path: Path to the materialized env file. Defaults to
            build/config/sigint.env.
    """
    path = Path(path) if path else _MATERIALIZED_PATH
    errors: list[str] = []

    if not path.exists():
        errors.append(
            f"{path} does not exist. Run 'just resolve-config' first."
        )
        return errors

    env = _parse_env_file(path)

    # Check required keys
    for key in REQUIRED_KEYS:
        if key not in env or not env[key]:
            errors.append(f"Missing required config key: {key}")

    # Check conditional keys
    for cond_key, cond_value, req_keys in CONDITIONAL_KEYS:
        if env.get(cond_key) == cond_value:
            for key in req_keys:
                if key not in env or not env[key]:
                    errors.append(
                        f"Missing config key: {key} "
                        f"(required when {cond_key}={cond_value})"
                    )

    return errors


# ── GPU preflight ────────────────────────────────────────────────


@dataclass(frozen=True)
class GpuInfo:
    """GPU detection result from preflight."""

    available: bool
    device_count: int = 0
    driver_version: str = ""
    driver_cuda_version: str = ""
    pytorch_cuda_version: str = ""
    devices: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def resolved_device(self) -> str:
        """Return 'cuda' if GPUs are usable, else 'cpu'."""
        return "cuda" if self.available else "cpu"

    def summary(self) -> str:
        """Human-readable GPU status string."""
        if not self.device_count:
            return "No NVIDIA GPUs detected"
        if not self.available:
            return (
                f"{self.device_count}x GPU detected but CUDA unavailable "
                f"(driver CUDA {self.driver_cuda_version}, "
                f"PyTorch CUDA {self.pytorch_cuda_version})"
            )
        vram = f" ({', '.join(self.devices)})" if self.devices else ""
        return f"{self.device_count}x GPU available{vram}, CUDA {self.driver_cuda_version}"


_gpu_info_cache: GpuInfo | None = None


def preflight_gpu() -> GpuInfo:
    """Detect GPU availability and validate CUDA driver compatibility.

    Checks:
    1. nvidia-smi reachable -> GPU count, driver version, CUDA version
    2. torch.cuda.is_available() -> runtime compatibility
    3. Version mismatch detection with actionable fix guidance

    This runs at config load time so the resolved device is known before
    any model loading.  Warnings are surfaced in the preflight report
    but never block startup (CPU fallback is always safe).

    Results are cached for the process lifetime (GPU hardware doesn't
    change mid-run).
    """
    global _gpu_info_cache
    if _gpu_info_cache is not None:
        return _gpu_info_cache

    import re
    import shutil
    import subprocess

    warnings: list[str] = []
    device_count = 0
    driver_version = ""
    driver_cuda = ""
    pytorch_cuda = ""
    device_names: list[str] = []
    cuda_available = False

    # ── Step 1: Probe nvidia-smi for hardware ────────────────────
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    device_names.append(
                        f"{parts[0]} {parts[1]}" if len(parts) >= 2 else parts[0],
                    )
                device_count = len(device_names)

            # Get driver version
            result2 = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=driver_version",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result2.returncode == 0:
                driver_version = result2.stdout.strip().splitlines()[0].strip()

            # Parse CUDA version from nvidia-smi header
            result3 = subprocess.run(
                ["nvidia-smi"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result3.returncode == 0:
                for line in result3.stdout.splitlines():
                    if "CUDA Version" in line:
                        m = re.search(r"CUDA Version:\s*([\d.]+)", line)
                        if m:
                            driver_cuda = m.group(1)
                        break
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    # ── Step 2: Check PyTorch CUDA runtime ───────────────────────
    try:
        import torch

        pytorch_cuda = torch.version.cuda or ""
        cuda_available = torch.cuda.is_available()

        if not cuda_available and device_count > 0 and pytorch_cuda:
            # GPUs present but torch can't see them -> version mismatch
            warnings.append(
                f"CUDA version mismatch: driver supports CUDA {driver_cuda}, "
                f"PyTorch built for CUDA {pytorch_cuda}. "
                f"Upgrade driver: sudo apt install nvidia-driver-570-open && sudo reboot"
            )
    except ImportError:
        if device_count > 0:
            warnings.append(
                "PyTorch not installed — GPUs detected but cannot be used. "
                "Install: uv add torch"
            )

    # ── Step 3: Check CatBoost GPU (independent CUDA runtime) ───
    if device_count > 0 and not cuda_available:
        warnings.append(
            "CatBoost GPU also requires compatible driver "
            "(same CUDA version constraint as PyTorch)"
        )

    _gpu_info_cache = GpuInfo(
        available=cuda_available,
        device_count=device_count,
        driver_version=driver_version,
        driver_cuda_version=driver_cuda,
        pytorch_cuda_version=pytorch_cuda,
        devices=device_names,
        warnings=warnings,
    )
    return _gpu_info_cache
