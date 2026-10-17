"""Shared dynamic-object physics helpers for runtime and host validation."""

from __future__ import annotations

from dataclasses import dataclass
import math

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
_ARTVIP_CARTON_FLAP_JOINT_PREFIX = "RevoluteJoint_carton_2_"
_ARTVIP_CARTON_FLAP_NAME_BY_JOINT_SUFFIX = {
    "left": "left_flap",
    "right": "right_flap",
    # The ArtVIP carton names the X-aligned flaps as "up/down"; map them into
    # the manifest's front/back semantic flap ids once here.
    "down": "front_flap",
    "up": "back_flap",
}
_ARTVIP_PUMP_BOTTLE_BODY_PRIM_NAME = "E_body_2"
_ARTVIP_PUMP_BOTTLE_CAP_PRIM_NAME = "E_cap_3"
_ARTVIP_PUMP_BOTTLE_PRISMATIC_JOINT_NAME = "PrismaticJoint_Pressure_pump_13_up"
_ARTVIP_PUMP_BOTTLE_FIXED_JOINT_NAME = "FixedJoint"
_ARTVIP_TOOLBOX_CASE_BODY_PRIM_NAME = "E_body_2"
# Referenced articulated USDs can take a few Kit updates before rigid-body APIs
# are visible under the spawned root prim. Keep the wait budget explicit.
_ARTVIP_CARTON_BODY_LOOKUP_MAX_UPDATES = 11
_ARTVIP_PUMP_BOTTLE_LOOKUP_MAX_UPDATES = 11
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


def _prim_has_named_ancestor_before_root(
    prim, *, root_prim, ancestor_name: str
) -> bool:
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


def _find_named_rigid_body_prim(stage, prim_path: str, rigid_body_name: str):
    from pxr import Usd, UsdPhysics

    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        raise RuntimeError(f"Dynamic object prim not found: {prim_path}")

    for _ in range(_ARTVIP_PUMP_BOTTLE_LOOKUP_MAX_UPDATES):
        for prim in Usd.PrimRange(root_prim):
            if prim == root_prim:
                continue
            if prim.GetName() == rigid_body_name and prim.HasAPI(
                UsdPhysics.RigidBodyAPI
            ):
                return prim
        _update_kit_app()

    raise RuntimeError(
        f"Could not find rigid body prim '{rigid_body_name}' under {prim_path}"
    )


def _find_named_prismatic_joint_prim(stage, prim_path: str, joint_name: str):
    from pxr import Usd, UsdPhysics

    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        raise RuntimeError(f"Dynamic object prim not found: {prim_path}")

    for _ in range(_ARTVIP_PUMP_BOTTLE_LOOKUP_MAX_UPDATES):
        for prim in Usd.PrimRange(root_prim):
            if prim == root_prim:
                continue
            if prim.GetName() == joint_name and prim.IsA(UsdPhysics.PrismaticJoint):
                return prim
        _update_kit_app()

    raise RuntimeError(
        f"Could not find prismatic joint '{joint_name}' under {prim_path}"
    )


def _find_artvip_carton_flap_joint_prims(stage, prim_path: str):
    from pxr import Usd, UsdPhysics

    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        raise RuntimeError(f"Dynamic object prim not found: {prim_path}")

    joint_prims: dict[str, object] = {}
    for prim in Usd.PrimRange(root_prim):
        if prim == root_prim or not prim.IsA(UsdPhysics.RevoluteJoint):
            continue
        prim_name = prim.GetName()
        if not prim_name.startswith("RevoluteJoint_carton_"):
            # Also handle double-underscore typos in some ArtVIP cartons
            if not prim_name.startswith("RevoluteJoint__carton_"):
                continue
        # Extract direction suffix (left/right/up/down) after last underscore
        joint_suffix = prim_name.rsplit("_", 1)[-1]
        flap_name = _ARTVIP_CARTON_FLAP_NAME_BY_JOINT_SUFFIX.get(joint_suffix)
        if flap_name is not None:
            joint_prims[flap_name] = prim

    missing_flaps = sorted(
        set(_ARTVIP_CARTON_FLAP_NAME_BY_JOINT_SUFFIX.values()) - set(joint_prims)
    )
    if missing_flaps:
        raise RuntimeError(
            "Could not find articulated carton flap joints for "
            f"{prim_path}: missing={missing_flaps}"
        )
    return joint_prims


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
        raise RuntimeError(
            f"Could not find articulated carton fixed joint at {fixed_joint_path}"
        )

    UsdPhysics.Joint(fixed_joint_prim).CreateJointEnabledAttr().Set(False)
    UsdPhysics.RigidBodyAPI(body_prim).CreateKinematicEnabledAttr().Set(True)

    return DynamicObjectPhysicsResult(
        physics_mode=physics_mode,
        pose_prim_path=str(body_prim.GetPath()),
        spawn_prim_path=prim_path,
    )


