"""Deterministic AABB overlap between two prims' world bounds.

Copied from RoboEval's ``app/benchmarks/packingbench/runtime_contact.py`` (ffda3a96) with only
what the engine's capture layer calls: ``aabb_overlap_xyz``, its bounds normaliser and the
per-axis tolerance. RoboEval keeps its PackingBench contact-filter and contact-group helpers;
this copy is maintained here (scene-verify-0001).
"""

from __future__ import annotations

from collections.abc import Sequence

CONTACT_AABB_OVERLAP_AXIS_TOLERANCE_M = 0.001


def _normalize_bounds_xyz(
    bounds_xyz: Sequence[float] | None,
) -> tuple[float, float, float, float, float, float] | None:
    if bounds_xyz is None or len(bounds_xyz) != 6:
        return None
    return tuple(float(value) for value in bounds_xyz)


def aabb_overlap_xyz(
    first_bounds_xyz: Sequence[float] | None,
    second_bounds_xyz: Sequence[float] | None,
) -> dict[str, object]:
    """Return deterministic 3D AABB overlap diagnostics for two prim bounds."""
    first_bounds = _normalize_bounds_xyz(first_bounds_xyz)
    second_bounds = _normalize_bounds_xyz(second_bounds_xyz)
    if first_bounds is None or second_bounds is None:
        return {
            "bounds_available": False,
            "overlap_x_m": None,
            "overlap_y_m": None,
            "overlap_z_m": None,
            "overlap_volume_m3": None,
            "geometry_overlap_detected": False,
        }

    overlap_x = max(
        0.0,
        min(first_bounds[3], second_bounds[3]) - max(first_bounds[0], second_bounds[0]),
    )
    overlap_y = max(
        0.0,
        min(first_bounds[4], second_bounds[4]) - max(first_bounds[1], second_bounds[1]),
    )
    overlap_z = max(
        0.0,
        min(first_bounds[5], second_bounds[5]) - max(first_bounds[2], second_bounds[2]),
    )
    overlap_volume = overlap_x * overlap_y * overlap_z
    geometry_overlap_detected = (
        overlap_x > CONTACT_AABB_OVERLAP_AXIS_TOLERANCE_M
        and overlap_y > CONTACT_AABB_OVERLAP_AXIS_TOLERANCE_M
        and overlap_z > CONTACT_AABB_OVERLAP_AXIS_TOLERANCE_M
    )
    return {
        "bounds_available": True,
        "overlap_x_m": round(overlap_x, 6),
        "overlap_y_m": round(overlap_y, 6),
        "overlap_z_m": round(overlap_z, 6),
        "overlap_volume_m3": round(overlap_volume, 6),
        "geometry_overlap_detected": geometry_overlap_detected,
    }
