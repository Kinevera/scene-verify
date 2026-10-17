"""Producer-side lock on the ``scene_verify/1`` cross-repo contract.

The SceneForge ``scene_verify`` QA gate (a *separate* repo) consumes the verdict this engine
emits. It reads exactly: ``schema_version`` (must start ``scene_verify/``), ``overall_status``
(``pass`` | ``warn`` | ``fail``), and ``gates`` as a list of objects each with string
``gate`` and ``status`` fields. These tests assert the engine's ``to_verdict_json()`` always
satisfies that shape across pass / warn / fail outcomes, so a producer-side change can never
silently break the consumer.
"""

from __future__ import annotations

from app.scene_verify import core as sv


def _evidence(*, static_tag: bool, phantom_m: float):
    return sv.CapturedSceneEvidence(
        objects=(
            sv.CapturedObjectEvidence(
                object_id="carton",
                is_static_expected=True,
                has_static_tag=static_tag,
                aabb_after=[-0.1, -0.1, 0.0, 0.1, 0.1, 0.2],
                mesh_divergence={"mesh_present": True, "mode": "aabb_only",
                                 "phantom_max_m": 0.0, "clip_max_m": 0.0},
            ),
            sv.CapturedObjectEvidence(
                object_id="box",
                is_static_expected=False,
                pose_before={"position": [0, 0, 0.1], "rotation": [1, 0, 0, 0]},
                pose_after={"position": [0, 0, 0.1], "rotation": [1, 0, 0, 0]},
                aabb_after=[0.0, 0.0, 0.02, 0.05, 0.05, 0.07],
                mesh_divergence={"mesh_present": True, "mode": "sampled",
                                 "phantom_max_m": phantom_m, "clip_max_m": 0.0},
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
        g["gate"] == "static_metadata_present" and g["status"] == "fail"
        for g in verdict["gates"]
    )
    _assert_consumer_contract(verdict)


def test_warn_verdict_satisfies_consumer_contract():
    cfg = sv.load_verify_thresholds(None)
    # A phantom-depth between warn and fail thresholds yields a warn on mesh agreement.
    phantom = (cfg.mesh_phantom_warn_m + cfg.mesh_phantom_fail_m) / 2.0
    verdict = _verdict(static_tag=True, phantom_m=phantom)
    assert verdict["overall_status"] == "warn"
    _assert_consumer_contract(verdict)
