"""Venv-only tests for the generic SceneBundle contract (no Isaac, no pxr).

The bundle is the seam that lets the verifier grade an arbitrary USD scene rather than only
a PackingBench manifest row, so its parsing/validation must be airtight and its
``objects_meta`` projection must match the shape ``capture_scene_evidence`` consumes.
"""

from __future__ import annotations

import json

import pytest

from app.scene_verify.bundle import (
    STATIC_PHYSICS_MODES,
    SceneBundle,
    SceneBundleError,
    SceneObjectSpec,
)


def _valid_mapping() -> dict:
    return {
        "scene_id": "demo_scene",
        "usd_stage_path": "scenes/demo/demo.usd",
        "support_prim_path": "/World/table",
        "objects": [
            {
                "object_id": "carton",
                "prim_path": "/World/carton",
                "is_static_expected": True,
            },
            {
                "object_id": "box",
                "prim_path": "/World/box",
                "position": [0.1, 0.2, 0.3],
            },
        ],
    }


def test_from_mapping_parses_objects_and_support():
    bundle = SceneBundle.from_mapping(_valid_mapping())
    assert bundle.scene_id == "demo_scene"
    assert bundle.usd_stage_path == "scenes/demo/demo.usd"
    assert bundle.support_prim_path == "/World/table"
    assert [o.object_id for o in bundle.objects] == ["carton", "box"]
    assert bundle.objects[0].is_static_expected is True
    assert bundle.objects[1].is_static_expected is False
    assert bundle.objects[1].position == (0.1, 0.2, 0.3)


def test_from_json_file_round_trip(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(_valid_mapping()), encoding="utf-8")
    bundle = SceneBundle.from_json_file(path)
    assert bundle.scene_id == "demo_scene"
    assert len(bundle.objects) == 2


def test_static_expected_derived_from_physics_mode():
    mode = sorted(STATIC_PHYSICS_MODES)[0]
    spec = SceneObjectSpec.from_mapping(
        {"object_id": "c", "prim_path": "/World/c", "physics_mode": mode}
    )
    assert spec.is_static_expected is True


def test_explicit_static_flag_overrides_physics_mode():
    mode = sorted(STATIC_PHYSICS_MODES)[0]
    # Explicit False must win even when the physics_mode would imply static.
    spec = SceneObjectSpec.from_mapping(
        {
            "object_id": "c",
            "prim_path": "/World/c",
            "physics_mode": mode,
            "is_static_expected": False,
        }
    )
    assert spec.is_static_expected is False


def test_to_meta_shape_matches_capture_contract():
    spec = SceneObjectSpec.from_mapping(
        {
            "object_id": "box",
            "prim_path": "/World/box",
            "pose_center_offset_xyz_m": [0.0, 0.0, 0.05],
            "position": [1.0, 2.0, 3.0],
        }
    )
    meta = spec.to_meta()
    # Keys must exactly match scripts/tools/verify_scene_bundle._meta so the shared capture
    # layer treats bundle-built objects identically to manifest-built ones.
    assert set(meta) == {
        "object_id",
        "prim_path",
        "pose_prim_path",
        "pose_center_offset_xyz_m",
        "position",
        "physics_mode",
        "is_static_expected",
    }
    # pose_prim_path defaults to prim_path when not given.
    assert meta["pose_prim_path"] == "/World/box"
    assert meta["pose_center_offset_xyz_m"] == [0.0, 0.0, 0.05]
    assert meta["position"] == [1.0, 2.0, 3.0]


def test_objects_meta_and_dynamic_specs():
    bundle = SceneBundle.from_mapping(_valid_mapping())
    metas = bundle.objects_meta()
    assert [m["object_id"] for m in metas] == ["carton", "box"]
    dynamic = bundle.dynamic_object_specs()
    assert [s.object_id for s in dynamic] == ["box"]  # carton is static-expected


def test_settle_steps_override_accepted_and_validated():
    mapping = _valid_mapping()
    mapping["settle_steps"] = 120
    assert SceneBundle.from_mapping(mapping).settle_steps == 120


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda m: m.pop("scene_id"), "scene_id"),
        (lambda m: m.pop("usd_stage_path"), "usd_stage_path"),
        (lambda m: m.update(objects=[]), "at least one object"),
        (lambda m: m.update(objects="nope"), "must be a list"),
        (lambda m: m.update(support_prim_path="relative/path"), "absolute prim path"),
        (lambda m: m.update(settle_steps=-5), "non-negative"),
        (lambda m: m.update(settle_steps=True), "non-negative"),
    ],
)
def test_invalid_bundle_rejected(mutate, message):
    mapping = _valid_mapping()
    mutate(mapping)
    with pytest.raises(SceneBundleError) as exc:
        SceneBundle.from_mapping(mapping)
    assert message in str(exc.value)


def test_duplicate_object_id_rejected():
    mapping = _valid_mapping()
    mapping["objects"][1]["object_id"] = "carton"
    with pytest.raises(SceneBundleError) as exc:
        SceneBundle.from_mapping(mapping)
    assert "duplicate object_id" in str(exc.value)


@pytest.mark.parametrize(
    "obj, message",
    [
        ({"prim_path": "/World/x"}, "object_id"),
        ({"object_id": "x"}, "prim_path"),
        ({"object_id": "x", "prim_path": "relative"}, "absolute USD 'prim_path'"),
        (
            {"object_id": "x", "prim_path": "/World/x", "position": [1, 2]},
            "3-number",
        ),
        (
            {"object_id": "x", "prim_path": "/World/x", "pose_prim_path": "rel"},
            "absolute prim path",
        ),
    ],
)
def test_invalid_object_spec_rejected(obj, message):
    with pytest.raises(SceneBundleError) as exc:
        SceneObjectSpec.from_mapping(obj)
    assert message in str(exc.value)