def _signed_flap_angle_deg(joint) -> float:
    lower_limit = joint.GetLowerLimitAttr().Get()
    upper_limit = joint.GetUpperLimitAttr().Get()
    if upper_limit is not None and float(upper_limit) <= 0.0:
        return -1.0
    if lower_limit is not None and float(lower_limit) >= 0.0:
        return 1.0
    return 1.0


def apply_artvip_carton_initial_flap_angles(
    stage,
    *,
    prim_path: str,
    flap_angles_deg: dict[str, float] | None,
) -> None:
    """Set the articulated carton flap bodies to the seeded initial open angles."""
    if not flap_angles_deg:
        return

    from pxr import Gf, UsdGeom, UsdPhysics

    for flap_name, joint_prim in _find_artvip_carton_flap_joint_prims(
        stage, prim_path
    ).items():
        if flap_name not in flap_angles_deg:
            continue

        joint = UsdPhysics.RevoluteJoint(joint_prim)
        body1_targets = joint.GetBody1Rel().GetTargets()
        if len(body1_targets) != 1:
            raise RuntimeError(
                "Expected articulated carton flap joint to target exactly one "
                f"body1 prim: {joint_prim.GetPath()}"
            )

        flap_prim = stage.GetPrimAtPath(body1_targets[0])
        if not flap_prim.IsValid():
            raise RuntimeError(
                "Dynamic object flap prim not found for articulated carton joint "
                f"{joint_prim.GetPath()}: {body1_targets[0]}"
            )

        xformable = UsdGeom.Xformable(flap_prim)
        existing_ops = xformable.GetOrderedXformOps()
        if (
            len(existing_ops) != 1
            or existing_ops[0].GetOpType() != UsdGeom.XformOp.TypeTransform
        ):
            raise RuntimeError(
                "Expected articulated carton flap prim to keep a single authored "
                f"transform op: {flap_prim.GetPath()}"
            )

        base_transform = existing_ops[0].Get()
        translation = base_transform.ExtractTranslation()
        scale = (
            float(base_transform[0][0]),
            float(base_transform[1][1]),
            float(base_transform[2][2]),
        )
        signed_angle_deg = float(flap_angles_deg[flap_name]) * _signed_flap_angle_deg(
            joint
        )
        axis_name = str(joint.GetAxisAttr().Get())

        xformable.ClearXformOpOrder()
        xformable.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble, "").Set(translation)
        if axis_name == "X":
            xformable.AddRotateXOp(UsdGeom.XformOp.PrecisionDouble, "").Set(
                signed_angle_deg
            )
        elif axis_name == "Y":
            xformable.AddRotateYOp(UsdGeom.XformOp.PrecisionDouble, "").Set(
                signed_angle_deg
            )
        elif axis_name == "Z":
            xformable.AddRotateZOp(UsdGeom.XformOp.PrecisionDouble, "").Set(
                signed_angle_deg
            )
        else:
            raise ValueError(f"Unsupported articulated flap joint axis: {axis_name}")
        xformable.AddScaleOp(UsdGeom.XformOp.PrecisionDouble, "").Set(Gf.Vec3d(*scale))


def _normalize_signed_degrees(angle_deg: float) -> float:
    return ((angle_deg + 180.0) % 360.0) - 180.0


def _extract_axis_rotation_deg(relative_transform, axis_name: str) -> float:
    rotation = relative_transform.ExtractRotationMatrix()
    if axis_name == "X":
        angle_rad = math.atan2(float(rotation[2][1]), float(rotation[1][1]))
    elif axis_name == "Y":
        angle_rad = math.atan2(float(rotation[0][2]), float(rotation[0][0]))
    elif axis_name == "Z":
        angle_rad = math.atan2(float(rotation[1][0]), float(rotation[0][0]))
    else:
        raise ValueError(f"Unsupported articulated flap joint axis: {axis_name}")

    return _normalize_signed_degrees(math.degrees(angle_rad))


