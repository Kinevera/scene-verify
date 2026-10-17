"""Dynamic-object physics setup and pose reads for the engine's Isaac Sim runner.

Copied from RoboEval's ``app/scene/object_physics.py`` (ffda3a96) with only
``apply_dynamic_object_physics``, ``get_dynamic_object_pose`` and the private helpers and
constants they reach. RoboEval keeps its flap-angle, spawn-pose and runtime pose-target
helpers; this copy is maintained here (scene-verify-0001).
"""

from __future__ import annotations

from dataclasses import dataclass

ARTVIP_CARTON_BASE_KINEMATIC_MODE = "artvip_carton_base_kinematic"
ARTVIP_PUMP_BOTTLE_RIGID_LOCK_MODE = "artvip_pump_bottle_rigid_lock"
ARTVIP_FOLDER_MAILER_RIGID_LOCK_MODE = "artvip_folder_mailer_rigid_lock"
ARTVIP_STAPLER_TOOL_RIGID_LOCK_MODE = "artvip_stapler_tool_rigid_lock"
ARTVIP_TOOLBOX_CASE_RIGID_LOCK_MODE = "artvip_toolbox_case_rigid_lock"
ARTVIP_SCISSORS_RIGID_LOCK_MODE = "artvip_scissors_rigid_lock"
ARTVIP_UTILITY_KNIFE_RIGID_LOCK_MODE = "artvip_utility_knife_rigid_lock"
ARTVIP_STAPLER_SMALL_RIGID_LOCK_MODE = "artvip_stapler_small_rigid_lock"
ARTVIP_PUMP_BOTTLE_SMALL_RIGID_LOCK_MODE = "artvip_pump_bottle_small_rigid_lock"
PRESERVE_AUTHORED_ARTICULATION_MODE = "preserve_authored_articulation"
POSE_PRIM_STRATEGY_AUTO = "auto"
POSE_PRIM_STRATEGY_ROOT = "root"
POSE_PRIM_STRATEGY_FIRST_RIGID_BODY_DESCENDANT = "first_rigid_body_descendant"
_ARTVIP_CARTON_BODY_PRIM_NAME = "E_body_1"
_ARTVIP_CARTON_FIXED_JOINT_NAME = "FixedJoint"
_ARTVIP_TOOLBOX_CASE_BODY_PRIM_NAME = "E_body_2"
# Referenced articulated USDs can take a few Kit updates before rigid-body APIs
# are visible under the spawned root prim. Keep the wait budget explicit.
_ARTVIP_CARTON_BODY_LOOKUP_MAX_UPDATES = 11
_ARTVIP_ROOT_RIGID_LOCK_MODES = {
    ARTVIP_PUMP_BOTTLE_RIGID_LOCK_MODE,
    ARTVIP_FOLDER_MAILER_RIGID_LOCK_MODE,
    ARTVIP_STAPLER_TOOL_RIGID_LOCK_MODE,
    ARTVIP_TOOLBOX_CASE_RIGID_LOCK_MODE,
    ARTVIP_SCISSORS_RIGID_LOCK_MODE,
    ARTVIP_UTILITY_KNIFE_RIGID_LOCK_MODE,
    ARTVIP_STAPLER_SMALL_RIGID_LOCK_MODE,
    ARTVIP_PUMP_BOTTLE_SMALL_RIGID_LOCK_MODE,
}


@dataclass(frozen=True)
class DynamicObjectPhysicsResult:
    """Resolved physics application details for one spawned dynamic object."""

    physics_mode: str | None
    pose_prim_path: str
    spawn_prim_path: str


def _update_kit_app() -> None:
    import omni.kit.app

    omni.kit.app.get_app().update()


def _find_first_rigid_body_descendant(root_prim):
    from pxr import Usd, UsdPhysics

    for prim in Usd.PrimRange(root_prim):
        if prim == root_prim:
            continue
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            return prim
    return None


def _find_rigid_body_descendants(root_prim) -> list[object]:
    from pxr import Usd, UsdPhysics

    rigid_bodies = []
    for prim in Usd.PrimRange(root_prim):
        if prim != root_prim and prim.HasAPI(UsdPhysics.RigidBodyAPI):
            rigid_bodies.append(prim)
    return rigid_bodies


def _prim_has_named_ancestor_before_root(prim, *, root_prim, ancestor_name: str) -> bool:
    current_prim = prim
    while current_prim and current_prim != root_prim:
        if current_prim.GetName() == ancestor_name:
            return True
        current_prim = current_prim.GetParent()
    return False


