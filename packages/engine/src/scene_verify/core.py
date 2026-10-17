"""Isaac-free core of the embodiment-agnostic scene verifier.

This module owns the *decision* layer of scene verification: it turns already-captured
scene evidence (poses before/after a passive settle, world AABBs, per-object visual-vs-
collision mesh divergence numbers, static-tag presence) into a three-state
``pass``/``warn``/``fail`` report with explicit, single-root-cause bucket attribution.

The engine is standalone — it takes a generic ``CapturedSceneEvidence`` (produced by any
USD/Isaac adapter) and emits a verdict; it has no dependency on PackingBench, SceneForge,
or any particular benchmark. It deliberately imports neither ``trimesh``/``pxr`` nor any
Isaac runtime at module top-level, so the whole decision layer is unit-testable in a plain
venv. Heavy geometry extraction lives in ``scene_verify.geometry``; the Isaac stage
load/step lives in ``scene_verify.capture`` and the runners that call it (the engine's
``scene_verify.runners.usd_bundle``, PackingBench's runner in RoboEval).

The report serialises to :meth:`SceneVerifyReport.to_verdict_json` — the stable
``scene_verify/1`` verdict that consumers (a SceneForge QA gate, a PackingBench eval)
read. Consumer-specific projections (e.g. PackingBench's legacy six-check summary) live in
that consumer's adapter, never here.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

# The scene_verify/1 contract (schema version, statuses and buckets, each bucket naming exactly
# one root cause) lives in the stdlib-only scene_verify_contract distribution, so the engine
# and every consumer share one definition.
from scene_verify_contract import GATE_STATUSES, SCHEMA_VERSION, Bucket, GateStatus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERIFIER_VERSION = "0.2.0"

#: GATE_STATUSES runs from least to most severe, so this is pass 0, warn 1, fail 2.
_STATUS_RANK: dict[str, int] = {status: rank for rank, status in enumerate(GATE_STATUSES)}


def worst_status(statuses: Sequence[str]) -> GateStatus:
    """Return the most severe status (``fail`` > ``warn`` > ``pass``)."""
    worst = "pass"
    for status in statuses:
        if _STATUS_RANK.get(status, 0) > _STATUS_RANK[worst]:
            worst = status
    return worst  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Thresholds (single source of truth lives in thresholds.yaml beside this module)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifyThresholds:
    """All tunables for the verifier; loaded from YAML, never hardcoded at call sites."""

    settle_steps: int
    max_linear_displacement_m: float
    max_angular_displacement_deg: float
    pose_alignment_tolerance_m: float
    table_contact_tolerance_m: float
    mesh_n_samples: int
    mesh_bvh_skip_margin_m: float
    mesh_phantom_warn_m: float
    mesh_phantom_fail_m: float
    mesh_clip_warn_m: float
    mesh_clip_fail_m: float
    interpenetration_max_penetration_depth_m: float
    interpenetration_max_overlap_volume_m3: float
    fall_through_max_bottom_below_table_m: float
    fidelity_min_face_count_fail: int
    fidelity_min_face_count_warn: int
    fidelity_min_area_ratio_warn: float
    fidelity_min_registered_ratio_fail: float
    fidelity_min_registered_ratio_warn: float
    defect_oversize_factor: float
    defect_undersize_factor: float
    defect_interpenetration_overlap_m: float

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "VerifyThresholds":
        root = mapping.get("scene_verify", mapping)
        settle = root["settle"]
        mesh = root["mesh_agreement"]
        interpenetration = root["interpenetration"]
        fall_through = root["fall_through"]
        # Absent section falls back to shipped defaults so a pre-0.2 external thresholds
        # override file keeps loading; the shipped thresholds.yaml always carries it.
        fidelity = root.get("fidelity") or {}
        defects = root["defects"]
        return cls(
            settle_steps=int(settle["settle_steps"]),
            max_linear_displacement_m=float(settle["max_linear_displacement_m"]),
            max_angular_displacement_deg=float(settle["max_angular_displacement_deg"]),
            pose_alignment_tolerance_m=float(settle["pose_alignment_tolerance_m"]),
            table_contact_tolerance_m=float(settle["table_contact_tolerance_m"]),
            mesh_n_samples=int(mesh["n_samples"]),
            mesh_bvh_skip_margin_m=float(mesh["bvh_skip_margin_m"]),
            mesh_phantom_warn_m=float(mesh["phantom_warn_m"]),
            mesh_phantom_fail_m=float(mesh["phantom_fail_m"]),
            mesh_clip_warn_m=float(mesh["clip_warn_m"]),
            mesh_clip_fail_m=float(mesh["clip_fail_m"]),
            interpenetration_max_penetration_depth_m=float(
                interpenetration["max_penetration_depth_m"]
            ),
            interpenetration_max_overlap_volume_m3=float(
                interpenetration["max_overlap_volume_m3"]
            ),
            fall_through_max_bottom_below_table_m=float(
                fall_through["max_bottom_below_table_m"]
            ),
            fidelity_min_face_count_fail=int(fidelity.get("min_face_count_fail", 2000)),
            fidelity_min_face_count_warn=int(fidelity.get("min_face_count_warn", 50000)),
            fidelity_min_area_ratio_warn=float(fidelity.get("min_area_ratio_warn", 0.01)),
            fidelity_min_registered_ratio_fail=float(
                fidelity.get("min_registered_ratio_fail", 0.15)
            ),
            fidelity_min_registered_ratio_warn=float(
                fidelity.get("min_registered_ratio_warn", 0.5)
            ),
            defect_oversize_factor=float(defects["oversize_factor"]),
            defect_undersize_factor=float(defects["undersize_factor"]),
            defect_interpenetration_overlap_m=float(defects["interpenetration_overlap_m"]),
        )


def default_thresholds_path() -> Path:
    """Path to the YAML shipped beside this module (the single source of truth)."""
    return Path(__file__).resolve().parent / "thresholds.yaml"


def load_verify_thresholds(path: Path | str | None = None) -> VerifyThresholds:
    """Load thresholds from ``path`` (or the adjacent default YAML when ``None``)."""
    import yaml  # local import: keeps module import dependency-light

    resolved = Path(path) if path is not None else default_thresholds_path()
    with resolved.open("r", encoding="utf-8") as handle:
        mapping = yaml.safe_load(handle)
    if not isinstance(mapping, Mapping):
        raise ValueError(f"scene_verify thresholds file is not a mapping: {resolved}")
    return VerifyThresholds.from_mapping(mapping)


# ---------------------------------------------------------------------------
# Captured evidence (produced by the Isaac runner; consumed here)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapturedObjectEvidence:
    """Per-object evidence captured around the passive settle window."""

    object_id: str
    is_static_expected: bool = False
    # Pose dicts: {"position": [x, y, z], "rotation": [qw, qx, qy, qz]}.
    pose_before: Mapping[str, Any] | None = None
    pose_after: Mapping[str, Any] | None = None
    # World AABB after settle as [min_x, min_y, min_z, max_x, max_y, max_z].
    aabb_after: Sequence[float] | None = None
    # Output of scene_verify.geometry.directional_mesh_divergence (or None if not run):
    #   {mesh_present: bool, mode: str, phantom_max_m, phantom_p95_m, clip_max_m, clip_p95_m}
    mesh_divergence: Mapping[str, Any] | None = None
    # Pure USD static-tag scan result for static-expected objects (None => not scanned).
    has_static_tag: bool | None = None


@dataclass(frozen=True)
class CapturedPairOverlap:
    """A single object-pair overlap.

    ``overlap_volume_m3`` / ``geometry_overlap_detected`` come from the coarse
    ``aabb_overlap_xyz`` pre-pass. ``penetration_depth_m`` is the refined mesh/contact-level
    depth between the two collision proxies (``None`` when not computed — e.g. older evidence
    or a pair with no usable collision geometry, in which case the gate falls back to the
    AABB-volume floor).
    """

    object_a: str
    object_b: str
    overlap_volume_m3: float
    geometry_overlap_detected: bool
    penetration_depth_m: float | None = None


@dataclass(frozen=True)
class CapturedSceneEvidence:
    """All evidence needed to score a scene, captured by the Isaac runner."""

    objects: tuple[CapturedObjectEvidence, ...]
    load_ok: bool
    load_detail: Mapping[str, Any] = field(default_factory=dict)
    table_top_z_m: float | None = None
    pairwise_overlaps: tuple[CapturedPairOverlap, ...] = ()
    #: Same pair measurements taken at t=0, BEFORE the passive settle. PhysX depenetrates
    #: authored overlaps within the first settle steps, so the post-settle capture alone is
    #: structurally blind to them — this is the authored-state signal the gate grades too.
    pairwise_overlaps_pre_settle: tuple[CapturedPairOverlap, ...] = ()
    #: Reconstruction-fidelity evidence, present only for scenes whose bundle declares
    #: reconstruction provenance: {"declared": {registered_images, total_frames},
    #: "measured": {face_count, mesh_area, aabb_area, area_ratio}}. ``None`` ⇒ the scene is
    #: not a reconstruction and fidelity gates are not applicable.
    recon_fidelity: Mapping[str, Any] | None = None


# ---------------------------------------------------------------------------
# Gate results + report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateResult:
    """One verifier gate outcome. ``bucket`` is the fixed single root-cause class."""

    gate: str
    status: GateStatus
    bucket: Bucket
    score: float | None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "status": self.status,
            "score": self.score,
            "bucket": self.bucket,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class SceneVerifyReport:
    """Aggregate verifier verdict for one scene."""

    scene_id: str
    overall_status: GateStatus
    verified_at: str
    gates: tuple[GateResult, ...]
    verifier_version: str = VERIFIER_VERSION
    #: sha256 hex of the exact USD stage this verdict grades (single-file bundles only).
    #: Binds the verdict to the geometry content: a consumer holding the USD can reject a
    #: verdict produced for different bytes. Optional/additive within scene_verify/1.
    usd_sha256: str | None = None

    @classmethod
    def from_gates(
        cls,
        *,
        scene_id: str,
        gates: Sequence[GateResult],
        verified_at: str,
        usd_sha256: str | None = None,
    ) -> "SceneVerifyReport":
        overall = worst_status([gate.status for gate in gates])
        return cls(
            scene_id=scene_id,
            overall_status=overall,
            verified_at=verified_at,
            gates=tuple(gates),
            usd_sha256=usd_sha256,
        )

    @property
    def bucket_attribution(self) -> dict[str, list[str]]:
        """Map each root-cause bucket to the non-passing gate(s) attributed to it."""
        attribution: dict[str, list[str]] = {}
        for gate in self.gates:
            if gate.status == "pass":
                continue
            attribution.setdefault(gate.bucket, []).append(gate.gate)
        return attribution

    def gate(self, name: str) -> GateResult | None:
        for gate in self.gates:
            if gate.gate == name:
                return gate
        return None

    def to_verdict_json(self) -> dict[str, Any]:
        """Stable ``scene_verify/1`` verdict that any consumer reads (a PackingBench eval,
        a SceneForge QA gate)."""
        verdict: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "scene_id": self.scene_id,
            "overall_status": self.overall_status,
            "verified_at": self.verified_at,
            "verifier_version": self.verifier_version,
            "gates": [gate.to_json() for gate in self.gates],
            "bucket_attribution": self.bucket_attribution,
        }
        if self.usd_sha256 is not None:
            verdict["usd_sha256"] = self.usd_sha256
        return verdict


# ---------------------------------------------------------------------------
# Gate builders (pure functions over captured evidence)
# ---------------------------------------------------------------------------


def _quaternion_angle_deg(
    quat_a: Sequence[float] | None, quat_b: Sequence[float] | None
) -> float | None:
    """Geodesic angle (degrees) between two unit quaternions [qw, qx, qy, qz]."""
    if quat_a is None or quat_b is None or len(quat_a) != 4 or len(quat_b) != 4:
        return None
    dot = sum(float(a) * float(b) for a, b in zip(quat_a, quat_b))
    dot = max(-1.0, min(1.0, abs(dot)))
    return math.degrees(2.0 * math.acos(dot))


def _linear_displacement_m(
    pose_before: Mapping[str, Any] | None, pose_after: Mapping[str, Any] | None
) -> float | None:
    if not pose_before or not pose_after:
        return None
    before = pose_before.get("position")
    after = pose_after.get("position")
    if not before or not after or len(before) != 3 or len(after) != 3:
        return None
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(after, before)))


def build_scene_load_gate(captured: CapturedSceneEvidence) -> GateResult:
    return GateResult(
        gate="scene_load",
        status="pass" if captured.load_ok else "fail",
        bucket="load",
        score=0.0 if captured.load_ok else 1.0,
        detail=dict(captured.load_detail),
    )


def evaluate_mesh_agreement_gate(
    object_divergences: Mapping[str, Mapping[str, Any]],
    config: VerifyThresholds,
) -> GateResult:
    """Threshold the (already-computed) directional visual-vs-collision divergence.

    Uses directional/signed depths only — never symmetric Chamfer. ``phantom_*`` is
    collision-outside-visual (phantom contacts); ``clip_*`` is visual-outside-collision
    (clip-through / missing collision parts). A missing visual or collision mesh is an
    asset gap routed to the ``labeling`` bucket as ``warn`` (not a physics failure).
    """
    if not object_divergences:
        return GateResult(
            gate="visual_collision_agreement",
            status="warn",
            bucket="labeling",
            score=None,
            detail={"reason": "no objects carried mesh divergence evidence"},
        )

    statuses: list[str] = []
    buckets: list[Bucket] = []
    worst_score = 0.0
    worst_object: dict[str, Any] = {}
    per_object: list[dict[str, Any]] = []

    for object_id, divergence in object_divergences.items():
        mesh_present = bool(divergence.get("mesh_present", False))
        if not mesh_present:
            statuses.append("warn")
            buckets.append("labeling")
            per_object.append(
                {"object_id": object_id, "mode": "missing", "mesh_present": False}
            )
            continue

        phantom_max = float(divergence.get("phantom_max_m", 0.0) or 0.0)
        clip_max = float(divergence.get("clip_max_m", 0.0) or 0.0)
        phantom_ratio = phantom_max / config.mesh_phantom_fail_m if config.mesh_phantom_fail_m else 0.0
        clip_ratio = clip_max / config.mesh_clip_fail_m if config.mesh_clip_fail_m else 0.0
        score = max(0.0, min(1.0, max(phantom_ratio, clip_ratio)))

        if phantom_max > config.mesh_phantom_fail_m or clip_max > config.mesh_clip_fail_m:
            status: GateStatus = "fail"
        elif phantom_max > config.mesh_phantom_warn_m or clip_max > config.mesh_clip_warn_m:
            status = "warn"
        else:
            status = "pass"

        statuses.append(status)
        buckets.append("mesh_disagreement")
        record = {
            "object_id": object_id,
            "mode": divergence.get("mode", "sampled"),
            "phantom_max_m": round(phantom_max, 6),
            "clip_max_m": round(clip_max, 6),
            "score": round(score, 4),
            "status": status,
        }
        per_object.append(record)
        if score >= worst_score:
            worst_score = score
            worst_object = record

    overall = worst_status(statuses)
    # Pick the bucket of the most-severe contributing object.
    bucket: Bucket = "mesh_disagreement"
    for status, candidate in zip(statuses, buckets):
        if status == overall:
            bucket = candidate
            break

    return GateResult(
        gate="visual_collision_agreement",
        status=overall,
        bucket=bucket,
        score=round(worst_score, 4),
        detail={"worst_object": worst_object, "objects": per_object},
    )


def build_interpenetration_gate(
    captured: CapturedSceneEvidence, config: VerifyThresholds
) -> GateResult:
    """Fail when two objects' collision geometry actually interpenetrates.

    The primary signal is mesh/contact-level penetration depth between collision proxies:
    AABB overlap is necessary but not sufficient (two validly-placed items can have bounding
    boxes that clip at a corner while the meshes never touch — the corpus surfaced 7 mm³ AABB
    overlaps that were exactly this false-positive). A pair fails only when its
    ``penetration_depth_m`` exceeds the depth tolerance. When mesh depth was not captured for
    a pair (no usable collision geometry), the gate falls back to the coarse AABB-volume floor
    so it never silently passes a pair it could not assess at mesh level.

    Two capture phases are graded with the same thresholds. ``authored`` (t=0, before any
    physics step) sees overlaps as the scene was authored — PhysX depenetrates them within the
    first settle steps, so grading only the settled state is structurally blind to exactly the
    defect this gate exists for. ``settled`` (post-settle) sees residual clashes physics could
    not resolve.
    """
    offenders: list[dict[str, Any]] = []
    max_depth = 0.0
    max_volume = 0.0
    phases = (
        ("authored", captured.pairwise_overlaps_pre_settle),
        ("settled", captured.pairwise_overlaps),
    )
    for phase, phase_overlaps in phases:
        for overlap in phase_overlaps:
            max_volume = max(max_volume, overlap.overlap_volume_m3)
            if not overlap.geometry_overlap_detected:
                continue
            depth = overlap.penetration_depth_m
            # A non-finite depth (NaN from degenerate signed-distance sampling) must not be
            # compared against the tolerance — `NaN > x` is False, which silently passed a
            # pair the gate could not assess (caught live by the soundness matrix). Treat it
            # as not-captured so the pair falls back to the AABB-volume floor.
            if depth is not None and not math.isfinite(depth):
                depth = None
            if depth is not None:
                max_depth = max(max_depth, depth)
                if depth > config.interpenetration_max_penetration_depth_m:
                    offenders.append(
                        {
                            "object_a": overlap.object_a,
                            "object_b": overlap.object_b,
                            "penetration_depth_m": round(depth, 6),
                            "overlap_volume_m3": round(overlap.overlap_volume_m3, 9),
                            "basis": "mesh_penetration",
                            "phase": phase,
                        }
                    )
            elif overlap.overlap_volume_m3 > config.interpenetration_max_overlap_volume_m3:
                offenders.append(
                    {
                        "object_a": overlap.object_a,
                        "object_b": overlap.object_b,
                        "overlap_volume_m3": round(overlap.overlap_volume_m3, 9),
                        "basis": "aabb_volume_fallback",
                        "phase": phase,
                    }
                )
    status: GateStatus = "fail" if offenders else "pass"
    return GateResult(
        gate="interpenetration",
        status=status,
        bucket="interpenetration",
        score=1.0 if offenders else 0.0,
        detail={
            "offenders": offenders,
            "max_penetration_depth_m": round(max_depth, 6),
            "max_overlap_volume_m3": round(max_volume, 9),
        },
    )


def build_static_settle_gate(
    captured: CapturedSceneEvidence, config: VerifyThresholds
) -> GateResult:
    """Fail when any object drifts past linear/angular tolerance over the settle window.

    Reads ONLY pose deltas. It never inspects static tags, so a missing-static-metadata
    defect cannot be mis-attributed here (that is the ``static_metadata_present`` gate).
    """
    max_linear = 0.0
    max_angular = 0.0
    offenders: list[dict[str, Any]] = []
    unassessed: list[str] = []
    # Only objects expected to be free/dynamic are graded for settle stability. A
    # static-expected object that drifts is a metadata defect (static_metadata_present),
    # never a physics-instability one — keeping the buckets structurally disjoint.
    for obj in captured.objects:
        if obj.is_static_expected:
            continue
        linear = _linear_displacement_m(obj.pose_before, obj.pose_after)
        angular = _quaternion_angle_deg(
            (obj.pose_before or {}).get("rotation"),
            (obj.pose_after or {}).get("rotation"),
        )
        if linear is None and angular is None:
            # Pose capture failed for this object: it must not silently grade as settled.
            unassessed.append(obj.object_id)
        if linear is not None:
            max_linear = max(max_linear, linear)
        if angular is not None:
            max_angular = max(max_angular, angular)
        if (linear is not None and linear > config.max_linear_displacement_m) or (
            angular is not None and angular > config.max_angular_displacement_deg
        ):
            offenders.append(
                {
                    "object_id": obj.object_id,
                    "linear_displacement_m": None if linear is None else round(linear, 6),
                    "angular_displacement_deg": None
                    if angular is None
                    else round(angular, 4),
                }
            )
    status: GateStatus = "fail" if offenders else ("warn" if unassessed else "pass")
    score = max(
        max_linear / config.max_linear_displacement_m
        if config.max_linear_displacement_m
        else 0.0,
        max_angular / config.max_angular_displacement_deg
        if config.max_angular_displacement_deg
        else 0.0,
    )
    return GateResult(
        gate="static_settle",
        status=status,
        bucket="physics_instability",
        score=round(max(0.0, min(1.0, score)), 4),
        detail={
            "max_linear_displacement_m": round(max_linear, 6),
            "max_angular_displacement_deg": round(max_angular, 4),
            "offenders": offenders,
            "unassessed_objects": unassessed,
        },
    )


def build_fall_through_gate(
    captured: CapturedSceneEvidence, config: VerifyThresholds
) -> GateResult:
    """Fail when any object's settled AABB bottom drops below the table support plane."""
    if captured.table_top_z_m is None:
        return GateResult(
            gate="fall_through",
            status="warn",
            bucket="fall_through",
            score=None,
            detail={"reason": "no table support plane captured"},
        )
    floor_z = captured.table_top_z_m - config.fall_through_max_bottom_below_table_m
    offenders: list[dict[str, Any]] = []
    unassessed: list[str] = []
    min_bottom = None
    for obj in captured.objects:
        # Static-expected support geometry is excluded for the same reason as settle.
        if obj.is_static_expected:
            continue
        if not obj.aabb_after or len(obj.aabb_after) != 6:
            unassessed.append(obj.object_id)  # no bounds captured: not silently floored
            continue
        bottom_z = float(obj.aabb_after[2])
        min_bottom = bottom_z if min_bottom is None else min(min_bottom, bottom_z)
        if bottom_z < floor_z:
            offenders.append({"object_id": obj.object_id, "bottom_z_m": round(bottom_z, 6)})
    status: GateStatus = "fail" if offenders else ("warn" if unassessed else "pass")
    return GateResult(
        gate="fall_through",
        status=status,
        bucket="fall_through",
        score=1.0 if offenders else 0.0,
        detail={
            "table_top_z_m": round(captured.table_top_z_m, 6),
            "floor_threshold_z_m": round(floor_z, 6),
            "min_bottom_z_m": None if min_bottom is None else round(min_bottom, 6),
            "offenders": offenders,
            "unassessed_objects": unassessed,
        },
    )


