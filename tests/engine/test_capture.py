"""``capture_scene_evidence`` on real USD stages, without Isaac Sim.

The capture layer moved here from RoboEval's PackingBench runner. Its only Isaac Sim
dependency is the ``world`` it steps for the passive settle, so these tests hand it a stub
world that counts steps and moves nothing; ``pxr`` and ``trimesh`` are real. With no physics
the settled poses equal the spawn poses, which isolates what the capture layer itself
measures: poses, bounds, the support plane, pairwise penetration at both phases, mesh
divergence, static tags, and the metersPerUnit normalisation.
"""

from __future__ import annotations

from typing import Any

import pytest

from scene_verify import core as sv
from scene_verify.bundle import SceneBundle
from scene_verify.capture import capture_scene_evidence


class StubWorld:
    """Stands in for ``isaacsim.core.api.World``: counts settle steps, simulates nothing."""

    def __init__(self) -> None:
        self.steps = 0

    def step(self, render: bool = True) -> None:
        assert render is False
        self.steps += 1


def _box(stage: Any, path: str, *, extents: tuple[float, float, float], center: tuple) -> None:
    """An Xform at ``center`` holding one closed, outward-wound box mesh with a collider."""
    from pxr import Gf, UsdGeom, UsdPhysics

    xform = UsdGeom.Xform.Define(stage, path)
    xform.AddTranslateOp().Set(Gf.Vec3d(*center))
    mesh = UsdGeom.Mesh.Define(stage, f"{path}/Geom")
    hx, hy, hz = (e / 2.0 for e in extents)
    points = [
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
        (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz),
    ]  # fmt: skip
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh.CreatePointsAttr([Gf.Vec3f(*p) for p in points])
    mesh.CreateFaceVertexCountsAttr([4] * 6)
    mesh.CreateFaceVertexIndicesAttr([i for q in quads for i in q])
    UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())


def _stage(meters_per_unit: float, unit: float, *, second_box_x: float | None = None) -> Any:
    """A table (static) and a box resting on it, authored in units of ``unit`` metres."""
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    u = 1.0 / unit  # metres -> stage units
    _box(stage, "/World/Table", extents=(1.0 * u, 1.0 * u, 0.1 * u), center=(0, 0, 0.75 * u))
    _box(stage, "/World/Box", extents=(0.1 * u, 0.1 * u, 0.1 * u), center=(0, 0, 0.85 * u))
    if second_box_x is not None:
        _box(
            stage,
            "/World/Box2",
            extents=(0.1 * u, 0.1 * u, 0.1 * u),
            center=(second_box_x * u, 0, 0.85 * u),
        )
    return stage


def _metas(*, with_second_box: bool = False) -> list[dict[str, Any]]:
    objects = [
        {"object_id": "table", "prim_path": "/World/Table", "is_static_expected": True},
        {"object_id": "box", "prim_path": "/World/Box"},
    ]
    if with_second_box:
        objects.append({"object_id": "box_2", "prim_path": "/World/Box2"})
    bundle = SceneBundle.from_mapping(
        {
            "scene_id": "capture_test",
            "usd_stage_path": "scene.usda",
            "support_prim_path": "/World/Table",
            "objects": objects,
        }
    )
    return bundle.objects_meta()


@pytest.fixture(scope="module")
def cfg() -> sv.VerifyThresholds:
    return sv.load_verify_thresholds(None)


def test_captures_a_resting_box_and_grades_it_pass(cfg):
    world = StubWorld()
    captured, metas = capture_scene_evidence(
        stage=_stage(1.0, 1.0),
        world=world,
        objects_meta=_metas(),
        support_prim_path="/World/Table",
        config=cfg,
        injected_info={"defect": "none"},
    )
    assert world.steps == cfg.settle_steps
    assert [m["object_id"] for m in metas] == ["table", "box"]
    assert captured.load_ok is True
    assert captured.load_detail == {"object_count": 2, "injected": {"defect": "none"}}
    assert captured.table_top_z_m == pytest.approx(0.8)

    table, box = captured.objects
    assert table.is_static_expected and table.has_static_tag is True
    assert box.is_static_expected is False and box.has_static_tag is None
    assert box.pose_before == box.pose_after
    assert box.pose_before is not None
    assert box.pose_before["position"] == pytest.approx([0.0, 0.0, 0.85])
    assert box.pose_before["rotation"] == pytest.approx([1.0, 0.0, 0.0, 0.0])
    assert box.aabb_after == pytest.approx([-0.05, -0.05, 0.8, 0.05, 0.05, 0.9])
    assert box.mesh_divergence == {
        "mesh_present": True,
        "mode": "aabb_only",
        "phantom_max_m": 0.0,
        "phantom_p95_m": 0.0,
        "clip_max_m": 0.0,
        "clip_p95_m": 0.0,
    }
    # One dynamic object: no pair to grade at either phase.
    assert captured.pairwise_overlaps == ()
    assert captured.pairwise_overlaps_pre_settle == ()

    report = sv.evaluate_scene_verify(
        scene_id="capture_test", captured=captured, config=cfg, verified_at="2026-10-17T00:00:00Z"
    )
    assert report.overall_status == "pass", report.to_verdict_json()


def test_normalises_a_centimetre_stage_to_metres(cfg):
    captured, _ = capture_scene_evidence(
        stage=_stage(0.01, 0.01),
        world=StubWorld(),
        objects_meta=_metas(),
        support_prim_path="/World/Table",
        config=cfg,
    )
    assert captured.table_top_z_m == pytest.approx(0.8)
    box = captured.objects[1]
    assert box.pose_after is not None
    assert box.pose_after["position"] == pytest.approx([0.0, 0.0, 0.85])
    assert box.aabb_after == pytest.approx([-0.05, -0.05, 0.8, 0.05, 0.05, 0.9])


def test_grades_an_authored_interpenetration_at_both_phases(cfg):
    # Two 10 cm boxes 4 cm apart centre to centre: 6 cm of overlap along x.
    captured, _ = capture_scene_evidence(
        stage=_stage(1.0, 1.0, second_box_x=0.04),
        world=StubWorld(),
        objects_meta=_metas(with_second_box=True),
        support_prim_path="/World/Table",
        config=cfg,
    )
    for phase in (captured.pairwise_overlaps_pre_settle, captured.pairwise_overlaps):
        # Pairs with the static table are excluded; only box/box_2 is graded.
        assert [(o.object_a, o.object_b) for o in phase] == [("box", "box_2")]
        (overlap,) = phase
        assert overlap.geometry_overlap_detected is True
        assert overlap.overlap_volume_m3 == pytest.approx(0.06 * 0.1 * 0.1, abs=1e-6)
        assert overlap.penetration_depth_m is not None
        assert overlap.penetration_depth_m > cfg.interpenetration_max_penetration_depth_m

    report = sv.evaluate_scene_verify(
        scene_id="clash", captured=captured, config=cfg, verified_at="2026-10-17T00:00:00Z"
    )
    gate = report.gate("interpenetration")
    assert gate is not None and gate.status == "fail"
    assert {o["phase"] for o in gate.detail["offenders"]} == {"authored", "settled"}
    assert {o["basis"] for o in gate.detail["offenders"]} == {"mesh_penetration"}


def test_a_missing_support_prim_leaves_the_table_plane_uncaptured(cfg):
    captured, _ = capture_scene_evidence(
        stage=_stage(1.0, 1.0),
        world=StubWorld(),
        objects_meta=_metas(),
        support_prim_path=None,
        config=cfg,
    )
    assert captured.table_top_z_m is None