def _find_artvip_carton_body_prim(stage, prim_path: str):
    from pxr import Usd, UsdPhysics

    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        raise RuntimeError(f"Dynamic object prim not found: {prim_path}")

    for _ in range(_ARTVIP_CARTON_BODY_LOOKUP_MAX_UPDATES):
        for prim in Usd.PrimRange(root_prim):
            if prim == root_prim:
                continue
            if prim.GetName() == _ARTVIP_CARTON_BODY_PRIM_NAME and prim.HasAPI(
                UsdPhysics.RigidBodyAPI
            ):
                return prim
        _update_kit_app()

    raise RuntimeError(
        "Could not find articulated carton body prim under "
        f"{prim_path}/{_ARTVIP_CARTON_BODY_PRIM_NAME}"
    )


def _default_pose_prim_path(stage, prim_path: str) -> str:
    return _resolve_pose_prim_path(stage, prim_path, pose_prim_strategy=None)


def _resolve_pose_prim_path(
    stage,
    prim_path: str,
    *,
    pose_prim_strategy: str | None,
) -> str:
    from pxr import UsdPhysics

    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Dynamic object prim not found: {prim_path}")

    strategy = pose_prim_strategy or POSE_PRIM_STRATEGY_AUTO
    if strategy == POSE_PRIM_STRATEGY_ROOT:
        return str(prim.GetPath())

    if strategy not in {
        POSE_PRIM_STRATEGY_AUTO,
        POSE_PRIM_STRATEGY_FIRST_RIGID_BODY_DESCENDANT,
    }:
        raise ValueError(f"Unsupported pose prim strategy: {strategy}")

    if prim.HasAPI(UsdPhysics.RigidBodyAPI):
        return str(prim.GetPath())

    rigid_child = _find_first_rigid_body_descendant(prim)
    if rigid_child is not None:
        return str(rigid_child.GetPath())
    return prim_path


def apply_dynamic_object_physics(
    stage,
    *,
    prim_path: str,
    physics_mode: str | None,
    pose_prim_strategy: str | None = None,
) -> DynamicObjectPhysicsResult:
    """Apply shared dynamic-object physics overrides after a USD reference is added."""
    if physics_mode is None:
        from pxr import UsdPhysics as _UsdPhysics

        pose_prim_path = _resolve_pose_prim_path(
            stage,
            prim_path,
            pose_prim_strategy=pose_prim_strategy,
        )
        # Ensure the object is a dynamic rigid body so it can be pushed/picked.
        # If a descendant already has RigidBodyAPI, strip it first to avoid
        # nested rigid bodies (invalid in PhysX).
        root_prim = stage.GetPrimAtPath(prim_path)
        if root_prim.IsValid() and not root_prim.HasAPI(_UsdPhysics.RigidBodyAPI):
            for desc in _find_rigid_body_descendants(root_prim):
                desc.RemoveAPI(_UsdPhysics.RigidBodyAPI)
            rigid_api = _UsdPhysics.RigidBodyAPI.Apply(root_prim)
            rigid_api.CreateKinematicEnabledAttr().Set(False)
        return DynamicObjectPhysicsResult(
            physics_mode=None,
            pose_prim_path=pose_prim_path,
            spawn_prim_path=pose_prim_path,
        )

    if physics_mode in _ARTVIP_ROOT_RIGID_LOCK_MODES:
        from pxr import PhysxSchema, Usd, UsdPhysics

        root_prim = stage.GetPrimAtPath(prim_path)
        if not root_prim.IsValid():
            raise RuntimeError(f"Dynamic object prim not found: {prim_path}")

        # Rigidify ArtVIP articulated assets that should behave as rigid v0.1
        # objects into a single dynamic body at the spawned root prim. The
        # source USDs carry descendant joints and rigid bodies that otherwise
        # preserve authored articulation/world-fix behavior and ignore the seeded
        # packing spawn contract.
        for descendant_prim in Usd.PrimRange(root_prim):
            if descendant_prim == root_prim:
                continue
            if descendant_prim.IsA(UsdPhysics.Joint):
                descendant_prim.SetActive(False)
            if (
                physics_mode == ARTVIP_TOOLBOX_CASE_RIGID_LOCK_MODE
                and descendant_prim.HasAPI(UsdPhysics.CollisionAPI)
                and not _prim_has_named_ancestor_before_root(
                    descendant_prim,
                    root_prim=root_prim,
                    ancestor_name=_ARTVIP_TOOLBOX_CASE_BODY_PRIM_NAME,
                )
            ):
                descendant_prim.RemoveAPI(UsdPhysics.CollisionAPI)
                if descendant_prim.HasAPI(PhysxSchema.PhysxCollisionAPI):
                    descendant_prim.RemoveAPI(PhysxSchema.PhysxCollisionAPI)
            if descendant_prim.HasAPI(UsdPhysics.ArticulationRootAPI):
                descendant_prim.RemoveAPI(UsdPhysics.ArticulationRootAPI)
            if descendant_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                descendant_prim.RemoveAPI(UsdPhysics.RigidBodyAPI)
            if descendant_prim.HasAPI(PhysxSchema.PhysxRigidBodyAPI):
                descendant_prim.RemoveAPI(PhysxSchema.PhysxRigidBodyAPI)

        if root_prim.HasAPI(UsdPhysics.RigidBodyAPI):
            rigid_body_api = UsdPhysics.RigidBodyAPI(root_prim)
        else:
            rigid_body_api = UsdPhysics.RigidBodyAPI.Apply(root_prim)
        rigid_body_api.CreateKinematicEnabledAttr().Set(False)

        return DynamicObjectPhysicsResult(
            physics_mode=physics_mode,
            pose_prim_path=prim_path,
            spawn_prim_path=prim_path,
        )

    if physics_mode == PRESERVE_AUTHORED_ARTICULATION_MODE:
        return DynamicObjectPhysicsResult(
            physics_mode=physics_mode,
            pose_prim_path=prim_path,
            spawn_prim_path=prim_path,
        )

    if physics_mode != ARTVIP_CARTON_BASE_KINEMATIC_MODE:
        raise ValueError(f"Unsupported dynamic object physics mode: {physics_mode}")

    from pxr import UsdPhysics

    body_prim = _find_artvip_carton_body_prim(stage, prim_path)
    fixed_joint_path = (
        f"{prim_path}/{_ARTVIP_CARTON_BODY_PRIM_NAME}/{_ARTVIP_CARTON_FIXED_JOINT_NAME}"
    )
    fixed_joint_prim = stage.GetPrimAtPath(fixed_joint_path)
    if not fixed_joint_prim.IsValid() or not fixed_joint_prim.IsA(UsdPhysics.Joint):
        raise RuntimeError(f"Could not find articulated carton fixed joint at {fixed_joint_path}")

    UsdPhysics.Joint(fixed_joint_prim).CreateJointEnabledAttr().Set(False)
    UsdPhysics.RigidBodyAPI(body_prim).CreateKinematicEnabledAttr().Set(True)

    return DynamicObjectPhysicsResult(
        physics_mode=physics_mode,
        pose_prim_path=str(body_prim.GetPath()),
        spawn_prim_path=prim_path,
    )