def build_static_metadata_gate(captured: CapturedSceneEvidence) -> GateResult:
    """Fail when a static-expected object lacks its static tag.

    Reads ONLY the USD tag scan. It never inspects pose deltas, keeping
    ``missing_static_metadata`` structurally separate from ``physics_instability``.
    """
    missing = [
        obj.object_id
        for obj in captured.objects
        if obj.is_static_expected and obj.has_static_tag is False
    ]
    unscanned = [
        obj.object_id
        for obj in captured.objects
        if obj.is_static_expected and obj.has_static_tag is None
    ]
    status: GateStatus = "fail" if missing else ("warn" if unscanned else "pass")
    return GateResult(
        gate="static_metadata_present",
        status=status,
        bucket="missing_static_metadata",
        score=1.0 if missing else 0.0,
        detail={"objects_missing_static_tag": missing, "objects_unscanned": unscanned},
    )


def build_recon_registration_gate(
    fidelity: Mapping[str, Any], config: VerifyThresholds
) -> GateResult:
    """Grade the declared SfM registration ratio of a reconstruction.

    A reconstruction where most source frames never registered is built from a sliver of the
    footage — the surface may be locally self-consistent yet cover almost none of the scene.
    The ratio is *declared* by the producer (the verifier cannot re-run SfM), so the basis is
    recorded and a bundle that omits the numbers warns rather than silently passing.
    """
    declared = fidelity.get("declared") or {}
    registered = declared.get("registered_images")
    total = declared.get("total_frames")
    if not isinstance(registered, int) or not isinstance(total, int) or total <= 0:
        return GateResult(
            gate="recon_registration_coverage",
            status="warn",
            bucket="reconstruction_fidelity",
            score=None,
            detail={"reason": "registration counts not declared in bundle provenance"},
        )
    ratio = registered / total
    if ratio < config.fidelity_min_registered_ratio_fail:
        status: GateStatus = "fail"
    elif ratio < config.fidelity_min_registered_ratio_warn:
        status = "warn"
    else:
        status = "pass"
    return GateResult(
        gate="recon_registration_coverage",
        status=status,
        bucket="reconstruction_fidelity",
        score=round(max(0.0, min(1.0, 1.0 - ratio)), 4),
        detail={
            "registered_images": registered,
            "total_frames": total,
            "registered_ratio": round(ratio, 4),
            "fail_below": config.fidelity_min_registered_ratio_fail,
            "warn_below": config.fidelity_min_registered_ratio_warn,
            "basis": "declared_by_producer",
        },
    )