def get_artvip_carton_flap_angles_deg(
    stage,
    *,
    prim_path: str,
    pose_prim_path: str | None = None,
) -> dict[str, float]:
    """Read articulated-carton flap angles in degrees from runtime USD transforms."""
    from pxr import UsdGeom, UsdPhysics

    body_prim_path = pose_prim_path or str(
        _find_artvip_carton_body_prim(stage, prim_path).GetPath()
    )
    body_prim = stage.GetPrimAtPath(body_prim_path)
    if not body_prim.IsValid():
        raise RuntimeError(f"Dynamic object pose prim not found: {body_prim_path}")

    xform_cache = UsdGeom.XformCache()
    flap_angles_deg: dict[str, float] = {}
    for flap_name, joint_prim in _find_artvip_carton_flap_joint_prims(
        stage, prim_path
    ).items():
        joint = UsdPhysics.RevoluteJoint(joint_prim)
        body1_targets = joint.GetBody1Rel().GetTargets()
        if len(body1_targets) != 1:
            raise RuntimeError(
                "Expected articulated carton flap joint to target exactly one "
                f"body1 prim: {joint_prim.GetPath()}"
            )

        flap_prim = stage.GetPrimAtPath(body1_targets[0])
        if not flap_prim.IsValid():
            raise RuntimeError(
                "Dynamic object flap prim not found for articulated carton joint "
                f"{joint_prim.GetPath()}: {body1_targets[0]}"
            )

        relative_transform, _ = xform_cache.ComputeRelativeTransform(
            flap_prim, body_prim
        )
        angle_deg = _extract_axis_rotation_deg(
            relative_transform,
            str(joint.GetAxisAttr().Get()),
        )
        flap_angles_deg[flap_name] = round(abs(angle_deg), 6)

    return flap_angles_deg


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
        raise ValueError(
            "pose_center_offset_xyz_m must contain exactly 3 values when provided"
        )

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


def _invert_quaternion(
    quaternion_wxyz: list[float],
) -> list[float]:
    """Return the inverse of a quaternion encoded as [w, x, y, z]."""
    w, x, y, z = (float(component) for component in quaternion_wxyz)
    norm_sq = (w * w) + (x * x) + (y * y) + (z * z)
    if norm_sq <= 0.0:
        raise ValueError("quaternion_wxyz must have non-zero magnitude")
    return [w / norm_sq, -x / norm_sq, -y / norm_sq, -z / norm_sq]


def _resolve_spawn_local_pose_center_offset(
    *,
    spawn_anchor_pose: dict[str, list[float]],
    pose_anchor_pose: dict[str, list[float]],
    pose_center_offset_xyz_m: list[float] | tuple[float, float, float] | None,
) -> tuple[float, float, float]:
    """
    Resolve the full local offset from the authored spawn prim to the tracked
    pose center.

    Some runtime USDs expose their dynamic pose from a descendant rigid body
    instead of the referenced root prim. Scene composition authors the spawn
    pose on the referenced root, so we have to include the authored root→pose
    prim transform in addition to any reviewed pose-center offset metadata.
    """
    spawn_rotation_inv = _invert_quaternion(spawn_anchor_pose["rotation"])
    anchor_delta_world = (
        float(pose_anchor_pose["position"][0])
        - float(spawn_anchor_pose["position"][0]),
        float(pose_anchor_pose["position"][1])
        - float(spawn_anchor_pose["position"][1]),
        float(pose_anchor_pose["position"][2])
        - float(spawn_anchor_pose["position"][2]),
    )
    anchor_delta_local = _rotate_vector_by_quaternion(
        anchor_delta_world,
        spawn_rotation_inv,
    )

    pose_center_delta_local = (0.0, 0.0, 0.0)
    if pose_center_offset_xyz_m is not None:
        if len(pose_center_offset_xyz_m) != 3:
            raise ValueError(
                "pose_center_offset_xyz_m must contain exactly 3 values when provided"
            )
        pose_center_delta_world = _rotate_vector_by_quaternion(
            (
                float(pose_center_offset_xyz_m[0]),
                float(pose_center_offset_xyz_m[1]),
                float(pose_center_offset_xyz_m[2]),
            ),
            pose_anchor_pose["rotation"],
        )
        pose_center_delta_local = _rotate_vector_by_quaternion(
            pose_center_delta_world,
            spawn_rotation_inv,
        )

    return (
        anchor_delta_local[0] + pose_center_delta_local[0],
        anchor_delta_local[1] + pose_center_delta_local[1],
        anchor_delta_local[2] + pose_center_delta_local[2],
    )


def get_dynamic_object_runtime_pose_targets(
    stage,
    *,
    prim_path: str,
    physics_mode: str | None,
    pose_prim_path: str | None = None,
) -> dict[str, dict[str, list[float]]]:
    """Capture pre-physics world poses for rigid bodies that need runtime restoration."""
    if physics_mode not in _ARTVIP_ROOT_RIGID_LOCK_MODES:
        return {}

    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        raise RuntimeError(f"Dynamic object prim not found: {prim_path}")

    rigid_body_targets = {
        str(rigid_body_prim.GetPath()): get_dynamic_object_anchor_pose(
            stage,
            prim_path=prim_path,
            pose_prim_path=str(rigid_body_prim.GetPath()),
        )
        for rigid_body_prim in _find_rigid_body_descendants(root_prim)
    }
    if pose_prim_path and pose_prim_path not in rigid_body_targets:
        rigid_body_targets[pose_prim_path] = get_dynamic_object_anchor_pose(
            stage,
            prim_path=prim_path,
            pose_prim_path=pose_prim_path,
        )
    return rigid_body_targets


