"""Venv-only soundness tests for the scene verifier engine.

These run without Isaac (no Isaac module is imported; ``pxr``/``trimesh`` are real).
They are the credibility gate: they prove each defect class flips the right gate and that
the physics-instability and missing-static-metadata buckets stay disjoint — before any
failure-rate is quoted over a real corpus. The PackingBench legacy projection is covered
separately in RoboEval's tests/benchmarks/test_scene_verify_packingbench.py.
"""

from __future__ import annotations

import pytest
import trimesh

from scene_verify import core as sv
from scene_verify import defects
from scene_verify import geometry as geom

VERIFIED_AT = "2026-06-22T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cfg() -> sv.VerifyThresholds:
    return sv.load_verify_thresholds()


@pytest.fixture
def real_pxr():
    """The real installed USD (usd-core in the dev group), so USD extraction/injection is
    exercised without Isaac. In RoboEval this fixture swapped out a session-wide ``pxr``
    MagicMock; here nothing mocks ``pxr``, so it only marks the tests that need it.
    """
    import importlib

    return importlib.import_module("pxr")


def _good_mesh_divergence() -> dict:
    return {"mesh_present": True, "mode": "aabb_only", "phantom_max_m": 0.0, "clip_max_m": 0.0}


def _carton(*, has_static_tag: bool = True, drifted: bool = False) -> sv.CapturedObjectEvidence:
    after_pos = [0.0, 0.0, 0.70] if drifted else [0.0, 0.0, 0.80]
    after_rot = [0.92388, 0.0, 0.0, 0.38268] if drifted else [1.0, 0.0, 0.0, 0.0]
    return sv.CapturedObjectEvidence(
        object_id="target_carton",
        is_static_expected=True,
        has_static_tag=has_static_tag,
        pose_before={"position": [0.0, 0.0, 0.80], "rotation": [1.0, 0.0, 0.0, 0.0]},
        pose_after={"position": after_pos, "rotation": after_rot},
        aabb_after=[-0.10, -0.10, 0.80, 0.10, 0.10, 0.95],
        mesh_divergence=_good_mesh_divergence(),
    )


def _item(
    *,
    mesh_divergence: dict | None = None,
    aabb_bottom_z: float = 0.81,
) -> sv.CapturedObjectEvidence:
    return sv.CapturedObjectEvidence(
        object_id="item",
        is_static_expected=False,
        pose_before={"position": [0.2, 0.0, 0.82], "rotation": [1.0, 0.0, 0.0, 0.0]},
        pose_after={"position": [0.2, 0.0, 0.821], "rotation": [1.0, 0.0, 0.0, 0.0]},
        aabb_after=[0.18, -0.02, aabb_bottom_z, 0.22, 0.02, aabb_bottom_z + 0.05],
        mesh_divergence=mesh_divergence or _good_mesh_divergence(),
    )


def _scene(
    *,
    objects: tuple[sv.CapturedObjectEvidence, ...],
    overlaps: tuple[sv.CapturedPairOverlap, ...] = (),
) -> sv.CapturedSceneEvidence:
    return sv.CapturedSceneEvidence(
        objects=objects,
        load_ok=True,
        table_top_z_m=0.80,
        pairwise_overlaps=overlaps,
    )


def _author_box_mesh(stage, path, *, extents=(0.10, 0.06, 0.04), translate=(0.0, 0.0, 0.0)):
    from pxr import Gf, UsdGeom

    mesh = UsdGeom.Mesh.Define(stage, path)
    hx, hy, hz = (e / 2.0 for e in extents)
    points = [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ]
    mesh.CreatePointsAttr([Gf.Vec3f(*p) for p in points])
    mesh.CreateFaceVertexCountsAttr([4, 4, 4, 4, 4, 4])
    mesh.CreateFaceVertexIndicesAttr(
        [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 5, 4, 1, 2, 6, 5, 2, 3, 7, 6, 3, 0, 4, 7]
    )
    if any(translate):
        UsdGeom.Xformable(mesh).AddTranslateOp().Set(Gf.Vec3d(*translate))
    return mesh.GetPrim()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_thresholds_load_from_yaml(cfg):
    assert cfg.settle_steps == 60
    assert cfg.max_linear_displacement_m == pytest.approx(0.01)
    assert cfg.mesh_phantom_fail_m == pytest.approx(0.015)
    assert cfg.defect_oversize_factor == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# Directional divergence (the one new geometric check)