def build_recon_density_gate(
    fidelity: Mapping[str, Any], config: VerifyThresholds
) -> GateResult:
    """Grade measured surface density of a reconstruction.

    Two signals, both measured from the stage (never trusted from the producer): absolute
    triangle count (scale-invariant; a room-scale scene represented by a few hundred faces is
    a degenerate shell regardless of units) and mesh-area / AABB-surface-area ratio (also
    scale-invariant; a thin sliver in a large bounding volume covers almost none of it).
    Face count below the fail line fails; the area ratio is a warn-only co-signal.
    """
    measured = fidelity.get("measured") or {}
    face_count = measured.get("face_count")
    if not isinstance(face_count, int):
        return GateResult(
            gate="recon_surface_density",
            status="warn",
            bucket="reconstruction_fidelity",
            score=None,
            detail={"reason": "mesh stats could not be measured from the stage"},
        )
    area_ratio = measured.get("area_ratio")
    if face_count < config.fidelity_min_face_count_fail:
        status: GateStatus = "fail"
    elif face_count < config.fidelity_min_face_count_warn or (
        isinstance(area_ratio, (int, float))
        and area_ratio < config.fidelity_min_area_ratio_warn
    ):
        status = "warn"
    else:
        status = "pass"
    score = 1.0 - min(1.0, face_count / config.fidelity_min_face_count_warn)
    return GateResult(
        gate="recon_surface_density",
        status=status,
        bucket="reconstruction_fidelity",
        score=round(score, 4),
        detail={
            "face_count": face_count,
            "area_ratio": None
            if not isinstance(area_ratio, (int, float))
            else round(float(area_ratio), 6),
            "face_count_fail_below": config.fidelity_min_face_count_fail,
            "face_count_warn_below": config.fidelity_min_face_count_warn,
            "area_ratio_warn_below": config.fidelity_min_area_ratio_warn,
            "basis": "measured_from_stage",
        },
    )


