"""Locks for verifier v0.2: reconstruction-fidelity gates + authored-phase interpenetration.

Two structural holes disclosed by the v0.1 natural-corpus writeup are closed here, and these
tests are the falsifiable form of that claim:

* **Fidelity**: a degenerate-but-self-consistent reconstruction (the 109-face shell) passed
  every physics gate. The ``recon_surface_density`` / ``recon_registration_coverage`` gates
  grade fidelity — and apply ONLY to scenes that declare reconstruction provenance, so
  curated benchmark verdicts are unchanged.
* **Authored interpenetration**: PhysX depenetrates authored overlaps within the first settle
  steps, so a post-settle capture alone is structurally blind to them. The gate now grades a
  t=0 (``authored``) capture alongside the settled one.
"""

from __future__ import annotations

import pytest

from scene_verify import core as sv


@pytest.fixture()
def cfg() -> sv.VerifyThresholds:
    return sv.load_verify_thresholds(None)


def _object(object_id: str = "box", **overrides):
    defaults = dict(
        object_id=object_id,
        is_static_expected=False,
        pose_before={"position": [0, 0, 0.1], "rotation": [1, 0, 0, 0]},
        pose_after={"position": [0, 0, 0.1], "rotation": [1, 0, 0, 0]},
        aabb_after=[0.0, 0.0, 0.0, 0.1, 0.1, 0.1],
        mesh_divergence={
            "mesh_present": True,
            "mode": "aabb_only",
            "phantom_max_m": 0.0,
            "clip_max_m": 0.0,
        },
    )
    defaults.update(overrides)
    return sv.CapturedObjectEvidence(**defaults)


def _evidence(**overrides) -> sv.CapturedSceneEvidence:
    defaults = dict(
        objects=(_object("box_a"), _object("box_b", aabb_after=[0.2, 0.0, 0.0, 0.3, 0.1, 0.1])),
        load_ok=True,
        load_detail={"object_count": 2},
        table_top_z_m=0.0,
        pairwise_overlaps=(),
        pairwise_overlaps_pre_settle=(),
    )
    defaults.update(overrides)
    return sv.CapturedSceneEvidence(**defaults)


def _report(captured: sv.CapturedSceneEvidence, cfg: sv.VerifyThresholds) -> sv.SceneVerifyReport:
    return sv.evaluate_scene_verify(
        scene_id="unit", captured=captured, config=cfg, verified_at="2026-07-06T00:00:00+00:00"
    )


# ---------------------------------------------------------------------------
# Authored-phase (t=0) interpenetration
# ---------------------------------------------------------------------------


def test_authored_overlap_fires_even_when_settled_capture_is_clean(cfg):
    """The PhysX-depenetration blindness lock: an overlap present at t=0 but resolved by
    settle MUST still fail the gate — this is exactly the case the post-settle capture
    alone could never see."""
    authored = sv.CapturedPairOverlap(
        "box_a",
        "box_b",
        overlap_volume_m3=1e-5,
        geometry_overlap_detected=True,
        penetration_depth_m=0.03,
    )
    report = _report(_evidence(pairwise_overlaps_pre_settle=(authored,)), cfg)
    gate = report.gate("interpenetration")
    assert gate.status == "fail"
    assert gate.detail["offenders"][0]["phase"] == "authored"


def test_settled_overlap_still_fires_and_is_phase_labelled(cfg):
    settled = sv.CapturedPairOverlap(
        "box_a",
        "box_b",
        overlap_volume_m3=1e-5,
        geometry_overlap_detected=True,
        penetration_depth_m=0.03,
    )
    report = _report(_evidence(pairwise_overlaps=(settled,)), cfg)
    gate = report.gate("interpenetration")
    assert gate.status == "fail"
    assert gate.detail["offenders"][0]["phase"] == "settled"