def apply_dynamic_object_runtime_pose_targets(
    *,
    physics_mode: str | None,
    pose_targets: dict[str, dict[str, list[float]]],
) -> None:
    """Restore rigid-body world poses after physics init when USD xforms are insufficient."""
    if physics_mode not in _ARTVIP_ROOT_RIGID_LOCK_MODES:
        return
    if not pose_targets:
        return

    import numpy as np
    from isaacsim.core.prims import RigidPrim

    zero_velocity = np.zeros((1, 3), dtype=np.float32)
    for pose_prim_path, pose in pose_targets.items():
        position = pose.get("position")
        rotation = pose.get("rotation")
        if position is None and rotation is None:
            continue

        rigid_prim = RigidPrim(
            prim_paths_expr=pose_prim_path,
            name=f"dynamic_object_{pose_prim_path.strip('/').replace('/', '_')}",
            reset_xform_properties=False,
        )
        rigid_prim.initialize()
        rigid_prim.set_world_poses(
            positions=(
                np.asarray([position], dtype=np.float32)
                if position is not None
                else None
            ),
            orientations=(
                np.asarray([rotation], dtype=np.float32)
                if rotation is not None
                else None
            ),
        )
        rigid_prim.set_linear_velocities(zero_velocity)
        rigid_prim.set_angular_velocities(zero_velocity)


def apply_dynamic_object_spawn_pose(
    stage,
    *,
    prim_path: str,
    position: list[float] | None,
    rotation_deg_z: float | None,
    pose_prim_path: str | None = None,
    pose_center_offset_xyz_m: list[float] | tuple[float, float, float] | None = None,
) -> None:
    """Author a shared dynamic-object spawn pose onto the resolved placement prim."""
    from pxr import Gf, UsdGeom

    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"Dynamic object prim not found: {prim_path}")

    xformable = UsdGeom.Xformable(prim)
    translate_op = None
    rotate_z_op = None
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate and translate_op is None:
            translate_op = op
        if op.GetOpType() == UsdGeom.XformOp.TypeRotateZ and rotate_z_op is None:
            rotate_z_op = op

    if position is not None:
        anchor_position = [float(axis) for axis in position]
        if pose_prim_path is not None or pose_center_offset_xyz_m is not None:
            spawn_anchor_pose = get_dynamic_object_anchor_pose(
                stage,
                prim_path=prim_path,
                pose_prim_path=prim_path,
            )
            pose_anchor_pose = get_dynamic_object_anchor_pose(
                stage,
                prim_path=prim_path,
                pose_prim_path=pose_prim_path or prim_path,
            )
            offset_x, offset_y, offset_z = _resolve_spawn_local_pose_center_offset(
                spawn_anchor_pose=spawn_anchor_pose,
                pose_anchor_pose=pose_anchor_pose,
                pose_center_offset_xyz_m=pose_center_offset_xyz_m,
            )
            yaw_rad = math.radians(float(rotation_deg_z or 0.0))
            cos_yaw = math.cos(yaw_rad)
            sin_yaw = math.sin(yaw_rad)
            rotated_offset_x = (offset_x * cos_yaw) - (offset_y * sin_yaw)
            rotated_offset_y = (offset_x * sin_yaw) + (offset_y * cos_yaw)
            anchor_position = [
                anchor_position[0] - rotated_offset_x,
                anchor_position[1] - rotated_offset_y,
                anchor_position[2] - offset_z,
            ]
        if translate_op is None:
            translate_op = xformable.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble, "")
        translate_op.Set(Gf.Vec3d(*anchor_position))

    if rotation_deg_z is not None:
        if rotate_z_op is None:
            rotate_z_op = xformable.AddRotateZOp(UsdGeom.XformOp.PrecisionDouble, "")
        rotate_z_op.Set(float(rotation_deg_z))


def get_dynamic_object_telemetry(
    stage,
    *,
    prim_path: str,
    physics_mode: str | None,
    pose_prim_path: str | None = None,
) -> dict[str, object]:
    """Read shared runtime telemetry for one spawned dynamic object."""
    if physics_mode != ARTVIP_CARTON_BASE_KINEMATIC_MODE:
        return {}

    return {
        "flap_angles_deg": get_artvip_carton_flap_angles_deg(
            stage,
            prim_path=prim_path,
            pose_prim_path=pose_prim_path,
        )
    }