# ---------------------------------------------------------------------------
# Top-level evaluation
# ---------------------------------------------------------------------------


def evaluate_scene_verify(
    *,
    scene_id: str,
    captured: CapturedSceneEvidence,
    config: VerifyThresholds,
    verified_at: str,
    usd_sha256: str | None = None,
) -> SceneVerifyReport:
    """Build the full ordered gate set and aggregate into a report."""
    object_divergences = {
        obj.object_id: obj.mesh_divergence
        for obj in captured.objects
        if obj.mesh_divergence is not None
    }
    gates = [
        build_scene_load_gate(captured),
        evaluate_mesh_agreement_gate(object_divergences, config),
        build_interpenetration_gate(captured, config),
        build_static_settle_gate(captured, config),
        build_fall_through_gate(captured, config),
        build_static_metadata_gate(captured),
    ]
    # Fidelity gates apply only to scenes that declare themselves reconstructions — a curated
    # benchmark asset is legitimately low-poly, so grading its density would be meaningless.
    # The applicability switch is the producer's declaration; a reconstruction that omits it
    # is graded physics-only (documented producer-honesty boundary, not a silent hole).
    if captured.recon_fidelity is not None:
        gates.append(build_recon_registration_gate(captured.recon_fidelity, config))
        gates.append(build_recon_density_gate(captured.recon_fidelity, config))
    return SceneVerifyReport.from_gates(
        scene_id=scene_id, gates=gates, verified_at=verified_at, usd_sha256=usd_sha256
    )


