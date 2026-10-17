"""Generic scene-bundle contract — the embodiment-agnostic input to the verifier.

This is the seam that makes ``scene_verify`` usable on *any* USD scene, not only a
PackingBench manifest row. A producer (a SceneForge approved-bundle QA worker, an
ad-hoc USD author, a different benchmark) describes a scene declaratively:

* ``usd_stage_path`` — the USD to open,
* one ``SceneObjectSpec`` per prim the verifier should grade, each marking whether the
  object is *expected to stay static* (a carton / fixture, graded by metadata) or *free*
  (graded by the passive settle),
* an optional ``support_prim_path`` — the table/ground plane the fall-through gate
  measures against.

The module is **Isaac-free on purpose** (no ``pxr`` / ``trimesh`` / Isaac imports) so the
contract and its validation are unit-testable in the plain project venv. The Isaac runner
(``scripts/tools/verify_usd_bundle.py``) consumes a ``SceneBundle`` and turns it into the
same ``CapturedSceneEvidence`` the PackingBench worker produces — so both paths are graded
by one engine, with no per-consumer scoring drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

#: ``physics_mode`` values whose objects are graded as static (by metadata, not settle).
#: Mirrors ``verify_scene_bundle.STATIC_PHYSICS_MODES`` so a bundle that carries a
#: PackingBench-style ``physics_mode`` resolves staticness identically to the manifest path.
STATIC_PHYSICS_MODES = frozenset(
    {
        "artvip_carton_base_kinematic",
        "preserve_authored_articulation",
    }
)


class SceneBundleError(ValueError):
    """Raised when a bundle is structurally invalid (missing/ill-typed fields)."""


def _as_xyz(value: Any, *, where: str) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise SceneBundleError(f"{where} must be a 3-number [x, y, z], got {value!r}")
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError) as exc:
        raise SceneBundleError(f"{where} must be numeric: {value!r}") from exc


@dataclass(frozen=True)
class SceneObjectSpec:
    """One prim the verifier should grade.

    ``is_static_expected`` is the authoritative flag the engine reads. It may be given
    directly, or derived from ``physics_mode`` (a PackingBench-style hint) when omitted —
    so a manifest-derived bundle and a hand-authored one resolve staticness the same way.
    A static-expected object is graded by ``static_metadata_present`` (does it carry its
    static tag?) and excluded from settle / fall-through / interpenetration grading; a free
    object is settled and graded for drift, fall-through, and pairwise penetration.
    """

    object_id: str
    prim_path: str
    is_static_expected: bool = False
    #: Prim whose world transform is read for the pose; defaults to ``prim_path``.
    pose_prim_path: str | None = None
    #: Offset (m) from the pose prim to the object's geometric centre, if any.
    pose_center_offset_xyz_m: tuple[float, float, float] | None = None
    #: Spawn position (m), used only to seed the interpenetration soundness injector.
    position: tuple[float, float, float] | None = None
    #: Optional PackingBench-style physics mode. ``None`` ⇒ make a plain dynamic rigid body.
    physics_mode: str | None = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "SceneObjectSpec":
        if not isinstance(mapping, Mapping):
            raise SceneBundleError(f"object spec must be a mapping, got {mapping!r}")
        object_id = mapping.get("object_id")
        prim_path = mapping.get("prim_path")
        if not isinstance(object_id, str) or not object_id:
            raise SceneBundleError(f"object spec needs a non-empty 'object_id': {mapping!r}")
        if not isinstance(prim_path, str) or not prim_path.startswith("/"):
            raise SceneBundleError(
                f"object {object_id!r} needs an absolute USD 'prim_path' (got {prim_path!r})"
            )
        physics_mode = mapping.get("physics_mode")
        if physics_mode is not None and not isinstance(physics_mode, str):
            raise SceneBundleError(f"object {object_id!r} 'physics_mode' must be a string")
        if "is_static_expected" in mapping:
            is_static = bool(mapping["is_static_expected"])
        else:
            # Derive from the physics mode exactly as the PackingBench worker does.
            is_static = physics_mode in STATIC_PHYSICS_MODES
        pose_prim_path = mapping.get("pose_prim_path")
        if pose_prim_path is not None and (
            not isinstance(pose_prim_path, str) or not pose_prim_path.startswith("/")
        ):
            raise SceneBundleError(
                f"object {object_id!r} 'pose_prim_path' must be an absolute prim path"
            )
        return cls(
            object_id=object_id,
            prim_path=prim_path,
            is_static_expected=is_static,
            pose_prim_path=pose_prim_path,
            pose_center_offset_xyz_m=_as_xyz(
                mapping.get("pose_center_offset_xyz_m"),
                where=f"object {object_id!r} 'pose_center_offset_xyz_m'",
            ),
            position=_as_xyz(
                mapping.get("position"), where=f"object {object_id!r} 'position'"
            ),
            physics_mode=physics_mode,
        )

    def to_meta(self) -> dict[str, Any]:
        """Project to the ``objects_meta`` dict shape the capture layer consumes.

        Identical keys to ``verify_scene_bundle._meta`` so the shared
        ``capture_scene_evidence`` treats manifest-built and bundle-built objects alike.
        """
        return {
            "object_id": self.object_id,
            "prim_path": self.prim_path,
            "pose_prim_path": self.pose_prim_path or self.prim_path,
            "pose_center_offset_xyz_m": (
                list(self.pose_center_offset_xyz_m)
                if self.pose_center_offset_xyz_m is not None
                else None
            ),
            "position": list(self.position) if self.position is not None else None,
            "physics_mode": self.physics_mode,
            "is_static_expected": self.is_static_expected,
        }


@dataclass(frozen=True)
class SceneBundle:
    """A declarative, benchmark-independent description of a scene to verify."""

    scene_id: str
    usd_stage_path: str
    objects: tuple[SceneObjectSpec, ...]
    support_prim_path: str | None = None
    #: Optional override for the passive-settle window; ``None`` ⇒ use threshold default.
    settle_steps: int | None = None
    #: Free-form provenance carried into evidence (producer, source, etc.).
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "SceneBundle":
        if not isinstance(mapping, Mapping):
            raise SceneBundleError(f"bundle must be a mapping, got {mapping!r}")
        scene_id = mapping.get("scene_id")
        usd_stage_path = mapping.get("usd_stage_path")
        if not isinstance(scene_id, str) or not scene_id:
            raise SceneBundleError("bundle needs a non-empty 'scene_id'")
        if not isinstance(usd_stage_path, str) or not usd_stage_path:
            raise SceneBundleError("bundle needs a non-empty 'usd_stage_path'")
        raw_objects = mapping.get("objects")
        if not isinstance(raw_objects, Sequence) or isinstance(raw_objects, (str, bytes)):
            raise SceneBundleError("bundle 'objects' must be a list")
        if not raw_objects:
            raise SceneBundleError("bundle 'objects' must declare at least one object")
        objects = tuple(SceneObjectSpec.from_mapping(obj) for obj in raw_objects)
        ids = [obj.object_id for obj in objects]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise SceneBundleError(f"bundle has duplicate object_id(s): {dupes}")
        support_prim_path = mapping.get("support_prim_path")
        if support_prim_path is not None and (
            not isinstance(support_prim_path, str) or not support_prim_path.startswith("/")
        ):
            raise SceneBundleError("'support_prim_path' must be an absolute prim path or null")
        settle_steps = mapping.get("settle_steps")
        if settle_steps is not None:
            if not isinstance(settle_steps, int) or isinstance(settle_steps, bool) or settle_steps < 0:
                raise SceneBundleError("'settle_steps' must be a non-negative integer or null")
        provenance = mapping.get("provenance") or {}
        if not isinstance(provenance, Mapping):
            raise SceneBundleError("'provenance' must be a mapping")
        return cls(
            scene_id=scene_id,
            usd_stage_path=usd_stage_path,
            objects=objects,
            support_prim_path=support_prim_path,
            settle_steps=settle_steps,
            provenance=dict(provenance),
        )

    @classmethod
    def from_json_file(cls, path: Path | str) -> "SceneBundle":
        text = Path(path).read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SceneBundleError(f"bundle {path} is not valid JSON: {exc}") from exc
        return cls.from_mapping(data)

    def objects_meta(self) -> list[dict[str, Any]]:
        """The full ``objects_meta`` list the capture layer iterates over."""
        return [obj.to_meta() for obj in self.objects]

    def dynamic_object_specs(self) -> list[SceneObjectSpec]:
        """Objects that should be made into free dynamic rigid bodies before settling."""
        return [obj for obj in self.objects if not obj.is_static_expected]
