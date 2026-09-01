"""Shared test configuration.

The suite must be hermetic: no network, no third-party API, no spend. That is
not hypothetical -- once a real FEATHERLESS_API_KEY exists in .env, every
simulated cycle in the pipeline tests would otherwise make a live inference
call, turning a two-second suite into a network-bound one that bills per run.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def no_network_llm(monkeypatch):
    """Force every FeatherlessClient built during a test into offline mode."""
    import deflow.llm as llm

    original = llm.FeatherlessClient.__init__

    def offline_init(self, *args, **kwargs):
        kwargs["enabled"] = False
        original(self, *args, **kwargs)

    monkeypatch.setattr(llm.FeatherlessClient, "__init__", offline_init)