def test_clean_two_phase_capture_passes(cfg):
    clean = sv.CapturedPairOverlap(
        "box_a", "box_b", overlap_volume_m3=0.0, geometry_overlap_detected=False
    )
    report = _report(
        _evidence(pairwise_overlaps=(clean,), pairwise_overlaps_pre_settle=(clean,)), cfg
    )
    assert report.gate("interpenetration").status == "pass"


def test_authored_corner_clip_with_zero_mesh_depth_passes(cfg):
    """The AABB-corner-clip false-positive guard applies at the authored phase too."""
    clip = sv.CapturedPairOverlap(
        "box_a",
        "box_b",
        overlap_volume_m3=7e-9,
        geometry_overlap_detected=True,
        penetration_depth_m=0.0,
    )
    report = _report(_evidence(pairwise_overlaps_pre_settle=(clip,)), cfg)
    assert report.gate("interpenetration").status == "pass"


# ---------------------------------------------------------------------------
# Fidelity gate applicability
# ---------------------------------------------------------------------------


def test_fidelity_gates_absent_without_reconstruction_declaration(cfg):
    """A curated (non-reconstruction) scene's verdict is byte-compatible with v0.1: exactly
    the six physics gates, no fidelity rows."""
    report = _report(_evidence(), cfg)
    names = [g.gate for g in report.gates]
    assert names == [
        "scene_load",
        "visual_collision_agreement",
        "interpenetration",
        "static_settle",
        "fall_through",
        "static_metadata_present",
    ]


def test_fidelity_gates_present_with_reconstruction_declaration(cfg):
    fidelity = {
        "declared": {"registered_images": 90, "total_frames": 90},
        "measured": {"face_count": 1_564_909, "area_ratio": 0.1269},
    }
    report = _report(_evidence(recon_fidelity=fidelity), cfg)
    names = [g.gate for g in report.gates]
    assert "recon_registration_coverage" in names
    assert "recon_surface_density" in names
    assert report.gate("recon_registration_coverage").status == "pass"
    assert report.gate("recon_surface_density").status == "pass"


# ---------------------------------------------------------------------------
# Registration-coverage thresholds (calibrated on the natural pilot corpus)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("registered", "total", "expected"),
    [
        (10, 90, "fail"),  # wh_secret: 0.111 — built from a sliver of the footage
        (17, 90, "warn"),  # wh_forklift_aisle: 0.189
        (10, 44, "warn"),  # wh_aisle_picker: 0.227
        (47, 90, "pass"),  # wh_coach_factory: 0.522
        (90, 90, "pass"),  # wh_garage_shop: 1.0
    ],
)
def test_registration_coverage_bands(cfg, registered, total, expected):
    gate = sv.build_recon_registration_gate(
        {"declared": {"registered_images": registered, "total_frames": total}}, cfg
    )
    assert gate.status == expected
    assert gate.bucket == "reconstruction_fidelity"
    assert gate.detail["basis"] == "declared_by_producer"


def test_registration_coverage_fails_closed_when_not_declared(cfg):
    gate = sv.build_recon_registration_gate({"declared": {}}, cfg)
    assert gate.status == "warn"


# ---------------------------------------------------------------------------
# Surface-density thresholds (calibrated on the natural pilot corpus)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("face_count", "area_ratio", "expected"),
    [
        (109, 0.0007, "fail"),  # wh_secret: the degenerate shell that passed v0.1
        (443, 0.0001, "fail"),  # wh_fabric
        (1114, 0.0025, "fail"),  # wh_forklift_aisle
        (42_315, 0.0164, "warn"),  # wh_aisle_picker: partial but usable
        (171_932, 0.05, "pass"),  # wh_coach_factory
        (1_564_909, 0.1269, "pass"),  # wh_garage_shop
        (100_000, 0.001, "warn"),  # dense faces but sliver coverage: area-ratio co-signal
    ],
)
def test_surface_density_bands(cfg, face_count, area_ratio, expected):
    gate = sv.build_recon_density_gate(
        {"measured": {"face_count": face_count, "area_ratio": area_ratio}}, cfg
    )
    assert gate.status == expected
    assert gate.bucket == "reconstruction_fidelity"
    assert gate.detail["basis"] == "measured_from_stage"