# ---------------------------------------------------------------------------


def test_directional_divergence_directions(cfg):
    visual = trimesh.creation.box(extents=[0.10, 0.06, 0.04])
    identical = trimesh.creation.box(extents=[0.10, 0.06, 0.04])
    oversize = trimesh.creation.box(extents=[0.15, 0.09, 0.06])
    undersize = trimesh.creation.box(extents=[0.06, 0.036, 0.024])

    same = geom.directional_mesh_divergence(visual, identical, n_samples=1200)
    assert same["mode"] == "aabb_only"
    assert same["phantom_max_m"] == 0.0 and same["clip_max_m"] == 0.0

    big = geom.directional_mesh_divergence(visual, oversize, n_samples=1200)
    assert big["mode"] == "sampled"
    assert big["phantom_max_m"] > cfg.mesh_phantom_fail_m  # collision outside visual
    assert big["clip_max_m"] == 0.0

    small = geom.directional_mesh_divergence(visual, undersize, n_samples=1200)
    assert small["mode"] == "sampled"
    assert small["clip_max_m"] > cfg.mesh_clip_fail_m  # visual outside collision
    assert small["phantom_max_m"] == 0.0


def test_directional_divergence_missing_mesh():
    visual = trimesh.creation.box(extents=[0.1, 0.1, 0.1])
    out = geom.directional_mesh_divergence(visual, None)
    assert out["mesh_present"] is False and out["mode"] == "missing"


def test_mesh_gate_thresholding(cfg):
    fail = sv.evaluate_mesh_agreement_gate(
        {"o": {"mesh_present": True, "mode": "sampled", "phantom_max_m": 0.03, "clip_max_m": 0.0}},
        cfg,
    )
    assert fail.status == "fail" and fail.bucket == "mesh_disagreement"

    warn = sv.evaluate_mesh_agreement_gate(
        {"o": {"mesh_present": True, "mode": "sampled", "phantom_max_m": 0.008, "clip_max_m": 0.0}},
        cfg,
    )
    assert warn.status == "warn"

    missing = sv.evaluate_mesh_agreement_gate(
        {"o": {"mesh_present": False, "mode": "missing"}}, cfg
    )
    assert missing.status == "warn" and missing.bucket == "labeling"


# ---------------------------------------------------------------------------
# Clean scene + evidence-level discrimination matrix
# ---------------------------------------------------------------------------


def test_clean_scene_all_pass(cfg):
    report = sv.evaluate_scene_verify(
        scene_id="pack_1_i2",
        captured=_scene(objects=(_carton(), _item())),
        config=cfg,
        verified_at=VERIFIED_AT,
    )
    assert report.overall_status == "pass"
    assert report.bucket_attribution == {}
    assert all(g.status == "pass" for g in report.gates)


def _report_for_defect(defect: str, cfg) -> sv.SceneVerifyReport:
    fail_div = {"mesh_present": True, "mode": "sampled", "phantom_max_m": 0.03, "clip_max_m": 0.0}
    clip_div = {"mesh_present": True, "mode": "sampled", "phantom_max_m": 0.0, "clip_max_m": 0.03}
    if defect == "oversize_collision_hull":
        scene = _scene(objects=(_carton(), _item(mesh_divergence=fail_div)))
    elif defect == "undersize_collision_hull":
        scene = _scene(objects=(_carton(), _item(mesh_divergence=clip_div)))
    elif defect == "missing_static_tag":
        # Static carton both mistagged AND drifting: settle must still ignore it.
        scene = _scene(objects=(_carton(has_static_tag=False, drifted=True), _item()))
    elif defect == "interpenetration":
        scene = _scene(
            objects=(_carton(), _item()),
            overlaps=(sv.CapturedPairOverlap("item", "target_carton", 0.0005, True),),
        )
    elif defect == "fall_through":
        scene = _scene(objects=(_carton(), _item(aabb_bottom_z=0.50)))
    else:  # pragma: no cover
        raise AssertionError(defect)
    return sv.evaluate_scene_verify(
        scene_id=f"defect_{defect}", captured=scene, config=cfg, verified_at=VERIFIED_AT
    )


EXPECTED_GATE = {
    "oversize_collision_hull": ("visual_collision_agreement", "mesh_disagreement"),
    "undersize_collision_hull": ("visual_collision_agreement", "mesh_disagreement"),
    "missing_static_tag": ("static_metadata_present", "missing_static_metadata"),
    "interpenetration": ("interpenetration", "interpenetration"),
    "fall_through": ("fall_through", "fall_through"),
}


@pytest.mark.parametrize("defect", list(EXPECTED_GATE))
def test_defect_discrimination(defect, cfg):
    expected_gate, expected_bucket = EXPECTED_GATE[defect]
    report = _report_for_defect(defect, cfg)

    assert report.overall_status == "fail", f"{defect} did not fail overall"
    fired = report.gate(expected_gate)
    assert fired is not None and fired.status == "fail", f"{defect}: {expected_gate} did not fire"
    assert fired.bucket == expected_bucket
    assert expected_gate in report.bucket_attribution.get(expected_bucket, [])

    # Exactly one gate fails -> no cross-contamination between root causes.
    failed_gates = [g.gate for g in report.gates if g.status == "fail"]
    assert failed_gates == [expected_gate], f"{defect}: unexpected failures {failed_gates}"


def test_missing_static_tag_routes_to_labeling_not_physics(cfg):
    """The crux separation: a mistagged, drifting static object trips metadata, not physics."""
    report = _report_for_defect("missing_static_tag", cfg)
    assert report.gate("static_metadata_present").status == "fail"
    # Even though the carton drifted 10 cm + 45 deg, the physics gates ignore it.
    assert report.gate("static_settle").status == "pass"
    assert report.gate("fall_through").status == "pass"
    assert "physics_instability" not in report.bucket_attribution


# ---------------------------------------------------------------------------
# USD-level: extraction + injectors (real pxr in the venv)
# ---------------------------------------------------------------------------


def test_usd_subtree_to_trimesh_roundtrip(real_pxr):
    from pxr import Usd

    stage = Usd.Stage.CreateInMemory()
    _author_box_mesh(stage, "/Root/Visual", extents=(0.10, 0.06, 0.04))
    mesh = geom.usd_subtree_to_trimesh(stage, "/Root/Visual")
    assert mesh is not None
    extents = mesh.bounds[1] - mesh.bounds[0]
    assert extents[0] == pytest.approx(0.10, abs=1e-6)
    assert extents[1] == pytest.approx(0.06, abs=1e-6)
    assert extents[2] == pytest.approx(0.04, abs=1e-6)


def test_inject_oversize_scales_extracted_collision(real_pxr):
    from pxr import Usd

    stage = Usd.Stage.CreateInMemory()
    _author_box_mesh(stage, "/Root/Collision", extents=(0.10, 0.06, 0.04))
    base = geom.usd_subtree_to_trimesh(stage, "/Root/Collision")
    base_x = float((base.bounds[1] - base.bounds[0])[0])

    info = defects.inject_oversize_collision_hull(stage, "/Root/Collision", factor=1.5)
    assert info["expected_gate"] == "visual_collision_agreement"
    scaled = geom.usd_subtree_to_trimesh(stage, "/Root/Collision")
    scaled_x = float((scaled.bounds[1] - scaled.bounds[0])[0])
    assert scaled_x == pytest.approx(base_x * 1.5, rel=1e-4)


def test_undersize_injection_drives_clip_through(cfg, real_pxr):
    from pxr import Usd

    stage = Usd.Stage.CreateInMemory()
    _author_box_mesh(stage, "/Root/Visual", extents=(0.10, 0.06, 0.04))
    _author_box_mesh(stage, "/Root/Collision", extents=(0.10, 0.06, 0.04))
    defects.inject_undersize_collision_hull(stage, "/Root/Collision", factor=0.6)

    visual = geom.usd_subtree_to_trimesh(stage, "/Root/Visual")
    collision = geom.usd_subtree_to_trimesh(stage, "/Root/Collision")
    div = geom.directional_mesh_divergence(visual, collision, n_samples=1200)
    gate = sv.evaluate_mesh_agreement_gate({"item": div}, cfg)
    assert gate.status == "fail"
    assert div["clip_max_m"] > cfg.mesh_clip_fail_m


def test_inject_missing_static_tag_flips_scan(real_pxr):
    from pxr import Usd, UsdGeom, UsdPhysics

    stage = Usd.Stage.CreateInMemory()
    xform = UsdGeom.Xform.Define(stage, "/Root/Carton").GetPrim()
    UsdPhysics.RigidBodyAPI.Apply(xform).CreateKinematicEnabledAttr().Set(True)
    assert geom.scan_static_tag(stage, "/Root/Carton") is True

    info = defects.inject_missing_static_tag(stage, "/Root/Carton")
    assert info["expected_bucket"] == "missing_static_metadata"
    assert geom.scan_static_tag(stage, "/Root/Carton") is False


def test_scan_static_tag_articulated_carton(real_pxr):
    """An articulated carton (kinematic base + live flap) is anchored, not a defect.

    Regression for the live Phase-0 false-positive: the prior scan flagged the carton
    because its flap bodies are dynamic. Anchored == any kinematic body present.
    """
    from pxr import Usd, UsdGeom, UsdPhysics

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/Root/Carton")
    base = UsdGeom.Xform.Define(stage, "/Root/Carton/Base").GetPrim()
    UsdPhysics.RigidBodyAPI.Apply(base).CreateKinematicEnabledAttr().Set(True)
    flap = UsdGeom.Xform.Define(stage, "/Root/Carton/Flap").GetPrim()
    UsdPhysics.RigidBodyAPI.Apply(flap).CreateKinematicEnabledAttr().Set(False)

    assert geom.scan_static_tag(stage, "/Root/Carton") is True
    defects.inject_missing_static_tag(stage, "/Root/Carton")
    assert geom.scan_static_tag(stage, "/Root/Carton") is False


def test_collision_mesh_prim_paths(real_pxr):
    """Soundness scales the collision prim only; this helper resolves it (empty when the
    asset has no separately-authored collision mesh)."""
    from pxr import Usd, UsdPhysics

    stage = Usd.Stage.CreateInMemory()
    _author_box_mesh(stage, "/Root/Obj/Visual", extents=(0.10, 0.06, 0.04))
    collision = _author_box_mesh(stage, "/Root/Obj/Collision_hull", extents=(0.10, 0.06, 0.04))
    UsdPhysics.CollisionAPI.Apply(collision)
    assert geom.collision_mesh_prim_paths(stage, "/Root/Obj") == ["/Root/Obj/Collision_hull"]

    bare = Usd.Stage.CreateInMemory()
    _author_box_mesh(bare, "/Root/Obj/Visual", extents=(0.10, 0.06, 0.04))
    assert geom.collision_mesh_prim_paths(bare, "/Root/Obj") == []


def test_inject_fall_through_removes_collision(real_pxr):
    from pxr import Usd, UsdPhysics

    stage = Usd.Stage.CreateInMemory()
    prim = _author_box_mesh(stage, "/Root/Item", extents=(0.05, 0.05, 0.05))
    UsdPhysics.CollisionAPI.Apply(prim)
    assert prim.HasAPI(UsdPhysics.CollisionAPI)

    info = defects.inject_fall_through(stage, "/Root/Item")
    assert info["expected_gate"] == "fall_through"
    assert not prim.HasAPI(UsdPhysics.CollisionAPI)
    assert "/Root/Item" in info["removed_collision_from"]


# ---------------------------------------------------------------------------
# Collision-proxy synthesis (convex-approx assets with no separate collision mesh)
# ---------------------------------------------------------------------------


