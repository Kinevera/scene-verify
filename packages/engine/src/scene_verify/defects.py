"""Defect injectors for the scene-verifier soundness harness.

Each injector mutates an **already-open, in-memory** USD stage in place and returns a
descriptor carrying the gate/bucket the verifier is expected to flip. The runner is
responsible for handing in a throwaway stage copy — these functions never open, export,
or overwrite the source asset.

The descriptors co-locate the expectation with the mutation so the discrimination matrix
in ``run_scene_verify_soundness.py`` stays declarative:

    matrix row = inject(stage, ...) -> verify(stage) -> assert fired == expected
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

#: xformOp suffix used so injected ops never collide with authored transform ops.
_DEFECT_OP_SUFFIX = "scene_verify_defect"


def _require_prim(stage: Any, prim_path: str):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"scene_verify defect target prim is absent: {prim_path}")
    return prim


def _add_scale_about_origin(prim: Any, factor: float) -> None:
    from pxr import Gf, UsdGeom

    op = UsdGeom.Xformable(prim).AddScaleOp(opSuffix=_DEFECT_OP_SUFFIX)
    op.Set(Gf.Vec3f(float(factor), float(factor), float(factor)))


def inject_oversize_collision_hull(
    stage: Any, collision_prim_path: str, *, factor: float
) -> dict[str, Any]:
    """Scale the collision subtree UP so it protrudes beyond the visual mesh (phantom)."""
    if factor <= 1.0:
        raise ValueError("oversize factor must be > 1.0")
    _add_scale_about_origin(_require_prim(stage, collision_prim_path), factor)
    return {
        "defect": "oversize_collision_hull",
        "target_prim_path": collision_prim_path,
        "factor": factor,
        "expected_gate": "visual_collision_agreement",
        "expected_bucket": "mesh_disagreement",
    }


def inject_undersize_collision_hull(
    stage: Any, collision_prim_path: str, *, factor: float
) -> dict[str, Any]:
    """Scale the collision subtree DOWN so the visual protrudes beyond it (clip-through)."""
    if not 0.0 < factor < 1.0:
        raise ValueError("undersize factor must be in (0, 1)")
    _add_scale_about_origin(_require_prim(stage, collision_prim_path), factor)
    return {
        "defect": "undersize_collision_hull",
        "target_prim_path": collision_prim_path,
        "factor": factor,
        "expected_gate": "visual_collision_agreement",
        "expected_bucket": "mesh_disagreement",
    }


def inject_missing_static_tag(stage: Any, static_prim_path: str) -> dict[str, Any]:
    """Turn a static-expected object dynamic (clears the kinematic "static tag").

    Routes to the labeling/metadata bucket — NOT physics — because the verifier's
    settle/fall-through gates ignore static-expected objects entirely.
    """
    from pxr import Usd, UsdPhysics

    root = _require_prim(stage, static_prim_path)
    flipped: list[str] = []
    for prim in Usd.PrimRange(root):
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            UsdPhysics.RigidBodyAPI(prim).CreateKinematicEnabledAttr().Set(False)
            flipped.append(str(prim.GetPath()))
    if not flipped:
        # No rigid body authored: apply a dynamic one to represent the same defect.
        UsdPhysics.RigidBodyAPI.Apply(root).CreateKinematicEnabledAttr().Set(False)
        flipped.append(str(root.GetPath()))
    return {
        "defect": "missing_static_tag",
        "target_prim_path": static_prim_path,
        "flipped_bodies": flipped,
        "expected_gate": "static_metadata_present",
        "expected_bucket": "missing_static_metadata",
    }


def inject_interpenetration(
    stage: Any, object_prim_path: str, *, translate_xyz: Sequence[float]
) -> dict[str, Any]:
    """Translate an object so its AABB overlaps a neighbour by a known margin."""
    from pxr import Gf, UsdGeom

    prim = _require_prim(stage, object_prim_path)
    op = UsdGeom.Xformable(prim).AddTranslateOp(opSuffix=_DEFECT_OP_SUFFIX)
    op.Set(Gf.Vec3d(*(float(v) for v in translate_xyz)))
    return {
        "defect": "interpenetration",
        "target_prim_path": object_prim_path,
        "translate_xyz": [float(v) for v in translate_xyz],
        "expected_gate": "interpenetration",
        "expected_bucket": "interpenetration",
    }


def inject_fall_through(stage: Any, object_prim_path: str) -> dict[str, Any]:
    """Remove collision geometry from a dynamic object so it falls through support."""
    from pxr import Usd, UsdPhysics

    try:
        from pxr import PhysxSchema  # noqa: F401
    except Exception:  # pragma: no cover - PhysxSchema optional in plain USD
        PhysxSchema = None

    root = _require_prim(stage, object_prim_path)
    removed: list[str] = []
    for prim in Usd.PrimRange(root):
        changed = False
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            prim.RemoveAPI(UsdPhysics.CollisionAPI)
            changed = True
        if PhysxSchema is not None and prim.HasAPI(PhysxSchema.PhysxCollisionAPI):
            prim.RemoveAPI(PhysxSchema.PhysxCollisionAPI)
            changed = True
        if changed:
            removed.append(str(prim.GetPath()))
    return {
        "defect": "fall_through",
        "target_prim_path": object_prim_path,
        "removed_collision_from": removed,
        "expected_gate": "fall_through",
        "expected_bucket": "fall_through",
    }


#: Registry consumed by the soundness runner (ordered for a stable matrix).
DEFECT_INJECTORS = (
    "oversize_collision_hull",
    "undersize_collision_hull",
    "missing_static_tag",
    "interpenetration",
    "fall_through",
)