def test_surface_density_fails_closed_when_not_measured(cfg):
    gate = sv.build_recon_density_gate({"measured": {}}, cfg)
    assert gate.status == "warn"


def test_degenerate_shell_scene_now_fails_overall(cfg):
    """The v0.1 fidelity-boundary example, closed: wh_secret's numbers make the verdict FAIL."""
    fidelity = {
        "declared": {"registered_images": 10, "total_frames": 90},
        "measured": {"face_count": 109, "area_ratio": 0.0007},
    }
    report = _report(_evidence(recon_fidelity=fidelity), cfg)
    assert report.overall_status == "fail"
    assert report.bucket_attribution.get("reconstruction_fidelity") == [
        "recon_registration_coverage",
        "recon_surface_density",
    ]


# ---------------------------------------------------------------------------
# Thresholds backward compatibility
# ---------------------------------------------------------------------------


def test_thresholds_mapping_without_fidelity_section_loads_defaults():
    """A pre-0.2 external thresholds override file (no ``fidelity:`` key) must keep loading."""
    base = sv.load_verify_thresholds(None)
    stripped = {
        "scene_verify": {
            "settle": {
                "settle_steps": base.settle_steps,
                "max_linear_displacement_m": base.max_linear_displacement_m,
                "max_angular_displacement_deg": base.max_angular_displacement_deg,
                "pose_alignment_tolerance_m": base.pose_alignment_tolerance_m,
                "table_contact_tolerance_m": base.table_contact_tolerance_m,
            },
            "mesh_agreement": {
                "n_samples": base.mesh_n_samples,
                "bvh_skip_margin_m": base.mesh_bvh_skip_margin_m,
                "phantom_warn_m": base.mesh_phantom_warn_m,
                "phantom_fail_m": base.mesh_phantom_fail_m,
                "clip_warn_m": base.mesh_clip_warn_m,
                "clip_fail_m": base.mesh_clip_fail_m,
            },
            "interpenetration": {
                "max_penetration_depth_m": base.interpenetration_max_penetration_depth_m,
                "max_overlap_volume_m3": base.interpenetration_max_overlap_volume_m3,
            },
            "fall_through": {
                "max_bottom_below_table_m": base.fall_through_max_bottom_below_table_m,
            },
            "defects": {
                "oversize_factor": base.defect_oversize_factor,
                "undersize_factor": base.defect_undersize_factor,
                "interpenetration_overlap_m": base.defect_interpenetration_overlap_m,
            },
        }
    }
    loaded = sv.VerifyThresholds.from_mapping(stripped)
    assert loaded.fidelity_min_face_count_fail == base.fidelity_min_face_count_fail
    assert loaded.fidelity_min_registered_ratio_warn == base.fidelity_min_registered_ratio_warn


def test_nan_penetration_depth_falls_back_to_aabb_floor(cfg):
    """The live-caught fail-open: degenerate signed-distance sampling yields NaN, and
    ``NaN > tolerance`` is False — the pair must fall back to the AABB-volume floor
    instead of silently passing. (Caught by the pack_3_dense_close_i1 soundness matrix:
    a 0.000293 m³ injected overlap with NaN depth fired no offender.)"""
    import math as _math

    nan_pair = sv.CapturedPairOverlap(
        "box_a",
        "box_b",
        overlap_volume_m3=0.000293,
        geometry_overlap_detected=True,
        penetration_depth_m=_math.nan,
    )
    for evidence in (
        _evidence(pairwise_overlaps_pre_settle=(nan_pair,)),
        _evidence(pairwise_overlaps=(nan_pair,)),
    ):
        gate = _report(evidence, cfg).gate("interpenetration")
        assert gate.status == "fail"
        assert gate.detail["offenders"][0]["basis"] == "aabb_volume_fallback"
