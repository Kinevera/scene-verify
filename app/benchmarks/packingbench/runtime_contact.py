"""Shared PackingBench runtime contact and geometry-overlap helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

CONTACT_AABB_OVERLAP_AXIS_TOLERANCE_M = 0.001


def split_filter_prim_paths_by_contact_geometry(
    *,
    filter_prim_paths: Sequence[str],
    bounds_by_prim_path: Mapping[str, Sequence[float] | None],
    mass_by_prim_path: Mapping[str, float | None],
    skippable_zero_mass_empty_prim_names_or_paths: Sequence[str] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    Split contact-filter prims into geometry-backed filters and empty helpers.

    Missing bounds remain fail-closed unless the prim is a zero-mass rigid body
    and its full path or basename is present in the explicit skip allowlist.
    Isaac's MJCF import can emit reviewed zero-mass articulation helper bodies
    with no geometry; those should not poison item-vs-robot clearance checks
    that already include the geometry-bearing neighboring links.
    """
    included_paths: list[str] = []
    skipped_zero_mass_empty_paths: list[str] = []
    skippable_identifiers = {
        identifier.strip()
        for identifier in (skippable_zero_mass_empty_prim_names_or_paths or ())
        if identifier and identifier.strip()
    }

    for prim_path in filter_prim_paths:
        has_bounds = (
            _normalize_bounds_xyz(bounds_by_prim_path.get(prim_path)) is not None
        )
        mass = mass_by_prim_path.get(prim_path)
        is_zero_mass = mass is not None and abs(float(mass)) <= 1e-12
        prim_basename = prim_path.rstrip("/").rsplit("/", 1)[-1]
        is_explicitly_skippable = (
            prim_path in skippable_identifiers or prim_basename in skippable_identifiers
        )
        if has_bounds or not (is_zero_mass and is_explicitly_skippable):
            included_paths.append(prim_path)
        else:
            skipped_zero_mass_empty_paths.append(prim_path)

    return tuple(included_paths), tuple(skipped_zero_mass_empty_paths)


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


def build_contact_group_diagnostics(
    *,
    monitored_prim_paths: Sequence[str],
    filter_prim_paths: Sequence[str],
    contact_records_by_pair: Mapping[tuple[str, str], Mapping[str, object]] | None,
    bounds_by_prim_path: Mapping[str, Sequence[float] | None],
    aabb_filter_prim_paths: Sequence[str] | None = None,
) -> dict[str, object]:
    """Summarize contact-buffer and AABB-overlap evidence for one monitored group."""
    missing_monitored_prim_paths = len(monitored_prim_paths) == 0
    missing_filter_prim_paths = len(filter_prim_paths) == 0
    aabb_filter_set = (
        set(filter_prim_paths)
        if aabb_filter_prim_paths is None
        else set(aabb_filter_prim_paths)
    )
    pair_summaries: list[dict[str, object]] = []
    contacting_filter_prim_paths: set[str] = set()
    aabb_overlapping_filter_prim_paths: set[str] = set()
    missing_contact_data = False
    missing_geometry_bounds = False
    contact_detected = False
    geometry_overlap_detected = False

    for monitored_prim_path in monitored_prim_paths:
        monitored_bounds = bounds_by_prim_path.get(monitored_prim_path)
        if monitored_bounds is None:
            missing_geometry_bounds = True
        for filter_prim_path in filter_prim_paths:
            filter_bounds = bounds_by_prim_path.get(filter_prim_path)
            if filter_bounds is None:
                missing_geometry_bounds = True

            contact_record = None
            if contact_records_by_pair is not None:
                contact_record = contact_records_by_pair.get(
                    (monitored_prim_path, filter_prim_path)
                )
            if contact_record is None:
                missing_contact_data = True

            overlap = (
                aabb_overlap_xyz(monitored_bounds, filter_bounds)
                if filter_prim_path in aabb_filter_set
                else {
                    "bounds_available": monitored_bounds is not None
                    and filter_bounds is not None,
                    "overlap_x_m": 0.0,
                    "overlap_y_m": 0.0,
                    "overlap_z_m": 0.0,
                    "overlap_volume_m3": 0.0,
                    "geometry_overlap_detected": False,
                }
            )
            pair_summary = {
                "monitored_prim_path": monitored_prim_path,
                "filter_prim_path": filter_prim_path,
                "contact_count": (
                    int(contact_record["contact_count"])
                    if contact_record is not None
                    and contact_record.get("contact_count") is not None
                    else None
                ),
                "min_contact_distance_m": (
                    round(float(contact_record["min_contact_distance_m"]), 6)
                    if contact_record is not None
                    and contact_record.get("min_contact_distance_m") is not None
                    else None
                ),
                "max_abs_normal_force": (
                    round(float(contact_record["max_abs_normal_force"]), 6)
                    if contact_record is not None
                    and contact_record.get("max_abs_normal_force") is not None
                    else None
                ),
                **overlap,
            }
            pair_summaries.append(pair_summary)

            if (
                pair_summary["contact_count"] is not None
                and pair_summary["contact_count"] > 0
            ):
                contact_detected = True
                contacting_filter_prim_paths.add(filter_prim_path)
            if overlap["geometry_overlap_detected"]:
                geometry_overlap_detected = True
                aabb_overlapping_filter_prim_paths.add(filter_prim_path)

    check_passed = not any(
        (
            missing_monitored_prim_paths,
            missing_filter_prim_paths,
            missing_geometry_bounds,
            contact_detected,
            geometry_overlap_detected,
        )
    )
    return {
        "check_passed": check_passed,
        "missing_monitored_prim_paths": missing_monitored_prim_paths,
        "missing_filter_prim_paths": missing_filter_prim_paths,
        "missing_contact_data": missing_contact_data,
        "missing_geometry_bounds": missing_geometry_bounds,
        "contact_detected": contact_detected,
        "geometry_overlap_detected": geometry_overlap_detected,
        "monitored_prim_paths": list(monitored_prim_paths),
        "filter_prim_paths": list(filter_prim_paths),
        "contacting_filter_prim_paths": sorted(contacting_filter_prim_paths),
        "aabb_overlapping_filter_prim_paths": sorted(
            aabb_overlapping_filter_prim_paths
        ),
        "pair_summaries": pair_summaries,
    }