# ---------------------------------------------------------------------------
# Artifact serialisation (durable; written by the runners)
# ---------------------------------------------------------------------------


def _evidence_to_dict(captured: CapturedSceneEvidence) -> dict[str, Any]:
    return {
        "load_ok": captured.load_ok,
        "load_detail": dict(captured.load_detail),
        "table_top_z_m": captured.table_top_z_m,
        "objects": [
            {
                "object_id": obj.object_id,
                "is_static_expected": obj.is_static_expected,
                "pose_before": None if obj.pose_before is None else dict(obj.pose_before),
                "pose_after": None if obj.pose_after is None else dict(obj.pose_after),
                "aabb_after": None if obj.aabb_after is None else list(obj.aabb_after),
                "mesh_divergence": None
                if obj.mesh_divergence is None
                else dict(obj.mesh_divergence),
                "has_static_tag": obj.has_static_tag,
            }
            for obj in captured.objects
        ],
        "pairwise_overlaps": [
            {
                "object_a": overlap.object_a,
                "object_b": overlap.object_b,
                "overlap_volume_m3": overlap.overlap_volume_m3,
                "geometry_overlap_detected": overlap.geometry_overlap_detected,
                "penetration_depth_m": overlap.penetration_depth_m,
            }
            for overlap in captured.pairwise_overlaps
        ],
        "pairwise_overlaps_pre_settle": [
            {
                "object_a": overlap.object_a,
                "object_b": overlap.object_b,
                "overlap_volume_m3": overlap.overlap_volume_m3,
                "geometry_overlap_detected": overlap.geometry_overlap_detected,
                "penetration_depth_m": overlap.penetration_depth_m,
            }
            for overlap in captured.pairwise_overlaps_pre_settle
        ],
        "recon_fidelity": None
        if captured.recon_fidelity is None
        else dict(captured.recon_fidelity),
    }


