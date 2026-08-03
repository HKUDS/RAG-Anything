# -*- coding: utf-8 -*-
"""
Backward-compatibility re-export wrapper for agent_manager module.

This module has been migrated to raganything.services.agent_manager.
All public symbols are re-exported from there.

Import from raganything.services.agent_manager directly in new code:
    from raganything.services.agent_manager import init_agent_manager, AgentManager, ...

This wrapper will be removed in a future release.
"""

import warnings

warnings.warn(
    "Import raganything.services.agent_manager instead of the deprecated root agent_manager module.",
    DeprecationWarning,
    stacklevel=2,
)

from raganything.services.agent_manager import *  # noqa: F401, F403, E402