def test_collision_proxy_convexhull_detects_overapproximation(cfg):
    # Non-convex single mesh (two separated boxes): the convex hull bridges the empty gap.
    b1 = trimesh.creation.box(extents=[0.04, 0.04, 0.04])
    b1.apply_translation([-0.05, 0.0, 0.0])
    b2 = trimesh.creation.box(extents=[0.04, 0.04, 0.04])
    b2.apply_translation([0.05, 0.0, 0.0])
    dumbbell = trimesh.util.concatenate([b1, b2])

    proxy, synthesized = geom._collision_proxy(dumbbell, "convexHull")
    assert synthesized is True
    div = geom.directional_mesh_divergence(
        dumbbell, proxy, n_samples=1500, force_sample=synthesized
    )
    assert div["mode"] == "sampled"  # forced past the AABB pre-pass (hull shares the AABB)
    assert div["phantom_max_m"] > cfg.mesh_phantom_fail_m  # hull over-approximates the gap
    gate = sv.evaluate_mesh_agreement_gate({"o": div}, cfg)
    assert gate.status == "fail" and gate.bucket == "mesh_disagreement"

    # A convex mesh's hull equals itself -> agreement; high-fidelity modes don't synthesize.
    box = trimesh.creation.box(extents=[0.10, 0.06, 0.04])
    cproxy, csynth = geom._collision_proxy(box, "convexHull")
    cdiv = geom.directional_mesh_divergence(box, cproxy, n_samples=1500, force_sample=csynth)
    assert cdiv["phantom_max_m"] == 0.0
    assert geom._collision_proxy(box, "sdf")[1] is False


def test_object_mesh_divergence_synthesizes_proxy_for_collisionapi_mesh(real_pxr):
    """A renderable mesh whose collider is a runtime approximation (no separate collision
    mesh) now yields a real divergence instead of a 'missing' labeling punt."""
    from pxr import Usd, UsdPhysics

    stage = Usd.Stage.CreateInMemory()
    visual = _author_box_mesh(stage, "/Root/Obj/Visual", extents=(0.10, 0.06, 0.04))
    UsdPhysics.CollisionAPI.Apply(visual)
    UsdPhysics.MeshCollisionAPI.Apply(visual).CreateApproximationAttr().Set("convexHull")
    div = geom.object_mesh_divergence(stage, "/Root/Obj", n_samples=800)
    assert div["mesh_present"] is True
    assert div["mode"] == "sampled"  # synthesized proxy forces sampling (box hull == box)

    # No collider authored at all -> genuinely missing (labeling warn).
    bare = Usd.Stage.CreateInMemory()
    _author_box_mesh(bare, "/Root/Obj/Visual", extents=(0.10, 0.06, 0.04))
    bdiv = geom.object_mesh_divergence(bare, "/Root/Obj", n_samples=800)
    assert bdiv["mesh_present"] is False and bdiv["mode"] == "missing"


def _author_box_mesh_wound(stage, path, *, extents, translate=(0.0, 0.0, 0.0), inward=False):
    """Author a box with COHERENT winding — outward by default, fully inward on request.

    Unlike ``_author_box_mesh`` (whose quad order is mixed), this controls winding
    deterministically so the normalization in ``_mesh_prim_to_trimesh`` can be regression-
    tested against the exact inward-wound geometry the external corpus shipped with.
    """
    from pxr import Gf, UsdGeom

    mesh = UsdGeom.Mesh.Define(stage, path)
    hx, hy, hz = (e / 2.0 for e in extents)
    points = [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ]
    outward_quads = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),  # bottom (-z), top (+z)
        (0, 1, 5, 4),
        (1, 2, 6, 5),  # front (-y), right (+x)
        (2, 3, 7, 6),
        (3, 0, 4, 7),  # back (+y), left (-x)
    ]
    quads = [tuple(reversed(q)) for q in outward_quads] if inward else outward_quads
    mesh.CreatePointsAttr([Gf.Vec3f(*p) for p in points])
    mesh.CreateFaceVertexCountsAttr([4] * 6)
    mesh.CreateFaceVertexIndicesAttr([i for q in quads for i in q])
    if any(translate):
        UsdGeom.Xformable(mesh).AddTranslateOp().Set(Gf.Vec3d(*translate))
    return mesh.GetPrim()


