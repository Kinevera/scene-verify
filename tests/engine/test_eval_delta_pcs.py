"""Lock the executed eval-delta claim into CI.

The Stage-3 headline is: given a genuinely-packed scene, the canonical PCS scorer is blind to
a collision-vs-visual mismatch (it never reads collision geometry) but DOES co-detect a physics
fall-through (it reads the post-settle pose). These tests drive the UNMODIFIED
``Pack1Task.get_success_evaluator`` and assert exactly that per-class behavior — no Isaac, no policy.

The falsifiable lock is ``test_collision_divergence_field_is_ignored_by_pcs``: it feeds the
scorer a state that EXPLICITLY carries a collision-divergence report and asserts the score is
unchanged. If the scoring contract ever grows a collision-agreement input and penalizes it,
that assertion fails — the signal we want. (Scoring two identical states is NOT such a signal
and is not claimed as one.)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "tools" / "run_eval_delta_pcs.py"
)


def _load_harness():
    spec = importlib.util.spec_from_file_location("run_eval_delta_pcs", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CARTON = "target_carton"
ITEM = "warehouse_brick"
META = {
    "carton_inner_dimensions_xyz_m": [0.30, 0.22, 0.17],
    "semantic_runtime_object_pairs": [
        {"runtime_asset_id": ITEM, "dimensions_xyz_m": [0.16, 0.08, 0.06]}
    ],
    "inside_box_wall_clearance_tolerance_m": 0.005,
    "closure_plane_clearance_m": 0.01,
    "stability_max_linear_displacement_m": 0.01,
    "stability_max_angular_displacement_deg": 5.0,
    "critical_protrusion_above_rim_m": 0.02,
    "requires_closure": False,
}


def test_fits_upright_and_lying():
    h = _load_harness()
    # brick fits upright.
    fits, _ = h._fits((0.16, 0.08, 0.06), (0.30, 0.22, 0.17), 0.005)
    assert fits is True
    # an object taller than the carton in every axis does not fit.
    fits, _ = h._fits((0.5, 0.5, 0.5), (0.30, 0.22, 0.17), 0.005)
    assert fits is False


def test_packed_scene_scores_full_success():
    h = _load_harness()
    state = h._packed_final_state(CARTON, ITEM, META, drop_settle=False)
    success, pcs, diag = h._score(CARTON, ITEM, state)
    assert success is True
    assert pcs == pytest.approx(1.0)
    assert diag["inside_box"][ITEM] is True
    assert diag["stable_after_settle"][ITEM] is True


def test_collision_defect_is_invisible_to_pcs():
    """The collision defect lives only in collision geometry, absent from final_state, so every
    scorer input is identical -> PCS stays at full success. NOTE: on its own this comparison is
    an identity (two equal states score equally); the falsifiable half of the PCS-blindness
    claim is the next test. This one pins the executed number: packed => full success."""
    h = _load_harness()
    valid = h._packed_final_state(CARTON, ITEM, META, drop_settle=False)
    _, pcs_valid, _ = h._score(CARTON, ITEM, valid)
    defect = h._packed_final_state(CARTON, ITEM, META, drop_settle=False)
    _, pcs_defect, _ = h._score(CARTON, ITEM, defect)
    assert pcs_valid == pytest.approx(1.0)
    assert pcs_defect == pytest.approx(pcs_valid)


def test_collision_divergence_field_is_ignored_by_pcs():
    """The FALSIFIABLE lock on PCS collision-blindness: hand the scorer a final_state that
    explicitly reports a huge collision-vs-visual divergence, in every plausible location the
    contract could read it from. If the scoring contract ever grows a collision-agreement
    input and penalizes it, this equality breaks — exactly the signal we want."""
    h = _load_harness()
    baseline = h._packed_final_state(CARTON, ITEM, META, drop_settle=False)
    _, pcs_baseline, _ = h._score(CARTON, ITEM, baseline)

    divergent = h._packed_final_state(CARTON, ITEM, META, drop_settle=False)
    report = {"phantom_max_m": 0.5, "clip_max_m": 0.5, "status": "fail"}
    divergent["collision_divergence"] = dict(report)
    divergent["packingbench"]["collision_divergence"] = dict(report)
    divergent["objects"][ITEM]["collision_divergence"] = dict(report)
    _, pcs_divergent, _ = h._score(CARTON, ITEM, divergent)

    assert pcs_baseline == pytest.approx(1.0)
    assert pcs_divergent == pytest.approx(pcs_baseline)  # scorer has no collision input


def test_fall_through_is_co_detected_by_pcs():
    """Physics divergence moves the post-settle pose, which PCS reads -> stability fails -> PCS drops."""
    h = _load_harness()
    fall = h._packed_final_state(CARTON, ITEM, META, drop_settle=True)
    success, pcs, diag = h._score(CARTON, ITEM, fall)
    assert success is False
    assert pcs < 1.0
    assert diag["stable_after_settle"][ITEM] is False
