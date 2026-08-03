# -*- coding: utf-8 -*-
"""
Backward-compatibility re-export wrapper for auth module.

This module has been migrated to raganything.services.auth.
All public symbols are re-exported from there.

Import from raganything.services.auth directly in new code:
    from raganything.services.auth import init_db, create_token, decode_token, ...

This wrapper will be removed in a future release.
"""

import warnings

warnings.warn(
    "Import raganything.services.auth instead of the deprecated root auth module.",
    DeprecationWarning,
    stacklevel=2,
)

from raganything.services.auth import *  # noqa: F401, F403, E402