def test_inward_wound_authored_hull_reports_phantom_not_clip(real_pxr, cfg):
    """Winding regression (surfaced live on the external corpus): with BOTH meshes wound
    inward, the normal-based signed distance flipped every sign and reported the oversized
    authored hull as ``clip`` instead of ``phantom``. Ground truth: the hull strictly
    contains the visual => phantom > 0, clip == 0."""
    from pxr import Usd

    stage = Usd.Stage.CreateInMemory()
    _author_box_mesh_wound(stage, "/Root/Obj/Visual", extents=(0.08, 0.08, 0.08), inward=True)
    _author_box_mesh_wound(stage, "/Root/Obj/Collision", extents=(0.12, 0.12, 0.12), inward=True)
    div = geom.object_mesh_divergence(stage, "/Root/Obj", n_samples=1500)
    assert div["mode"] == "sampled"
    assert div["phantom_max_m"] > cfg.mesh_phantom_fail_m  # >=2 cm hull margin
    assert div["clip_max_m"] < 0.005  # visual strictly inside the hull -> no clip

    gate = sv.evaluate_mesh_agreement_gate({"o": div}, cfg)
    assert gate.status == "fail" and gate.bucket == "mesh_disagreement"


def test_authored_collider_sharing_aabb_is_sampled_not_aabb_masked(real_pxr, cfg):
    """AABB-pre-pass regression: a separately-AUTHORED collider that shares the visual's
    AABB (the authored-convex-hull-of-a-concave-visual pattern) used to short-circuit to
    ``aabb_only`` with ~0 divergence, masking the interior bulge. Authored colliders must
    force sampling exactly like synthesized proxies."""
    from pxr import Usd

    stage = Usd.Stage.CreateInMemory()
    # Concave visual: two cubes with a 6 cm empty gap between them.
    _author_box_mesh_wound(
        stage, "/Root/Obj/VisualA", extents=(0.04, 0.04, 0.04), translate=(-0.05, 0.0, 0.0)
    )
    _author_box_mesh_wound(
        stage, "/Root/Obj/VisualB", extents=(0.04, 0.04, 0.04), translate=(0.05, 0.0, 0.0)
    )
    # Authored hull box spanning both: byte-identical AABB to the visual union.
    _author_box_mesh_wound(stage, "/Root/Obj/Collision", extents=(0.14, 0.04, 0.04))
    div = geom.object_mesh_divergence(stage, "/Root/Obj", n_samples=1500)
    assert div["mode"] == "sampled"  # NOT "aabb_only" — the previously-masked path
    assert div["phantom_max_m"] > cfg.mesh_phantom_fail_m  # hull bridges the empty gap

    gate = sv.evaluate_mesh_agreement_gate({"o": div}, cfg)
    assert gate.status == "fail" and gate.bucket == "mesh_disagreement"


# ---------------------------------------------------------------------------
# Mesh/contact-level interpenetration (the corpus refinement)
# ---------------------------------------------------------------------------


def test_mesh_pair_penetration_depth_distinguishes_corner_clip_from_clash():
    """Two spheres whose AABB cubes overlap at a corner but never touch -> depth 0; the
    corpus surfaced exactly this as a 7 mm³ AABB false-positive. A real overlap -> depth>0."""
    a = trimesh.creation.icosphere(subdivisions=3, radius=0.05)
    # Diagonal offset so the [0.10]^3 AABBs overlap a sliver at the corner while the
    # sphere surfaces stay ~2.6 cm apart (center distance 0.156 m > sum of radii 0.10 m).
    b = trimesh.creation.icosphere(subdivisions=3, radius=0.05)
    b.apply_translation([0.09, 0.09, 0.09])
    a_min, a_max = a.bounds
    b_min, b_max = b.bounds
    assert not (any(a_min > b_max) or any(b_min > a_max))  # AABBs do overlap
    assert geom.mesh_pair_penetration_depth_m(a, b, n_samples=4000) == pytest.approx(0.0, abs=1e-3)

    # Now genuinely interpenetrating (centers 0.05 m apart << sum of radii 0.10 m).
    c = trimesh.creation.icosphere(subdivisions=3, radius=0.05)
    c.apply_translation([0.05, 0.0, 0.0])
    assert geom.mesh_pair_penetration_depth_m(a, c, n_samples=4000) > 0.01


