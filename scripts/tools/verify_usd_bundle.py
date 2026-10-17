#!/usr/bin/env python3
"""Generic USD scene-bundle verifier — emits ``scene_verify/1`` for *any* USD scene.

This is the embodiment-agnostic counterpart to ``verify_scene_bundle.py`` (which is bound
to a PackingBench manifest row). It takes a declarative ``SceneBundle`` JSON — a USD path
plus the prims to grade — opens that USD on a physics-enabled ``World``, runs the *same*
passive settle and evidence capture (``capture_scene_evidence``, shared with the
PackingBench worker), and scores it with the Isaac-free engine. One engine, one capture,
two producers: a PackingBench eval and an arbitrary author (e.g. a SceneForge approved
bundle) get graded identically.

It deliberately does NOT fabricate physics it cannot justify: declared *free* objects are
made into dynamic rigid bodies so the settle gate is meaningful, but the support/ground is
read from the USD as authored — a scene whose table lacks a collider will (correctly) trip
``fall_through`` rather than be silently floored. No gate is faked to pass.

Usage (host Isaac python):
    /opt/isaac-sim/python.sh scripts/tools/verify_usd_bundle.py \
        --bundle path/to/scene_bundle.json \
        --artifacts-dir /sdb-disk/work/backend-scene-verify/artifacts --emit-sidecar

The ``--emit-sidecar`` flag also writes ``scene_verify.json`` beside the bundle's USD —
exactly the artifact a SceneForge packaging worker promotes into its QA report so the
``scene_verify`` approval gate can read it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(BACKEND_ROOT), str(BACKEND_ROOT / "scripts" / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify an arbitrary USD scene bundle with scene_verify"
    )
    parser.add_argument(
        "--bundle", required=True, help="Path to a SceneBundle JSON (see app/scene_verify/bundle.py)."
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(BACKEND_ROOT / "artifacts"),
        help="Durable artifacts root (verdicts under <dir>/scene_verify/<scene_id>).",
    )
    parser.add_argument("--thresholds", default=None)
    parser.add_argument("--settle-steps", type=int, default=None)
    parser.add_argument(
        "--emit-sidecar",
        action="store_true",
        help="Also write scene_verify.json beside the bundle's USD (the artifact a "
        "SceneForge packaging worker promotes into its QA report).",
    )
    return parser.parse_args(argv)


def _resolve_usd_path(usd_stage_path: str) -> str:
    path = Path(usd_stage_path)
    if not path.is_absolute():
        path = (BACKEND_ROOT / path).resolve()
    return str(path)


def build_generic_scene(*, bundle, usd_path: str, config):
    """Open ``usd_path``, make declared free objects dynamic, reset.

    Requires a booted ``SimulationApp``. Returns ``(stage, world, objects_meta,
    support_prim_path)`` ready for ``capture_scene_evidence``. Static-expected objects are
    left exactly as authored (graded by metadata). Free objects get a dynamic rigid body so
    the passive settle measures real physics; their pose prim is re-pointed to whatever the
    physics helper resolved, so pose capture reads the settled body.
    """
    import carb
    import omni.usd
    from isaacsim.core.api import World
    from pxr import UsdGeom, UsdPhysics

    from app.scene.object_physics import apply_dynamic_object_physics

    settings = carb.settings.get_settings()
    settings.set("/physics/updateToUsd", True)
    settings.set("/physics/updateVelocitiesToUsd", True)

    usd_context = omni.usd.get_context()
    if not usd_context.open_stage(usd_path):
        raise RuntimeError(f"failed to open USD stage: {usd_path}")
    stage = usd_context.get_stage()
    if stage is None:
        raise RuntimeError(f"USD stage is None after open: {usd_path}")

    # Read the scene's AUTHORED units before World() resets them. A real external scene may be
    # authored in any unit (the Pixar Kitchen Set is centimetres = 0.01); hard-coding the World
    # to metres silently loads such a scene 100x oversized and runs physics at the wrong scale.
    # Pass the authored value through so PhysX settles at true scale and the stage reports the
    # right metersPerUnit to the capture-layer normalisation. PackingBench USD is 1.0 (no-op).
    try:
        authored_mpu = float(UsdGeom.GetStageMetersPerUnit(stage))
    except Exception:
        authored_mpu = 1.0
    if not (authored_mpu > 0.0):
        authored_mpu = 1.0
    print(f"[verify-usd] authored metersPerUnit={authored_mpu}", flush=True)

    # A passive settle needs a physics scene; add a default one only if the USD authored
    # none. This does not floor anything — it just lets PhysX step the existing colliders.
    if not any(prim.IsA(UsdPhysics.Scene) for prim in stage.Traverse()):
        UsdPhysics.Scene.Define(stage, "/physicsScene")
        print("[verify-usd] no UsdPhysics.Scene authored; added /physicsScene", flush=True)

    objects_meta = bundle.objects_meta()
    meta_by_id = {m["object_id"]: m for m in objects_meta}
    for spec in bundle.objects:
        prim = stage.GetPrimAtPath(spec.prim_path)
        if not prim.IsValid():
            raise RuntimeError(
                f"object {spec.object_id!r}: prim not found at {spec.prim_path}"
            )
        if spec.is_static_expected:
            continue
        result = apply_dynamic_object_physics(
            stage, prim_path=spec.prim_path, physics_mode=spec.physics_mode
        )
        if result.pose_prim_path:
            meta_by_id[spec.object_id]["pose_prim_path"] = result.pose_prim_path
        # apply_dynamic_object_physics skips prims that already carry RigidBodyAPI — it never
        # flips kinematicEnabled. A kinematically-pinned "frozen scene" declared free would
        # sail through settle/fall gates untouched; unfreeze it so the gates grade physics.
        from pxr import Usd
        for sub in Usd.PrimRange(stage.GetPrimAtPath(spec.prim_path)):
            if sub.HasAPI(UsdPhysics.RigidBodyAPI):
                api = UsdPhysics.RigidBodyAPI(sub)
                attr = api.GetKinematicEnabledAttr()
                if attr and attr.HasAuthoredValue() and attr.Get() is True:
                    attr.Set(False)
                    print(
                        f"[verify-usd] {spec.object_id}: cleared kinematicEnabled on "
                        f"{sub.GetPath()} (free-declared object must be dynamic)",
                        flush=True,
                    )

    World.clear_instance()
    world = World(stage_units_in_meters=authored_mpu)
    world.reset()
    return stage, world, objects_meta, bundle.support_prim_path


def run(args: argparse.Namespace) -> int:
    from app.scene_verify import core as sv
    from app.scene_verify.bundle import SceneBundle

    from verify_scene_bundle import capture_scene_evidence

    bundle = SceneBundle.from_json_file(args.bundle)
    config = sv.load_verify_thresholds(args.thresholds)
    # The bundle is authored by the producer whose scene is being graded — it may RAISE the
    # settle window but never lower it (settle_steps: 0 would neutralize the physics gates,
    # letting the verified thing choose not to be verified). Only the operator CLI flag may
    # shorten it (debug use).
    if args.settle_steps is not None:
        settle_override = args.settle_steps
    elif bundle.settle_steps is not None:
        settle_override = max(bundle.settle_steps, config.settle_steps)
        if bundle.settle_steps < config.settle_steps:
            print(
                f"[verify-usd] bundle settle_steps={bundle.settle_steps} below floor; "
                f"using {config.settle_steps}",
                flush=True,
            )
    else:
        settle_override = None
    if settle_override is not None:
        config = sv.VerifyThresholds(**{**config.__dict__, "settle_steps": settle_override})

    usd_path = _resolve_usd_path(bundle.usd_stage_path)
    verified_at = datetime.now(timezone.utc).isoformat()
    stage, world, objects_meta, support_prim_path = build_generic_scene(
        bundle=bundle, usd_path=usd_path, config=config
    )
    if support_prim_path is not None and not stage.GetPrimAtPath(support_prim_path).IsValid():
        # A typo'd support path would silently disable fall-through (warn) while CI stays
        # green; a DECLARED support that does not resolve is a bundle error, not a warn.
        raise RuntimeError(f"support_prim_path not found on stage: {support_prim_path}")
    print(
        f"[verify-usd] opened {usd_path}: {len(objects_meta)} objects, "
        f"support={support_prim_path}, settle={config.settle_steps}",
        flush=True,
    )
    captured, _ = capture_scene_evidence(
        stage=stage,
        world=world,
        objects_meta=objects_meta,
        support_prim_path=support_prim_path,
        config=config,
    )
    # Fidelity gates apply only when the producer declares the scene a reconstruction
    # (bundle provenance carries a "reconstruction" mapping). Registration counts are
    # declared (the verifier cannot re-run SfM — the gate records that basis); surface
    # density is measured from the stage, never trusted.
    recon_decl = bundle.provenance.get("reconstruction")
    if isinstance(recon_decl, dict):
        import dataclasses

        from app.scene_verify import geometry as geom

        try:
            measured = geom.reconstruction_mesh_stats(
                stage, [m["prim_path"] for m in objects_meta]
            )
        except Exception as exc:  # pathological geometry must warn, not crash the run
            measured = {"measured": False, "error": str(exc)}
        captured = dataclasses.replace(
            captured,
            recon_fidelity={
                "declared": dict(recon_decl),
                "measured": measured if measured.get("measured") else {},
            },
        )
        print(f"[verify-usd] reconstruction fidelity evidence: {measured}", flush=True)
    import hashlib

    usd_sha256 = hashlib.sha256(Path(usd_path).read_bytes()).hexdigest()
    report = sv.evaluate_scene_verify(
        scene_id=bundle.scene_id, captured=captured, config=config, verified_at=verified_at,
        usd_sha256=usd_sha256,
    )
    paths = sv.dump_report(
        report=report, captured=captured, artifacts_dir=args.artifacts_dir
    )
    verdict = report.to_verdict_json()
    if args.emit_sidecar:
        sidecar = Path(usd_path).parent / "scene_verify.json"
        sidecar.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
        print(f"[verify-usd] sidecar written: {sidecar}", flush=True)

    print(json.dumps(verdict, indent=2))
    print(f"\nverdict written: {paths['verdict']}")
    # Greppable signal: /opt/isaac-sim/python.sh collapses non-zero codes to 1, so CI keys
    # on this line (or verdict.json), not $?.
    print(
        f"SCENE_VERIFY_RESULT scene_id={report.scene_id} overall_status={report.overall_status}",
        flush=True,
    )
    return 0 if report.overall_status != "fail" else 2


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from isaacsim import SimulationApp

    SimulationApp({"headless": True, "width": 640, "height": 480})
    rc = 1
    try:
        rc = run(args)
    except Exception:
        import traceback

        traceback.print_exc()
        rc = 1
    sys.stdout.flush()
    sys.stderr.flush()
    # simulation_app.close() hard-exits 0, masking rc; artifacts are already flushed, so
    # exit explicitly with rc for a CI gate keying on the code.
    os._exit(rc)


if __name__ == "__main__":
    main()
