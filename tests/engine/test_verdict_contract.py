"""Producer-side lock on the ``scene_verify/1`` cross-repo contract.

The SceneForge ``scene_verify`` QA gate (a *separate* repo) consumes the verdict this engine
emits. It reads exactly: ``schema_version`` (must start ``scene_verify/``), ``overall_status``
(``pass`` | ``warn`` | ``fail``), and ``gates`` as a list of objects each with string
``gate`` and ``status`` fields. These tests assert the engine's ``to_verdict_json()`` always
satisfies that shape across pass / warn / fail outcomes, so a producer-side change can never
silently break the consumer.
"""

from __future__ import annotations

import dataclasses
import json
import math
from typing import Any

import pytest

import scene_verify
import scene_verify_contract
from scene_verify import core as sv
from scene_verify_contract import parse_verdict

#: A stand-in stage digest; the runner hashes the real file
#: (tests/engine/test_usd_bundle_runner.py).
USD_SHA256 = "cd" * 32


def _evidence(*, static_tag: bool, phantom_m: float):
    return sv.CapturedSceneEvidence(
        objects=(
            sv.CapturedObjectEvidence(
                object_id="carton",
                is_static_expected=True,
                has_static_tag=static_tag,
                aabb_after=[-0.1, -0.1, 0.0, 0.1, 0.1, 0.2],
                mesh_divergence={
                    "mesh_present": True,
                    "mode": "aabb_only",
                    "phantom_max_m": 0.0,
                    "clip_max_m": 0.0,
                },
            ),
            sv.CapturedObjectEvidence(
                object_id="box",
                is_static_expected=False,
                pose_before={"position": [0, 0, 0.1], "rotation": [1, 0, 0, 0]},
                pose_after={"position": [0, 0, 0.1], "rotation": [1, 0, 0, 0]},
                aabb_after=[0.0, 0.0, 0.02, 0.05, 0.05, 0.07],
                mesh_divergence={
                    "mesh_present": True,
                    "mode": "sampled",
                    "phantom_max_m": phantom_m,
                    "clip_max_m": 0.0,
                },
            ),
        ),
        load_ok=True,
        load_detail={"object_count": 2},
        table_top_z_m=0.0,
        pairwise_overlaps=(),
    )


def _verdict(*, static_tag: bool, phantom_m: float) -> dict:
    cfg = sv.load_verify_thresholds(None)
    report = sv.evaluate_scene_verify(
        scene_id="contract_scene",
        captured=_evidence(static_tag=static_tag, phantom_m=phantom_m),
        config=cfg,
        verified_at="2026-06-29T00:00:00+00:00",
        usd_sha256=USD_SHA256,
    )
    return report.to_verdict_json()


def _assert_consumer_contract(verdict: dict) -> None:
    # Mirrors app/services/scene_release_service._build_scene_verify_check on the SceneForge side.
    assert isinstance(verdict.get("schema_version"), str)
    # Pin the MAJOR: the SceneForge gate recognizes exactly scene_verify/1 (fail-closed on
    # any other major), so a producer-side bump to scene_verify/2 must fail here first.
    assert verdict["schema_version"] == "scene_verify/1"
    assert verdict.get("overall_status") in {"pass", "warn", "fail"}
    gates = verdict.get("gates")
    assert isinstance(gates, list) and gates
    for gate in gates:
        assert isinstance(gate, dict)
        assert isinstance(gate.get("gate"), str) and gate["gate"]
        assert gate.get("status") in {"pass", "warn", "fail"}


def test_pass_verdict_satisfies_consumer_contract():
    verdict = _verdict(static_tag=True, phantom_m=0.001)
    assert verdict["overall_status"] == "pass"
    _assert_consumer_contract(verdict)


def test_fail_verdict_satisfies_consumer_contract():
    # Missing static tag => static_metadata_present fail.
    verdict = _verdict(static_tag=False, phantom_m=0.001)
    assert verdict["overall_status"] == "fail"
    assert any(
        g["gate"] == "static_metadata_present" and g["status"] == "fail" for g in verdict["gates"]
    )
    _assert_consumer_contract(verdict)


def test_warn_verdict_satisfies_consumer_contract():
    cfg = sv.load_verify_thresholds(None)
    # A phantom-depth between warn and fail thresholds yields a warn on mesh agreement.
    phantom = (cfg.mesh_phantom_warn_m + cfg.mesh_phantom_fail_m) / 2.0
    verdict = _verdict(static_tag=True, phantom_m=phantom)
    assert verdict["overall_status"] == "warn"
    _assert_consumer_contract(verdict)


# ---------------------------------------------------------------------------
# The contract package's validator accepts every verdict the engine emits
# ---------------------------------------------------------------------------


def test_engine_takes_the_contract_from_the_contract_package():
    assert sv.SCHEMA_VERSION is scene_verify_contract.SCHEMA_VERSION
    assert scene_verify.SCHEMA_VERSION == "scene_verify/1"
    assert scene_verify.GateStatus is scene_verify_contract.GateStatus
    assert scene_verify.Bucket is scene_verify_contract.Bucket
    assert sv.worst_status(["pass", "warn"]) == "warn"
    assert sv.worst_status(["warn", "fail", "pass"]) == "fail"
    assert sv.worst_status([]) == "pass"


def _overlap(depth: float | None, volume: float = 0.0005) -> sv.CapturedPairOverlap:
    return sv.CapturedPairOverlap("box", "box_2", volume, True, penetration_depth_m=depth)