def test_sampled_divergence_is_reproducible():
    """Seeded surface sampling makes a sampled verdict deterministic: the same geometry must
    yield identical phantom/clip numbers run-to-run, so a value near a gate threshold (e.g.
    book_brick at the 0.015 phantom line) no longer flaps warn<->fail between runs."""
    b1 = trimesh.creation.box([0.04, 0.04, 0.04])
    b1.apply_translation([-0.05, 0.0, 0.0])
    b2 = trimesh.creation.box([0.04, 0.04, 0.04])
    b2.apply_translation([0.05, 0.0, 0.0])
    dumbbell = trimesh.util.concatenate([b1, b2])
    hull = dumbbell.convex_hull
    r1 = geom.directional_mesh_divergence(dumbbell, hull, n_samples=2000, force_sample=True)
    r2 = geom.directional_mesh_divergence(dumbbell, hull, n_samples=2000, force_sample=True)
    assert r1["mode"] == "sampled" and r1 == r2

    a = trimesh.creation.icosphere(subdivisions=3, radius=0.05)
    c = trimesh.creation.icosphere(subdivisions=3, radius=0.05)
    c.apply_translation([0.05, 0.0, 0.0])
    assert geom.mesh_pair_penetration_depth_m(
        a, c, n_samples=3000
    ) == geom.mesh_pair_penetration_depth_m(a, c, n_samples=3000)


def test_object_mesh_divergence_is_pose_invariant_and_scale_correct(real_pxr):
    """An object's visual-vs-collision divergence is intrinsic to the asset and must not change
    with its scene orientation, but MUST scale with the asset's world scale (canonicalising should
    remove orientation, not scale — reporting authored pre-scale sizes would be ~30x off, the bug
    the first naive fix introduced). A boundingSphere proxy is the sharp probe: its radius derives
    from the mesh AABB, which grows under rotation in world frame but is orientation-invariant in
    canonical frame."""
    from pxr import Gf, Usd, UsdGeom, UsdPhysics

    def divergence(*, rotate_z_deg: float = 0.0, scale: float = 1.0) -> dict:
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/Root/Obj")
        visual = _author_box_mesh(stage, "/Root/Obj/Visual", extents=(0.10, 0.06, 0.04))
        UsdPhysics.CollisionAPI.Apply(visual)
        UsdPhysics.MeshCollisionAPI.Apply(visual).CreateApproximationAttr().Set("boundingSphere")
        xf = UsdGeom.Xformable(stage.GetPrimAtPath("/Root/Obj"))
        if rotate_z_deg:
            xf.AddRotateZOp().Set(rotate_z_deg)
        if scale != 1.0:
            xf.AddScaleOp().Set(Gf.Vec3f(scale, scale, scale))
        return geom.object_mesh_divergence(stage, "/Root/Obj", n_samples=1500)

    base = divergence()
    assert base["mode"] == "sampled" and base["phantom_max_m"] > 0.0  # sphere over-approximates
    # Orientation-invariant.
    assert base["phantom_max_m"] == pytest.approx(
        divergence(rotate_z_deg=37.0)["phantom_max_m"], abs=1e-5
    )
    assert base["clip_max_m"] == pytest.approx(
        divergence(rotate_z_deg=37.0)["clip_max_m"], abs=1e-5
    )
    # Scale-correct: divergence reported in WORLD units, so 2x scale -> ~2x divergence
    # (not removed).
    scaled = divergence(scale=2.0, rotate_z_deg=37.0)
    assert scaled["phantom_max_m"] == pytest.approx(2.0 * base["phantom_max_m"], rel=1e-3)


