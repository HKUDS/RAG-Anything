import importlib
import sys

import pytest


@pytest.mark.parametrize(
    ("module_name", "canonical_name"),
    [
        ("auth", "raganything.services.auth"),
        ("agent_manager", "raganything.services.agent_manager"),
    ],
)
def test_root_compatibility_wrappers_warn_and_reexport(module_name, canonical_name):
    sys.modules.pop(module_name, None)
    with pytest.warns(DeprecationWarning):
        wrapper = importlib.import_module(module_name)
    canonical = importlib.import_module(canonical_name)
    symbol = "create_token" if module_name == "auth" else "AgentManager"
    assert getattr(wrapper, symbol) is getattr(canonical, symbol)