def _scenarios() -> dict[str, tuple[sv.CapturedSceneEvidence, dict[str, Any]]]:
    """Evidence covering every gate in each status it can take, and the optional fields."""
    cfg = sv.load_verify_thresholds(None)
    clean = _evidence(static_tag=True, phantom_m=0.001)
    box = clean.objects[1]
    warn_phantom = (cfg.mesh_phantom_warn_m + cfg.mesh_phantom_fail_m) / 2.0
    recon_pass = {
        "declared": {"registered_images": 90, "total_frames": 90},
        "measured": {"face_count": 1_564_909, "area_ratio": 0.1269},
    }
    recon_fail = {
        "declared": {"registered_images": 10, "total_frames": 90},
        "measured": {"face_count": 109, "area_ratio": 0.0007},
    }
    drifted = dataclasses.replace(
        box, pose_after={"position": [0.0, 0.0, 0.3], "rotation": [0.92388, 0, 0, 0.38268]}
    )
    return {
        "pass": (clean, {}),
        "pass bound to another usd": (clean, {"usd_sha256": "ab" * 32}),
        "warn mesh": (_evidence(static_tag=True, phantom_m=warn_phantom), {}),
        "fail static metadata": (_evidence(static_tag=False, phantom_m=0.001), {}),
        "fail mesh": (_evidence(static_tag=True, phantom_m=0.05), {}),
        "warn mesh missing": (
            dataclasses.replace(
                clean,
                objects=(
                    clean.objects[0],
                    dataclasses.replace(box, mesh_divergence={"mesh_present": False}),
                ),
            ),
            {},
        ),
        "fail load with no objects": (sv.CapturedSceneEvidence(objects=(), load_ok=False), {}),
        "fail load": (dataclasses.replace(clean, load_ok=False), {}),
        "warn no table": (dataclasses.replace(clean, table_top_z_m=None), {}),
        "fail fall through": (dataclasses.replace(clean, table_top_z_m=0.5), {}),
        "fail settle": (dataclasses.replace(clean, objects=(clean.objects[0], drifted)), {}),
        "warn unassessed pose": (
            dataclasses.replace(
                clean,
                objects=(clean.objects[0], dataclasses.replace(box, pose_before=None)),
            ),
            {},
        ),
        "fail authored interpenetration": (
            dataclasses.replace(clean, pairwise_overlaps_pre_settle=(_overlap(0.02),)),
            {},
        ),
        "fail settled aabb fallback": (
            dataclasses.replace(clean, pairwise_overlaps=(_overlap(math.nan),)),
            {},
        ),
        "pass corner clip": (dataclasses.replace(clean, pairwise_overlaps=(_overlap(0.0),)), {}),
        "pass reconstruction": (dataclasses.replace(clean, recon_fidelity=recon_pass), {}),
        "fail reconstruction": (dataclasses.replace(clean, recon_fidelity=recon_fail), {}),
        "warn reconstruction undeclared": (
            dataclasses.replace(clean, recon_fidelity={"declared": {}, "measured": {}}),
            {},
        ),
    }


@pytest.mark.parametrize("scenario", list(_scenarios()))
def test_every_engine_verdict_passes_the_contract_validator(scenario: str, tmp_path):
    captured, extra = _scenarios()[scenario]
    report = sv.evaluate_scene_verify(
        scene_id=f"contract_{scenario.replace(' ', '_')}",
        captured=captured,
        config=sv.load_verify_thresholds(None),
        verified_at="2026-10-17T10:00:00+00:00",
        **{"usd_sha256": USD_SHA256, **extra},
    )
    # Each scenario is named for the overall status it yields.
    assert report.overall_status == scenario.split()[0]
    verdict = report.to_verdict_json()
    _assert_consumer_contract(verdict)

    parsed = parse_verdict(verdict)
    assert parsed.overall_status == report.overall_status
    assert [gate.gate for gate in parsed.gates] == [gate.gate for gate in report.gates]
    assert dict(parsed.bucket_attribution) == {
        bucket: tuple(names) for bucket, names in report.bucket_attribution.items()
    }
    assert parsed.usd_sha256 == extra.get("usd_sha256", USD_SHA256)
    assert verdict["usd_sha256"] == parsed.usd_sha256

    # A consumer reads the verdict.json the runner writes, so the file must validate too.
    paths = sv.dump_report(report=report, captured=captured, artifacts_dir=tmp_path)
    assert parse_verdict(json.loads(paths["verdict"].read_text(encoding="utf-8"))) == parsed


def test_the_scenarios_cover_every_status():
    statuses = set()
    for captured, extra in _scenarios().values():
        report = sv.evaluate_scene_verify(
            scene_id="coverage",
            captured=captured,
            config=sv.load_verify_thresholds(None),
            verified_at="2026-10-17T10:00:00+00:00",
            **extra,
        )
        statuses.add(report.overall_status)
    assert statuses == {"pass", "warn", "fail"}


def test_the_engine_refuses_to_write_a_verdict_without_a_stage_digest(tmp_path):
    # usd_sha256 is required by the contract since 0.4.0, so the engine never writes a verdict
    # the contract would refuse.
    captured = _evidence(static_tag=True, phantom_m=0.001)
    report = sv.evaluate_scene_verify(
        scene_id="unbound",
        captured=captured,
        config=sv.load_verify_thresholds(None),
        verified_at="2026-11-08T10:00:00+00:00",
    )
    with pytest.raises(ValueError, match="usd_sha256"):
        report.to_verdict_json()
    with pytest.raises(ValueError, match="usd_sha256"):
        sv.dump_report(report=report, captured=captured, artifacts_dir=tmp_path)
    assert not (tmp_path / "scene_verify" / "unbound" / "verdict.json").exists()