def test_object_mesh_divergence_invariant_to_settle_tumble_on_subprim(real_pxr):
    """The live case: the orientation lives on a descendant body prim (a rigid body settling to a
    different orientation than its object-root parent), and it is a full off-axis tumble, not just
    yaw. Canonicalising to the first mesh prim's own world transform keeps the divergence invariant
    regardless — this is what closed the book_brick cross-row residual."""
    from pxr import Gf, Usd, UsdGeom, UsdPhysics

    def divergence(tumble: bool) -> dict:
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/Root/Obj")  # object root: identity, fixed
        UsdGeom.Xform.Define(stage, "/Root/Obj/Body")  # descendant body: carries the pose
        visual = _author_box_mesh(stage, "/Root/Obj/Body/Visual", extents=(0.10, 0.06, 0.04))
        UsdPhysics.CollisionAPI.Apply(visual)
        UsdPhysics.MeshCollisionAPI.Apply(visual).CreateApproximationAttr().Set("boundingSphere")
        if tumble:
            # Off-axis rotation (roll+pitch+yaw), like a settled tumble — not just a Z spin.
            op = UsdGeom.Xformable(stage.GetPrimAtPath("/Root/Obj/Body")).AddRotateXYZOp()
            op.Set(Gf.Vec3f(41.0, -29.0, 63.0))
        return geom.object_mesh_divergence(stage, "/Root/Obj", n_samples=1500)

    base = divergence(False)
    tumbled = divergence(True)
    assert base["phantom_max_m"] > 0.0
    assert base["phantom_max_m"] == pytest.approx(tumbled["phantom_max_m"], abs=1e-5)
    assert base["clip_max_m"] == pytest.approx(tumbled["clip_max_m"], abs=1e-5)


def test_mesh_pair_penetration_propagates_sampling_failure(monkeypatch):
    """A sampling failure on non-degenerate meshes must propagate (not be swallowed as 0.0)
    so the USD wrapper routes the pair to the AABB-volume fallback instead of a silent pass."""
    a = trimesh.creation.box([0.1, 0.1, 0.1])
    b = trimesh.creation.box([0.1, 0.1, 0.1])  # overlapping AABB -> reaches the sampling path

    def boom(*_a, **_k):
        raise RuntimeError("sample failed")

    monkeypatch.setattr(geom, "_sample_surface", boom)
    with pytest.raises(RuntimeError):
        geom.mesh_pair_penetration_depth_m(a, b)


def _overlap(depth):
    # AABB volume kept above the legacy floor so the ONLY thing that can clear the pair is
    # the mesh-depth signal — this isolates the refinement.
    return sv.CapturedPairOverlap("item_a", "item_b", 0.0005, True, penetration_depth_m=depth)


def test_interpenetration_gate_passes_aabb_clip_with_zero_mesh_depth(cfg):
    """The headline fix: an AABB overlap above the volume floor but with ~0 mesh penetration
    no longer fails — it is a bounding-box corner-clip of validly placed items."""
    scene = _scene(objects=(_carton(), _item()), overlaps=(_overlap(0.0005),))
    report = sv.evaluate_scene_verify(
        scene_id="clip", captured=scene, config=cfg, verified_at=VERIFIED_AT
    )
    assert report.gate("interpenetration").status == "pass"


def test_interpenetration_gate_fails_real_mesh_penetration(cfg):
    scene = _scene(objects=(_carton(), _item()), overlaps=(_overlap(0.02),))
    report = sv.evaluate_scene_verify(
        scene_id="clash", captured=scene, config=cfg, verified_at=VERIFIED_AT
    )
    gate = report.gate("interpenetration")
    assert gate.status == "fail"
    assert gate.detail["offenders"][0]["basis"] == "mesh_penetration"


def test_interpenetration_gate_falls_back_to_aabb_when_depth_absent(cfg):
    """No mesh depth captured (e.g. a pair with no usable collision geometry) -> the gate
    still guards via the coarse AABB-volume floor rather than silently passing."""
    overlap = sv.CapturedPairOverlap("item_a", "item_b", 0.0005, True, penetration_depth_m=None)
    scene = _scene(objects=(_carton(), _item()), overlaps=(overlap,))
    report = sv.evaluate_scene_verify(
        scene_id="fallback", captured=scene, config=cfg, verified_at=VERIFIED_AT
    )
    gate = report.gate("interpenetration")
    assert gate.status == "fail"
    assert gate.detail["offenders"][0]["basis"] == "aabb_volume_fallback"
