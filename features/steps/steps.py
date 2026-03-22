"""Re-export step definitions from all domains.

Behave only auto-discovers steps from features/steps/.
This module imports from domain-specific step files so
behave can find them.
"""

from features.platform.steps.health_steps import *  # noqa: F401,F403
from features.platform.steps.integration_steps import *  # noqa: F401,F403
from features.platform.steps.data_lifecycle_steps import *  # noqa: F401,F403
from features.classification.steps.config_steps import *  # noqa: F401,F403
from features.classification.steps.feature_steps import *  # noqa: F401,F403
from features.classification.steps.taxonomy_steps import *  # noqa: F401,F403
from features.classification.steps.evidence_steps import *  # noqa: F401,F403
from features.classification.steps.classification_steps import *  # noqa: F401,F403
from features.classification.steps.benchmark_steps import *  # noqa: F401,F403
from features.classification.steps.bespoke_steps import *  # noqa: F401,F403
from features.classification.steps.vocab_steps import *  # noqa: F401,F403
from features.tagging.steps.tagging_steps import *  # noqa: F401,F403
