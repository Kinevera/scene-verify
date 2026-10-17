#!/usr/bin/env python3
"""Host Isaac runner for the PackingBench scene verifier.

Generalises the host scene validator into a geometry/physics *verifier*: it builds a real
scene (reusing ``build_host_validation_scene`` and the shared object-physics helpers),
runs a passive settle, captures evidence, and scores it with the Isaac-free
``scene_verify`` decision layer — emitting the stable ``scene_verify/1`` verdict.

It builds the scene through the **shared** ``host_scene_runtime.build_packingbench_scene``
— the same faithful build the host validator uses (robot + fixed-base joint included) — so
the physics scene the verifier grades is the one the benchmark actually runs. Cameras are
the only validator step skipped (not physics-relevant). An earlier robot-free shortcut let
a rigid-lock item fall through the table; sharing the build removed that divergence.

All Isaac/app imports are lazy (inside functions) so that:
* importing this module does NOT boot a ``SimulationApp`` (the soundness runner imports
  ``build_and_capture`` after booting its own app), and
* the validator script is never imported (it boots an app at import time).

Usage (host Isaac python):
    /opt/isaac-sim/python.sh scripts/tools/verify_scene_bundle.py \
        --instance-id pack_1_i2 --storage-root /sdb-disk/work/backend \
        --artifacts-dir /sdb-disk/work/backend-scene-verify/artifacts
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

#: Physics modes whose objects are expected to stay static (graded by metadata, not settle).
STATIC_PHYSICS_MODES = {
    "artvip_carton_base_kinematic",
    "preserve_authored_articulation",
}

#: Soundness defects and the gate each must flip. Used by ``--inject`` so the live soundness
#: harness can run one defect per *fresh* Isaac process (Isaac hard-aborts on a 2nd scene
#: build in one process), aggregated by run_scene_verify_soundness.py.
SOUNDNESS_EXPECTED_GATE = {
    "oversize_collision_hull": "visual_collision_agreement",
    "undersize_collision_hull": "visual_collision_agreement",
    "missing_static_tag": "static_metadata_present",
    "interpenetration": "interpenetration",
    "fall_through": "fall_through",
}


def _soundness_injector(defect: str, config):
    """Return an ``(stage, objects_meta, config) -> info`` closure for one defect.

    Each closure mutates the freshly-built stage before ``world.reset()`` (the inject point
    in ``build_and_capture``). A closure may return ``{"skipped": reason, ...}`` when the
    scene lacks the geometry the defect needs (e.g. no separately-authored collision mesh).
    """
    from app.scene_verify import defects
    from app.scene_verify import geometry as geom

    def _first_dynamic(metas):
        return next((m for m in metas if not m["is_static_expected"]), None)

    def _first_static(metas):
        return next((m for m in metas if m["is_static_expected"]), None)

    def _skip(reason):
        return {"skipped": reason, "expected_gate": SOUNDNESS_EXPECTED_GATE[defect]}

    def oversize(stage, metas, _cfg):
        item = _first_dynamic(metas)
        if item is None:
            return _skip("no dynamic object")
        prims = geom.collision_mesh_prim_paths(stage, item["prim_path"])
        if not prims:
            return _skip("no authored collision mesh")
        return defects.inject_oversize_collision_hull(stage, prims[0], factor=config.defect_oversize_factor)

    def undersize(stage, metas, _cfg):
        item = _first_dynamic(metas)
        if item is None:
            return _skip("no dynamic object")
        prims = geom.collision_mesh_prim_paths(stage, item["prim_path"])
        if not prims:
            return _skip("no authored collision mesh")
        return defects.inject_undersize_collision_hull(stage, prims[0], factor=config.defect_undersize_factor)

    def missing_static(stage, metas, _cfg):
        target = _first_static(metas) or _first_dynamic(metas)
        if target is None:
            return _skip("no object")
        return defects.inject_missing_static_tag(stage, target["prim_path"])

    def interpenetration(stage, metas, _cfg):
        dynamic = [m for m in metas if not m["is_static_expected"]]
        if len(dynamic) < 2:
            return _skip("needs >=2 dynamic objects")
        item, partner = dynamic[0], dynamic[1]
        item_pos = item.get("position") or [0.0, 0.0, 0.0]
        partner_pos = partner.get("position") or item_pos
        translate = [float(partner_pos[k]) - float(item_pos[k]) for k in range(3)]
        return defects.inject_interpenetration(stage, item["prim_path"], translate_xyz=translate)

    def fall_through(stage, metas, _cfg):
        item = _first_dynamic(metas)
        if item is None:
            return _skip("no dynamic object")
        return defects.inject_fall_through(stage, item["prim_path"])

    return {
        "oversize_collision_hull": oversize,
        "undersize_collision_hull": undersize,
        "missing_static_tag": missing_static,
        "interpenetration": interpenetration,
        "fall_through": fall_through,
    }[defect]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a PackingBench scene with scene_verify")
    parser.add_argument("--instance-id", default="pack_1_i2")
    parser.add_argument("--robot", default="yam")
    parser.add_argument(
        "--storage-root",
        default=str(BACKEND_ROOT),
        help="Dir containing objects/backgrounds/robots/scenes (default: backend root).",
    )
    parser.add_argument("--robot-dir", default=None)
    parser.add_argument(
        "--artifacts-dir",
        default=str(BACKEND_ROOT / "artifacts"),
        help="Durable artifacts root (verdicts written under <dir>/scene_verify/<id>).",
    )
    parser.add_argument("--thresholds", default=None)
    parser.add_argument("--settle-steps", type=int, default=None)
    parser.add_argument(
        "--inject",
        default=None,
        choices=sorted(SOUNDNESS_EXPECTED_GATE),
        help="Inject one soundness defect before reset (live soundness harness; one defect "
        "per fresh Isaac process). Artifacts go under scene_verify/<id>__soundness__<defect>.",
    )
    return parser.parse_args(argv)


def build_and_capture(
    *,
    instance_id: str,
    robot: str,
    storage_root: Path,
    robot_dir: Path | None,
    config,
    inject=None,
    inject_target: str | None = None,
):
    """Build a fresh scene (optionally inject a defect), settle, and capture evidence.

    Requires a booted ``SimulationApp``. Returns ``(captured, objects_meta)``. ``inject`` is
    a callable ``(stage, objects_meta, config) -> dict`` used by the soundness harness.
    """
    from app.benchmarks.packingbench.host_scene_runtime import build_packingbench_scene

    robot_dir = robot_dir or (storage_root / "robots" / robot)

    def _meta(obj: dict) -> dict:
        return {
            "object_id": obj["name"],
            "prim_path": obj["prim_path"],
            "pose_prim_path": obj["pose_prim_path"],
            "pose_center_offset_xyz_m": obj["pose_center_offset_xyz_m"],
            "position": obj["position"],
            "physics_mode": obj["physics_mode"],
            "is_static_expected": obj["physics_mode"] in STATIC_PHYSICS_MODES,
        }

    injected = {"info": None}

    def _pre_reset(stage, objects) -> set:
        # Inject a defect on the built stage before world.reset() (the only point where stage
        # mutations take physics effect). Return the injected object's name so its pose target
        # is not re-pinned (a translate defect would otherwise be teleported back to spawn).
        if inject is None:
            return set()
        info = inject(stage, [_meta(o) for o in objects], config)
        injected["info"] = info
        print(f"[verify] injected: {info}", flush=True)
        if not (info and info.get("target_prim_path")):
            return set()
        return {o["name"] for o in objects if o["prim_path"] == info["target_prim_path"]}

    # Faithful shared build (robot + objects + reset + pose restore), identical to the host
    # validator's — so the physics scene the verifier grades is the one the benchmark uses.
    # The robot-free shortcut this replaces let a rigid-lock item fall through the table.
    built = build_packingbench_scene(
        instance_id=instance_id,
        robot=robot,
        storage_root=storage_root,
        robot_dir=robot_dir,
        pre_reset_hook=_pre_reset,
    )
    stage = built.stage
    world = built.world
    support_prim_path = built.support_prim_path
    objects_meta = [_meta(o) for o in built.objects]
    print(
        f"[verify] faithful build: {len(objects_meta)} objects, support={support_prim_path}",
        flush=True,
    )

    return capture_scene_evidence(
        stage=stage,
        world=world,
        objects_meta=objects_meta,
        support_prim_path=support_prim_path,
        config=config,
        injected_info=injected["info"],
    )


def capture_scene_evidence(
    *,
    stage,
    world,
    objects_meta,
    support_prim_path,
    config,
    injected_info=None,
):
    """Settle a built scene and capture all evidence the engine grades.

    Shared by the PackingBench worker (``build_and_capture``) and the generic
    ``verify_usd_bundle`` runner, so both grade scenes through one capture implementation
    with no per-consumer drift. ``objects_meta`` rows carry: ``object_id``, ``prim_path``,
    ``pose_prim_path``, ``pose_center_offset_xyz_m``, ``position``, ``physics_mode``,
    ``is_static_expected``. Requires a booted ``SimulationApp`` and a ``world`` already
    bound to ``stage`` (poses are captured before/after a passive ``config.settle_steps``
    settle). Returns ``(captured, objects_meta)``.
    """
    from pxr import UsdGeom

    from app.benchmarks.packingbench.runtime_contact import aabb_overlap_xyz
    from app.scene.object_physics import get_dynamic_object_pose
    from app.scene_verify import core as sv
    from app.scene_verify import geometry as geom

    # The engine's thresholds are all in metres. A USD stage may be authored in any unit
    # (PackingBench scenes are metres = 1.0; the Pixar Kitchen Set is centimetres = 0.01).
    # Every length captured below — poses, AABBs, table_top_z, penetration, mesh divergence —
    # is read in raw stage units, so normalise to metres here, the single capture seam, before
    # the engine grades. metersPerUnit == 1.0 (every PackingBench scene) makes this a no-op.
    try:
        meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
    except Exception:
        meters_per_unit = 1.0
    if not (meters_per_unit > 0.0):
        meters_per_unit = 1.0
    mpu = meters_per_unit
    print(f"[verify] stage metersPerUnit={mpu} (lengths normalised to metres)", flush=True)

    def _scale_aabb(bounds):
        if bounds is None:
            return None
        return tuple(float(c) * mpu for c in bounds)

    def _pose(meta: dict) -> dict | None:
        try:
            pose = get_dynamic_object_pose(
                stage,
                prim_path=meta["prim_path"],
                pose_prim_path=meta["pose_prim_path"],
                pose_center_offset_xyz_m=meta.get("pose_center_offset_xyz_m"),
            )
        except Exception:
            return None
        if pose and mpu != 1.0 and pose.get("position") is not None:
            pose = {**pose, "position": [float(c) * mpu for c in pose["position"]]}
        return pose

    def _capture_aabbs() -> dict:
        bounds = geom.world_aabb_bounds_by_prim_path(
            stage, [m["prim_path"] for m in objects_meta]
        )
        if mpu != 1.0:
            # Scale at the source so AABBs, table_top_z, and the overlap volumes (computed
            # from these bounds) are all in metres without further per-field scaling.
            bounds = {k: _scale_aabb(v) for k, v in bounds.items()}
        return bounds

    def _capture_pair_overlaps(bounds: dict, phase: str) -> list["sv.CapturedPairOverlap"]:
        overlaps: list[sv.CapturedPairOverlap] = []
        for i in range(len(objects_meta)):
            for j in range(i + 1, len(objects_meta)):
                a, b = objects_meta[i], objects_meta[j]
                # Grade interpenetration only between dynamic items. An item legitimately
                # inside an open container's bounding box (a placed/packed item) is not
                # interpenetration, and coarse AABB overlap cannot distinguish that from a
                # real clash — so pairs involving a static-expected object are excluded.
                if a["is_static_expected"] or b["is_static_expected"]:
                    continue
                ov = aabb_overlap_xyz(bounds.get(a["prim_path"]), bounds.get(b["prim_path"]))
                if ov.get("bounds_available"):
                    aabb_hit = bool(ov.get("geometry_overlap_detected"))
                    # Only when the cheap AABB pre-pass says the boxes overlap do we pay for
                    # the mesh-level penetration depth between collision proxies — this is
                    # what distinguishes a real clash from a bounding-box corner-clip of two
                    # validly placed items (the 7 mm³ AABB false-positive the corpus surfaced).
                    penetration = None
                    if aabb_hit:
                        try:
                            penetration = geom.pairwise_collision_penetration_depth_m(
                                stage,
                                a["prim_path"],
                                b["prim_path"],
                                n_samples=config.mesh_n_samples,
                            )
                        except Exception as exc:  # never crash the run on bad geometry
                            print(
                                f"[verify]   penetration ({phase}) "
                                f"{a['object_id']}/{b['object_id']}: {exc}",
                                flush=True,
                            )
                            penetration = None
                    if penetration is not None and not math.isfinite(float(penetration)):
                        # Degenerate signed-distance sampling can yield NaN; recording it
                        # would poison the gate's threshold comparison downstream. None
                        # routes the pair to the AABB-volume fallback instead.
                        print(
                            f"[verify]   penetration ({phase}) "
                            f"{a['object_id']}/{b['object_id']}: non-finite, using AABB fallback",
                            flush=True,
                        )
                        penetration = None
                    if penetration is not None and mpu != 1.0:
                        penetration = float(penetration) * mpu
                    overlaps.append(
                        sv.CapturedPairOverlap(
                            a["object_id"],
                            b["object_id"],
                            float(ov.get("overlap_volume_m3") or 0.0),
                            aabb_hit,
                            penetration_depth_m=penetration,
                        )
                    )
        return overlaps

    pose_before = {m["object_id"]: _pose(m) for m in objects_meta}
    # Authored-state (t=0) interpenetration capture, BEFORE any physics step: PhysX
    # depenetrates authored overlaps within the first settle steps, so the settled capture
    # alone is structurally blind to exactly the defect the interpenetration gate exists for.
    overlaps_pre_settle = _capture_pair_overlaps(_capture_aabbs(), "authored")
    print(
        f"[verify] world ready, captured spawn poses + authored overlaps "
        f"({len(overlaps_pre_settle)} pairs); settling {config.settle_steps} steps",
        flush=True,
    )
    settle_steps = config.settle_steps
    for _ in range(settle_steps):
        world.step(render=False)
    pose_after = {m["object_id"]: _pose(m) for m in objects_meta}
    print("[verify] settled, capturing AABBs + mesh divergence", flush=True)

    aabbs = _capture_aabbs()
    overlaps = _capture_pair_overlaps(aabbs, "settled")

    table_top_z = None
    if support_prim_path:
        support_bounds = geom.world_aabb_bounds_by_prim_path(
            stage, [support_prim_path]
        ).get(support_prim_path)
        if support_bounds:
            table_top_z = float(support_bounds[5]) * mpu
    print(f"[verify] AABBs+overlaps captured ({len(overlaps)} pairs), table_top_z={table_top_z}", flush=True)

    captured_objects = []
    for m in objects_meta:
        print(f"[verify]   object {m['object_id']}: mesh divergence...", flush=True)
        try:
            divergence = geom.object_mesh_divergence(
                stage,
                m["prim_path"],
                n_samples=config.mesh_n_samples,
                bvh_skip_margin_m=config.mesh_bvh_skip_margin_m,
            )
        except Exception as exc:  # asset geometry can be pathological; never crash the run
            divergence = {"mesh_present": False, "mode": "error", "error": str(exc)}
        if mpu != 1.0 and isinstance(divergence, dict):
            for _len_key in ("phantom_max_m", "clip_max_m", "phantom_p95_m", "clip_p95_m"):
                if isinstance(divergence.get(_len_key), (int, float)):
                    divergence[_len_key] = float(divergence[_len_key]) * mpu
        print(f"[verify]   object {m['object_id']}: mode={divergence.get('mode')}", flush=True)
        try:
            static_tag = (
                geom.scan_static_tag(stage, m["prim_path"])
                if m["is_static_expected"]
                else None
            )
        except Exception as exc:
            static_tag = None
            print(f"[verify]   object {m['object_id']}: static scan error: {exc}", flush=True)
        captured_objects.append(
            sv.CapturedObjectEvidence(
                object_id=m["object_id"],
                is_static_expected=m["is_static_expected"],
                pose_before=pose_before.get(m["object_id"]),
                pose_after=pose_after.get(m["object_id"]),
                aabb_after=aabbs.get(m["prim_path"]),
                mesh_divergence=divergence,
                has_static_tag=static_tag,
            )
        )

    captured = sv.CapturedSceneEvidence(
        objects=tuple(captured_objects),
        load_ok=bool(objects_meta),
        load_detail={"object_count": len(objects_meta), "injected": injected_info},
        table_top_z_m=table_top_z,
        pairwise_overlaps=tuple(overlaps),
        pairwise_overlaps_pre_settle=tuple(overlaps_pre_settle),
    )
    return captured, objects_meta


def run(args: argparse.Namespace) -> int:
    from app.scene_verify import core as sv
    from app.benchmarks.packingbench import scene_verify_packingbench as pb_adapter

    config = sv.load_verify_thresholds(args.thresholds)
    if args.settle_steps is not None:
        config = sv.VerifyThresholds(**{**config.__dict__, "settle_steps": args.settle_steps})

    verified_at = datetime.now(timezone.utc).isoformat()
    inject = _soundness_injector(args.inject, config) if args.inject else None
    captured, objects_meta = build_and_capture(
        instance_id=args.instance_id,
        robot=args.robot,
        storage_root=Path(args.storage_root),
        robot_dir=Path(args.robot_dir) if args.robot_dir else None,
        config=config,
        inject=inject,
    )
    # An injected case writes to its own artifact subdir so it never clobbers the clean run.
    out_scene_id = (
        f"{args.instance_id}__soundness__{args.inject}" if args.inject else args.instance_id
    )
    report = sv.evaluate_scene_verify(
        scene_id=out_scene_id, captured=captured, config=config, verified_at=verified_at
    )
    # Engine writes the generic verdict/evidence; the PackingBench adapter writes its own
    # legacy validation_summary.json (the engine has no PackingBench identity).
    paths = sv.dump_report(report=report, captured=captured, artifacts_dir=args.artifacts_dir)
    pb_adapter.write_validation_summary(
        report,
        artifacts_dir=args.artifacts_dir,
        validated_asset_ids=tuple(m["object_id"] for m in objects_meta),
    )
    print(json.dumps(report.to_verdict_json(), indent=2))
    print(f"\nverdict written: {paths['verdict']}")
    # Authoritative, greppable gate signal: /opt/isaac-sim/python.sh collapses non-zero
    # exit codes to 1, so CI should key on this line (or verdict.json) rather than $?.
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
    # Isaac's simulation_app.close() hard-exits the process with code 0, which would mask
    # rc. Artifacts are already flushed to disk by run(); exit explicitly with rc so a CI
    # gate keying on the exit code can distinguish pass/warn (0) from fail (2).
    os._exit(rc)


if __name__ == "__main__":
    main()
