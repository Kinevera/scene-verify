"""The engine's VERIFIER_VERSION follows the release: both distributions carry the release
tag's version, the engine pins the contract at it, and every verdict reports it
(scene-verify-0001)."""

from __future__ import annotations

from importlib.metadata import requires, version

import scene_verify
from scene_verify import core as sv


def test_verifier_version_equals_the_engine_distribution_version():
    assert sv.VERIFIER_VERSION == version("scene-verify")
    assert scene_verify.VERIFIER_VERSION == sv.VERIFIER_VERSION


def test_both_distributions_carry_one_version():
    assert version("scene-verify-contract") == version("scene-verify")


def test_the_engine_pins_the_contract_at_its_own_version():
    pins = [req.replace(" ", "") for req in requires("scene-verify") or []]
    assert f"scene-verify-contract=={version('scene-verify')}" in pins


def test_a_verdict_reports_the_verifier_version():
    report = sv.SceneVerifyReport.from_gates(
        scene_id="version",
        gates=[],
        verified_at="2026-10-17T00:00:00+00:00",
        usd_sha256="ef" * 32,
    )
    assert report.to_verdict_json()["verifier_version"] == version("scene-verify")