def scene_verify_out_dir(artifacts_dir: Path | str, scene_id: str) -> Path:
    """Canonical per-scene artifacts directory (shared by the engine and its consumers).

    ``scene_id`` comes from the (possibly external) bundle — flatten path separators and
    dots so an id like ``../../x`` cannot escape the artifacts tree.
    """
    safe = scene_id.replace("/", "_").replace("\\", "_").replace("..", "_")
    return Path(artifacts_dir) / "scene_verify" / safe


def dump_report(
    *,
    report: SceneVerifyReport,
    captured: CapturedSceneEvidence,
    artifacts_dir: Path | str,
) -> dict[str, Path]:
    """Write the generic verdict.json + evidence.json under a durable dir.

    Consumer-specific projections (e.g. PackingBench's legacy validation_summary.json) are
    written by that consumer's adapter, not here — the engine stays benchmark-agnostic.
    """
    out_dir = scene_verify_out_dir(artifacts_dir, report.scene_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    verdict_path = out_dir / "verdict.json"
    evidence_path = out_dir / "evidence.json"

    verdict_path.write_text(
        json.dumps(report.to_verdict_json(), indent=2, sort_keys=False),
        encoding="utf-8",
    )
    evidence_path.write_text(
        json.dumps(_evidence_to_dict(captured), indent=2, sort_keys=False),
        encoding="utf-8",
    )
    return {"verdict": verdict_path, "evidence": evidence_path}
