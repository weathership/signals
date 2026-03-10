"""Re-export step definitions from all domains.

Behave only auto-discovers steps from features/steps/.
This module imports from domain-specific step files so
behave can find them.
"""

from features.platform.steps.service_steps import *  # noqa: F401,F403
from features.agent.steps.agent_steps import *  # noqa: F401,F403
from features.analytics.steps.analytics_steps import *  # noqa: F401,F403