def get_dynamic_object_pose(
    stage,
    *,
    prim_path: str,
    pose_prim_path: str | None = None,
    pose_center_offset_xyz_m: list[float] | tuple[float, float, float] | None = None,
) -> dict[str, list[float]]:
    """Read a dynamic object's world pose from the resolved runtime pose prim."""
    anchor_pose = get_dynamic_object_anchor_pose(
        stage,
        prim_path=prim_path,
        pose_prim_path=pose_prim_path,
    )
    if pose_center_offset_xyz_m is None:
        return anchor_pose

    if len(pose_center_offset_xyz_m) != 3:
        raise ValueError("pose_center_offset_xyz_m must contain exactly 3 values when provided")

    rotated_offset = _rotate_vector_by_quaternion(
        (
            float(pose_center_offset_xyz_m[0]),
            float(pose_center_offset_xyz_m[1]),
            float(pose_center_offset_xyz_m[2]),
        ),
        anchor_pose["rotation"],
    )
    return {
        "position": [
            anchor_pose["position"][0] + rotated_offset[0],
            anchor_pose["position"][1] + rotated_offset[1],
            anchor_pose["position"][2] + rotated_offset[2],
        ],
        "rotation": anchor_pose["rotation"],
    }


def get_dynamic_object_anchor_pose(
    stage,
    *,
    prim_path: str,
    pose_prim_path: str | None = None,
) -> dict[str, list[float]]:
    """Read the authored anchor pose from the resolved runtime pose prim."""
    from pxr import UsdGeom

    target_path = pose_prim_path or _default_pose_prim_path(stage, prim_path)
    target_prim = stage.GetPrimAtPath(target_path)
    if not target_prim.IsValid():
        raise RuntimeError(f"Dynamic object pose prim not found: {target_path}")

    xformable = UsdGeom.Xformable(target_prim)
    world_transform = xformable.ComputeLocalToWorldTransform(0)
    translation = world_transform.ExtractTranslation()
    position = [float(translation[0]), float(translation[1]), float(translation[2])]

    rotation_matrix = world_transform.ExtractRotationMatrix()
    quat = rotation_matrix.ExtractRotation().GetQuaternion()
    rotation = [
        float(quat.GetReal()),
        float(quat.GetImaginary()[0]),
        float(quat.GetImaginary()[1]),
        float(quat.GetImaginary()[2]),
    ]
    return {"position": position, "rotation": rotation}


def _rotate_vector_by_quaternion(
    vector: tuple[float, float, float],
    quaternion_wxyz: list[float],
) -> tuple[float, float, float]:
    w, x, y, z = (float(component) for component in quaternion_wxyz)
    vx, vy, vz = vector

    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)

    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )
