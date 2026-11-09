"""The generic runner, ``scene_verify.runners.usd_bundle``, without Isaac Sim.

The runner moved here from RoboEval's ``scripts/tools/verify_usd_bundle.py`` with its Isaac
Sim 5.1 API untouched. These tests stub ``carb``, ``isaacsim`` and ``omni`` (the
``isaac_stubs`` fixture) and keep ``pxr`` real: the stubbed ``omni.usd`` context opens the
real USD file, and the stubbed ``World`` steps nothing, so the run grades the scene as
authored. They lock the CLI, the scene setup, the settle-window rule, the artifacts the run
writes (verdict, evidence, sidecar) and its exit codes. Whether Isaac Sim's physics settles
a scene as expected is not tested here; that needs Isaac Sim (``requires_isaac``).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from scene_verify import core as sv
from scene_verify.bundle import SceneBundle
from scene_verify.runners import usd_bundle
from scene_verify_contract import parse_verdict


def _author_scene(path: Path, *, box_z: float = 0.85, pin_free_box: bool = False) -> None:
    """Write a metre-scale USD: a static table, a free box above it and a pinned box."""
    from pxr import Gf, Usd, UsdGeom, UsdPhysics

    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)

    def box(prim_path: str, extents: tuple[float, float, float], center: tuple) -> Any:
        xform = UsdGeom.Xform.Define(stage, prim_path)
        xform.AddTranslateOp().Set(Gf.Vec3d(*center))
        mesh = UsdGeom.Mesh.Define(stage, f"{prim_path}/Geom")
        hx, hy, hz = (e / 2.0 for e in extents)
        points = [
            (-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
            (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz),
        ]  # fmt: skip
        quads = [
            (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
        ]  # fmt: skip
        mesh.CreatePointsAttr([Gf.Vec3f(*p) for p in points])
        mesh.CreateFaceVertexCountsAttr([4] * 6)
        mesh.CreateFaceVertexIndicesAttr([i for q in quads for i in q])
        UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
        return xform.GetPrim()

    box("/World/Table", (1.0, 1.0, 0.1), (0, 0, 0.75))
    box("/World/Box", (0.1, 0.1, 0.1), (0, 0, box_z))
    pinned = box("/World/Pinned", (0.1, 0.1, 0.1), (0.3, 0, 0.85))
    if pin_free_box:
        UsdPhysics.RigidBodyAPI.Apply(pinned).CreateKinematicEnabledAttr().Set(True)
    stage.GetRootLayer().Save()


def _write_bundle(path: Path, usd_stage_path: str, **overrides: Any) -> Path:
    bundle: dict[str, Any] = {
        "scene_id": "runner_scene",
        "usd_stage_path": usd_stage_path,
        "support_prim_path": "/World/Table",
        "objects": [
            {"object_id": "table", "prim_path": "/World/Table", "is_static_expected": True},
            {"object_id": "box", "prim_path": "/World/Box"},
            {"object_id": "pinned", "prim_path": "/World/Pinned"},
        ],
    }
    bundle.update(overrides)
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def _wire_usd_context(stubs: dict[str, MagicMock]) -> dict[str, Any]:
    """Make the stubbed ``omni.usd`` context open the real USD file with pxr."""
    from pxr import Usd

    opened: dict[str, Any] = {}

    def open_stage(usd_path: str) -> bool:
        opened["stage"] = Usd.Stage.Open(usd_path)
        opened["path"] = usd_path
        return True

    context = stubs["omni.usd"].get_context.return_value
    context.open_stage.side_effect = open_stage
    context.get_stage.side_effect = lambda: opened.get("stage")
    return opened


@pytest.fixture
def scene(tmp_path: Path, isaac_stubs: dict[str, MagicMock]) -> dict[str, Any]:
    usd_path = tmp_path / "scene.usda"
    _author_scene(usd_path)
    opened = _wire_usd_context(isaac_stubs)
    return {"usd": usd_path, "stubs": isaac_stubs, "opened": opened, "tmp": tmp_path}


def _world(stubs: dict[str, MagicMock]) -> MagicMock:
    return stubs["isaacsim.core.api"].World


# ---------------------------------------------------------------------------
# CLI and import
# ---------------------------------------------------------------------------


def test_cli_defaults():
    args = usd_bundle.parse_args(["--bundle", "b.json"])
    assert vars(args) == {
        "bundle": "b.json",
        "artifacts_dir": "artifacts",
        "thresholds": None,
        "settle_steps": None,
        "emit_sidecar": False,
    }


def test_cli_flags_are_unchanged():
    args = usd_bundle.parse_args(
        [
            "--bundle",
            "b.json",
            "--artifacts-dir",
            "out",
            "--thresholds",
            "t.yaml",
            "--settle-steps",
            "30",
            "--emit-sidecar",
        ]
    )
    assert vars(args) == {
        "bundle": "b.json",
        "artifacts_dir": "out",
        "thresholds": "t.yaml",
        "settle_steps": 30,
        "emit_sidecar": True,
    }


def test_cli_requires_a_bundle(capsys):
    with pytest.raises(SystemExit) as raised:
        usd_bundle.parse_args([])
    assert raised.value.code == 2
    assert "--bundle" in capsys.readouterr().err


def test_importing_the_runner_boots_nothing():
    # A fresh interpreter, so no other test's imports count.
    code = (
        "import sys, scene_verify.runners.usd_bundle\n"
        "loaded = sorted({m.split('.')[0] for m in sys.modules} & "
        "{'isaacsim', 'omni', 'carb', 'pxr', 'trimesh'})\n"
        "print(loaded)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


def test_the_runner_runs_as_a_module_under_minus_m():
    result = subprocess.run(
        [sys.executable, "-m", "scene_verify.runners.usd_bundle", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    for flag in ("--bundle", "--artifacts-dir", "--thresholds", "--settle-steps", "--emit-sidecar"):
        assert flag in result.stdout


def test_a_relative_usd_path_resolves_against_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert usd_bundle._resolve_usd_path("scenes/a.usda") == str(tmp_path / "scenes" / "a.usda")
    assert usd_bundle._resolve_usd_path("/abs/a.usda") == "/abs/a.usda"


# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------


def test_build_generic_scene_makes_declared_free_objects_dynamic(scene):
    from pxr import UsdPhysics

    _author_scene(scene["usd"], pin_free_box=True)
    bundle = SceneBundle.from_json_file(
        _write_bundle(scene["tmp"] / "bundle.json", str(scene["usd"]))
    )
    stage, world, metas, support = usd_bundle.build_generic_scene(
        bundle=bundle, usd_path=str(scene["usd"]), config=sv.load_verify_thresholds(None)
    )
    stubs = scene["stubs"]

    assert scene["opened"]["path"] == str(scene["usd"])
    assert support == "/World/Table"
    assert [m["object_id"] for m in metas] == ["table", "box", "pinned"]
    # A passive settle needs a physics scene; one is added when none is authored.
    assert any(prim.IsA(UsdPhysics.Scene) for prim in stage.Traverse())
    # The free box becomes a dynamic rigid body.
    box = stage.GetPrimAtPath("/World/Box")
    assert box.HasAPI(UsdPhysics.RigidBodyAPI)
    assert UsdPhysics.RigidBodyAPI(box).GetKinematicEnabledAttr().Get() is False
    # A free-declared object that was authored kinematic is unpinned.
    pinned = stage.GetPrimAtPath("/World/Pinned")
    assert UsdPhysics.RigidBodyAPI(pinned).GetKinematicEnabledAttr().Get() is False
    # The static-expected table is left as authored.
    assert not stage.GetPrimAtPath("/World/Table").HasAPI(UsdPhysics.RigidBodyAPI)

    settings = stubs["carb"].settings.get_settings.return_value
    settings.set.assert_any_call("/physics/updateToUsd", True)
    settings.set.assert_any_call("/physics/updateVelocitiesToUsd", True)
    _world(stubs).clear_instance.assert_called_once_with()
    _world(stubs).assert_called_once_with(stage_units_in_meters=1.0)
    assert world is _world(stubs).return_value
    world.reset.assert_called_once_with()


def test_build_generic_scene_refuses_a_missing_prim(scene):
    bundle = SceneBundle.from_json_file(
        _write_bundle(
            scene["tmp"] / "bundle.json",
            str(scene["usd"]),
            objects=[{"object_id": "ghost", "prim_path": "/World/Ghost"}],
        )
    )
    with pytest.raises(RuntimeError, match="prim not found at /World/Ghost"):
        usd_bundle.build_generic_scene(
            bundle=bundle, usd_path=str(scene["usd"]), config=sv.load_verify_thresholds(None)
        )


# ---------------------------------------------------------------------------
# run(): artifacts, settle window, exit codes
# ---------------------------------------------------------------------------


def _run(scene: dict[str, Any], *extra_args: str, **bundle_overrides: Any) -> tuple[int, Path]:
    usd_stage_path = bundle_overrides.pop("usd_stage_path", str(scene["usd"]))
    bundle_path = _write_bundle(scene["tmp"] / "bundle.json", usd_stage_path, **bundle_overrides)
    artifacts = scene["tmp"] / "artifacts"
    args = usd_bundle.parse_args(
        ["--bundle", str(bundle_path), "--artifacts-dir", str(artifacts), *extra_args]
    )
    return usd_bundle.run(args), artifacts


def test_run_writes_a_valid_verdict_bound_to_the_usd(scene, capsys):
    rc, artifacts = _run(scene, "--emit-sidecar")
    assert rc == 0

    verdict_path = artifacts / "scene_verify" / "runner_scene" / "verdict.json"
    evidence_path = artifacts / "scene_verify" / "runner_scene" / "evidence.json"
    verdict = parse_verdict(json.loads(verdict_path.read_text(encoding="utf-8")))
    assert verdict.overall_status == "pass"
    assert verdict.scene_id == "runner_scene"
    assert verdict.verifier_version == sv.VERIFIER_VERSION
    assert verdict.usd_sha256 == hashlib.sha256(scene["usd"].read_bytes()).hexdigest()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert [o["object_id"] for o in evidence["objects"]] == ["table", "box", "pinned"]

    sidecar = scene["usd"].parent / "scene_verify.json"
    assert json.loads(sidecar.read_text(encoding="utf-8")) == json.loads(
        verdict_path.read_text(encoding="utf-8")
    )
    out = capsys.readouterr().out
    assert "SCENE_VERIFY_RESULT scene_id=runner_scene overall_status=pass" in out


def test_run_refuses_a_verdict_when_the_usd_changes_while_it_is_graded(scene, monkeypatch):
    # usd_sha256 must name the bytes the verifier opened: the runner hashes the file before it
    # opens the stage and refuses to write a verdict if the bytes differ after grading.
    import scene_verify.capture as capture

    original = capture.capture_scene_evidence

    def rewrite_then_capture(**kwargs: Any):
        with scene["usd"].open("a", encoding="utf-8") as handle:
            handle.write("\n# rewritten while graded\n")
        return original(**kwargs)

    monkeypatch.setattr(capture, "capture_scene_evidence", rewrite_then_capture)
    with pytest.raises(RuntimeError, match="changed while it was verified"):
        _run(scene, "--emit-sidecar")
    assert not (scene["tmp"] / "artifacts" / "scene_verify" / "runner_scene").exists()
    assert not (scene["usd"].parent / "scene_verify.json").exists()


def test_run_writes_no_sidecar_unless_asked(scene):
    rc, _ = _run(scene)
    assert rc == 0
    assert not (scene["usd"].parent / "scene_verify.json").exists()


def test_run_returns_2_on_a_failing_verdict(scene, capsys):
    # The free box sits 0.5 m below the table top: fall_through fails.
    _author_scene(scene["usd"], box_z=0.3)
    rc, artifacts = _run(scene)
    assert rc == 2
    verdict = json.loads(
        (artifacts / "scene_verify" / "runner_scene" / "verdict.json").read_text(encoding="utf-8")
    )
    assert verdict["overall_status"] == "fail"
    assert verdict["bucket_attribution"]["fall_through"] == ["fall_through"]
    assert "overall_status=fail" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("bundle_steps", "cli_steps", "expected_steps"),
    [
        (None, None, 60),  # the thresholds' window
        (5, None, 60),  # a bundle may not shorten it
        (90, None, 90),  # a bundle may lengthen it
        (None, ["--settle-steps", "3"], 3),  # the operator's flag may shorten it
        (90, ["--settle-steps", "3"], 3),  # and wins over the bundle
    ],
)
def test_settle_window(scene, bundle_steps, cli_steps, expected_steps):
    overrides = {} if bundle_steps is None else {"settle_steps": bundle_steps}
    rc, _ = _run(scene, *(cli_steps or []), **overrides)
    assert rc == 0
    assert _world(scene["stubs"]).return_value.step.call_count == expected_steps


def test_a_declared_reconstruction_adds_the_fidelity_gates(scene):
    rc, artifacts = _run(
        scene, provenance={"reconstruction": {"registered_images": 90, "total_frames": 90}}
    )
    verdict = json.loads(
        (artifacts / "scene_verify" / "runner_scene" / "verdict.json").read_text(encoding="utf-8")
    )
    gates = {gate["gate"]: gate for gate in verdict["gates"]}
    assert gates["recon_registration_coverage"]["status"] == "pass"
    # Three boxes are 36 triangles, far under the 2000-face fail line.
    assert gates["recon_surface_density"]["status"] == "fail"
    assert gates["recon_surface_density"]["detail"]["face_count"] == 36
    assert rc == 2
    parse_verdict(verdict)


def test_an_unresolved_support_prim_is_a_bundle_error(scene):
    with pytest.raises(RuntimeError, match="support_prim_path not found on stage"):
        _run(scene, support_prim_path="/World/Nope")


def test_a_relative_usd_stage_path_runs_from_the_working_directory(scene, monkeypatch):
    monkeypatch.chdir(scene["tmp"])
    rc, _ = _run(scene, "--emit-sidecar", usd_stage_path="scene.usda")
    assert rc == 0
    assert scene["opened"]["path"] == str(scene["usd"])
    assert (scene["tmp"] / "scene_verify.json").exists()


# ---------------------------------------------------------------------------
# main(): boots the app and exits with run's code
# ---------------------------------------------------------------------------


class _Exited(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def _no_exit(code: int) -> None:
    raise _Exited(code)


def test_main_boots_a_headless_app_and_exits_with_the_run_code(scene, monkeypatch):
    monkeypatch.setattr(os, "_exit", _no_exit)
    bundle_path = _write_bundle(scene["tmp"] / "bundle.json", str(scene["usd"]))
    argv = ["--bundle", str(bundle_path), "--artifacts-dir", str(scene["tmp"] / "artifacts")]
    with pytest.raises(_Exited) as exited:
        usd_bundle.main(argv)
    assert exited.value.code == 0
    scene["stubs"]["isaacsim"].SimulationApp.assert_called_once_with(
        {"headless": True, "width": 640, "height": 480}
    )


def test_main_exits_1_when_the_run_raises(scene, monkeypatch, capsys):
    monkeypatch.setattr(os, "_exit", _no_exit)
    with pytest.raises(_Exited) as exited:
        usd_bundle.main(["--bundle", str(scene["tmp"] / "missing.json")])
    assert exited.value.code == 1
    assert "FileNotFoundError" in capsys.readouterr().err
