"""Shared fixtures. The tests need no GPU and no Isaac Sim: ``pxr`` is the real usd-core from
the dev group, and the Isaac Sim modules a runner path imports are stubbed per test."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

#: The Isaac Sim modules the engine imports inside its runner and capture functions.
ISAAC_MODULES = (
    "carb",
    "carb.settings",
    "isaacsim",
    "isaacsim.core",
    "isaacsim.core.api",
    "omni",
    "omni.kit",
    "omni.kit.app",
    "omni.usd",
)


@pytest.fixture
def isaac_stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Install MagicMock stand-ins for carb, isaacsim and omni for one test.

    Each stub is reachable both by its dotted name in ``sys.modules`` and as an attribute of
    its parent, so ``import omni.usd`` followed by ``omni.usd.get_context()`` reaches the same
    object the test configures. ``monkeypatch`` removes them afterwards.
    """
    stubs: dict[str, MagicMock] = {}
    for name in ISAAC_MODULES:
        stub = MagicMock(name=name)
        stubs[name] = stub
        monkeypatch.setitem(sys.modules, name, stub)
    for name, stub in stubs.items():
        parent, _, child = name.rpartition(".")
        if parent:
            setattr(stubs[parent], child, stub)
    return stubs
