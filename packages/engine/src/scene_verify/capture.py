"""Settle a built Isaac Sim scene and capture the evidence the engine grades.

``capture_scene_evidence`` moved here from RoboEval's PackingBench runner
``scripts/tools/verify_scene_bundle.py`` (ffda3a96), where the generic runner imported it.
The engine's runner (``scene_verify.runners.usd_bundle``) and PackingBench's runner both call
it, so every producer grades scenes through one capture implementation. PackingBench's scene
build, soundness injectors and CLI stay in RoboEval (scene-verify-0001).

Its Isaac Sim imports stay inside the function, so importing this module boots nothing.
"""

from __future__ import annotations

import math


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

    Shared by the PackingBench worker (``build_and_capture`` in RoboEval) and the generic
    ``scene_verify.runners.usd_bundle`` runner, so both grade scenes through one capture
    implementation with no per-consumer drift. ``objects_meta`` rows carry: ``object_id``, ``prim_path``,
    ``pose_prim_path``, ``pose_center_offset_xyz_m``, ``position``, ``physics_mode``,
    ``is_static_expected``. Requires a booted ``SimulationApp`` and a ``world`` already
    bound to ``stage`` (poses are captured before/after a passive ``config.settle_steps``
    settle). Returns ``(captured, objects_meta)``.
    """
    from pxr import UsdGeom

    from scene_verify import core as sv
    from scene_verify import geometry as geom
    from scene_verify.object_physics import get_dynamic_object_pose
    from scene_verify.runtime_contact import aabb_overlap_xyz

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
