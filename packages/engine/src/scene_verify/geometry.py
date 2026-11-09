"""Geometry helpers for the scene verifier.

Two responsibilities:

* :func:`usd_subtree_to_trimesh` / :func:`world_aabb_bounds_by_prim_path` extract world-
  space geometry from an open USD stage (needs ``pxr``; imported lazily so the rest of
  this module stays importable for unit tests).
* :func:`directional_mesh_divergence` computes the one genuinely-new geometric check —
  **directional/signed** visual-vs-collision divergence. It takes ``trimesh`` meshes and
  uses only ``trimesh``/``numpy``, so it is exercised in the plain venv against synthetic
  ``trimesh.creation.box`` meshes.

Why directional and never symmetric Chamfer: collision meshes are legitimately
simplified (convex hulls, decimated shells), so a symmetric distance false-positives on
essentially every scene. We instead measure two signed depths independently:

* ``phantom`` — collision surface points lying *outside* the visual mesh
  (collision larger than visual -> phantom contacts).
* ``clip``    — visual surface points lying *outside* the collision mesh
  (collision smaller than visual -> clip-through / missing collision parts).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import trimesh

#: Fixed seed for surface sampling. Both the divergence and penetration checks estimate a
#: statistic (max protrusion / max penetration depth) from a finite random surface sample.
#: With an unseeded RNG the same scene yields slightly different numbers each run, which makes
#: a value sitting near a gate threshold flap warn<->fail between runs (observed on book_brick:
#: phantom_max 0.0138-0.0154 across runs of identical geometry, straddling the 0.015 fail line).
#: A fixed seed makes the verdict reproducible — same scene, same numbers, same verdict — WITHOUT
#: changing what is measured or any threshold. trimesh.sample.sample_surface takes ``seed`` in
#: both the venv (4.12) and Isaac (4.5) trimesh, and does not perturb numpy's global RNG.
MESH_SAMPLE_SEED = 0


def _sample_surface(mesh: trimesh.Trimesh, n_samples: int) -> np.ndarray:
    """Deterministic area-weighted surface samples (seeded; portable across trimesh 4.5/4.12)."""
    points, _ = trimesh.sample.sample_surface(mesh, n_samples, seed=MESH_SAMPLE_SEED)
    return np.asarray(points)


# ---------------------------------------------------------------------------
# USD extraction (pxr imported lazily)
# ---------------------------------------------------------------------------


def world_aabb_bounds_by_prim_path(
    stage: Any,
    prim_paths: Sequence[str],
) -> dict[str, list[float] | None]:
    """World-space AABBs as ``[min_x, min_y, min_z, max_x, max_y, max_z]`` per prim.

    Self-contained USD ``BBoxCache`` helper so the engine pulls in no host script with
    import-time side effects (Isaac scene validators boot a ``SimulationApp`` at import).
    """
    from pxr import Usd, UsdGeom

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
    )
    bounds_by_prim_path: dict[str, list[float] | None] = {}
    for prim_path in prim_paths:
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            bounds_by_prim_path[prim_path] = None
            continue
        aligned_range = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if hasattr(aligned_range, "IsEmpty") and aligned_range.IsEmpty():
            bounds_by_prim_path[prim_path] = None
            continue
        min_point = aligned_range.GetMin()
        max_point = aligned_range.GetMax()
        bounds_by_prim_path[prim_path] = [
            round(float(min_point[0]), 6),
            round(float(min_point[1]), 6),
            round(float(min_point[2]), 6),
            round(float(max_point[0]), 6),
            round(float(max_point[1]), 6),
            round(float(max_point[2]), 6),
        ]
    return bounds_by_prim_path


def scan_static_tag(stage: Any, prim_path: str) -> bool | None:
    """Whether a static-expected subtree is kinematically anchored ("static tag" present).

    Mirrors how the codebase marks support geometry: a kinematic ``UsdPhysics.RigidBodyAPI``
    (``kinematicEnabled=True``, e.g. the ArtVIP carton base) anchors the object. An
    *articulated* object legitimately mixes a kinematic anchor with dynamic child bodies
    (the carton's live flap joints), so the object is "static" when **any** body is
    kinematic, or when there is no rigid body at all. It is missing its static tag only when
    rigid bodies exist but none is kinematic — exactly what ``inject_missing_static_tag``
    produces by flipping every body to ``kinematicEnabled=False``. Returns ``None`` when the
    prim is absent.

    This is a pure USD scan and never inspects pose deltas, so the decision layer keeps
    ``missing_static_metadata`` disjoint from ``physics_instability``.
    """
    from pxr import Usd, UsdPhysics

    root = stage.GetPrimAtPath(prim_path)
    if not root or not root.IsValid():
        return None
    rigid_bodies = [prim for prim in Usd.PrimRange(root) if prim.HasAPI(UsdPhysics.RigidBodyAPI)]
    if not rigid_bodies:
        return True  # no dynamics authored => static collider
    for prim in rigid_bodies:
        attr = UsdPhysics.RigidBodyAPI(prim).GetKinematicEnabledAttr()
        if attr and attr.HasAuthoredValue() and attr.Get() is True:
            return True  # at least one kinematic anchor => object is anchored
    return False  # rigid bodies present but none anchored => missing static tag


def _mesh_prim_to_trimesh(prim: Any) -> trimesh.Trimesh | None:
    """Bake a single ``UsdGeom.Mesh`` prim into a world-space ``trimesh.Trimesh``."""
    from pxr import Usd, UsdGeom

    mesh = UsdGeom.Mesh(prim)
    points = mesh.GetPointsAttr().Get()
    counts = mesh.GetFaceVertexCountsAttr().Get()
    indices = mesh.GetFaceVertexIndicesAttr().Get()
    if not points or not counts or not indices:
        return None

    local = np.asarray([[p[0], p[1], p[2]] for p in points], dtype=float)
    # USD uses row-vector * matrix; the translation lives in the last row.
    matrix = np.asarray(
        UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()),
        dtype=float,
    ).reshape(4, 4)
    homogeneous = np.hstack([local, np.ones((local.shape[0], 1))])
    world = homogeneous @ matrix
    world = world[:, :3] / world[:, 3:4]

    faces: list[tuple[int, int, int]] = []
    offset = 0
    for count in counts:
        count = int(count)
        for k in range(1, count - 1):
            faces.append(
                (
                    int(indices[offset]),
                    int(indices[offset + k]),
                    int(indices[offset + k + 1]),
                )
            )
        offset += count
    if not faces:
        return None
    tm = trimesh.Trimesh(vertices=world, faces=np.asarray(faces, dtype=np.int64), process=False)
    # Authored winding is untrustworthy (leftHanded orientation, inward-wound exports,
    # mirroring transforms), and the signed-distance core decides inside/outside from face
    # normals — inconsistent winding silently swaps phantom<->clip. Normalize to coherent
    # outward winding so the directional labels keep their meaning on closed authored
    # meshes. (Open/non-watertight surfaces have no well-defined interior; there the flip
    # decision — and the directional labels themselves — remain best-effort.)
    try:
        trimesh.repair.fix_normals(tm, multibody=True)
    except Exception:
        pass  # non-orientable input: keep authored winding rather than fail the capture
    return tm


def _concat(parts: list[trimesh.Trimesh]) -> trimesh.Trimesh | None:
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return trimesh.util.concatenate(parts)


def usd_subtree_to_trimesh(stage: Any, prim_path: str) -> trimesh.Trimesh | None:
    """Concatenate all ``UsdGeom.Mesh`` descendants of ``prim_path`` into one world-space mesh.

    Returns ``None`` when no usable mesh geometry is found (routed to the ``labeling``
    bucket by the decision layer). Polygons are fan-triangulated.
    """
    from pxr import Usd, UsdGeom

    root = stage.GetPrimAtPath(prim_path)
    if not root or not root.IsValid():
        return None
    parts = [
        tm
        for prim in Usd.PrimRange(root)
        if prim.IsA(UsdGeom.Mesh)
        for tm in (_mesh_prim_to_trimesh(prim),)
        if tm is not None
    ]
    return _concat(parts)


def _is_dedicated_collision_prim(prim: Any) -> bool:
    """Whether a mesh is a *separately-authored* collider (distinct from the visual): a
    ``guide`` purpose or a collision/collider/convex path. A renderable mesh that merely
    *also* carries ``CollisionAPI`` (the common convex-approx case) is NOT dedicated — it is
    the visual whose collider is a runtime approximation, handled by proxy synthesis."""
    from pxr import UsdGeom

    name = str(prim.GetPath()).lower()
    try:
        purpose = UsdGeom.Imageable(prim).ComputePurpose()
    except Exception:  # pragma: no cover - purpose optional
        purpose = None
    return purpose == UsdGeom.Tokens.guide or any(
        tag in name for tag in ("collision", "collider", "convex")
    )


def collision_mesh_prim_paths(stage: Any, object_prim_path: str) -> list[str]:
    """Paths of *separately-authored* collision ``UsdGeom.Mesh`` prims under an object.

    Used by the soundness harness to scale the collision geometry only. Empty when the asset
    has no dedicated collision mesh (its collider is a runtime approximation of the visual).
    """
    from pxr import Usd, UsdGeom

    root = stage.GetPrimAtPath(object_prim_path)
    if not root or not root.IsValid():
        return []
    return [
        str(prim.GetPath())
        for prim in Usd.PrimRange(root)
        if prim.IsA(UsdGeom.Mesh) and _is_dedicated_collision_prim(prim)
    ]


def _read_mesh_approximation(prim: Any) -> str | None:
    from pxr import UsdPhysics

    if not prim.HasAPI(UsdPhysics.MeshCollisionAPI):
        return None
    attr = UsdPhysics.MeshCollisionAPI(prim).GetApproximationAttr()
    return str(attr.Get()) if attr and attr.HasAuthoredValue() else None


def _collision_proxy(
    mesh: trimesh.Trimesh, approximation: str | None
) -> tuple[trimesh.Trimesh, bool]:
    """The collider geometry PhysX uses for ``mesh`` under ``approximation``.

    Returns ``(proxy, synthesized)``. ``synthesized`` is True for a convex over-
    approximation (hull/box/sphere) whose interior divergence from the visual must be
    sampled, not bounding-box-compared. High-fidelity modes (sdf / convexDecomposition /
    triangle mesh) return the mesh itself — the collider tracks the visual.
    """
    approx = (approximation or "").lower()
    if approx == "convexhull":
        try:
            return mesh.convex_hull, True
        except Exception:  # pragma: no cover - no convex-hull backend (scipy)
            return mesh, False
    if approx == "boundingcube":
        lo, hi = mesh.bounds
        box = trimesh.creation.box(extents=(hi - lo))
        box.apply_translation((lo + hi) / 2.0)
        return box, True
    if approx == "boundingsphere":
        center = mesh.bounds.mean(axis=0)
        radius = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0]) / 2.0)
        sphere = trimesh.creation.icosphere(subdivisions=2, radius=radius)
        sphere.apply_translation(center)
        return sphere, True
    return mesh, False


def _world_orientation_inverse(prim: Any) -> np.ndarray | None:
    """Pure inverse-rotation (trimesh column-convention 4x4) that removes ``prim``'s world
    ORIENTATION while preserving world scale and translation.

    Used to canonicalise an object's visual-vs-collision divergence. The divergence is intrinsic
    to the asset — it must not depend on how the scene places or *settles* the object. In world
    space the synthesized convex-hull proxy depended on the object's orientation (qhull
    re-triangulates rotated vertices, shifting the sampled max), flapping a boundary asset's
    verdict between rows. Removing only the orientation (not scale) fixes that: the proxy is built
    on consistently-oriented vertices every scene, so the divergence is pose-invariant — while the
    magnitude stays in physical world units (canonicalising into the prim's full *local* frame
    would instead report authored, pre-scale sizes, ~30x off for a scaled asset).

    The orientation is the nearest rotation to the transform's linear part (SVD/polar
    decomposition, dropping scale and shear). Returns ``None`` for a degenerate transform.
    """
    from pxr import Usd, UsdGeom

    matrix = np.asarray(
        UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()),
        dtype=float,
    ).reshape(4, 4)
    # USD row-vector convention (p_row @ M); trimesh column is M.T. Its 3x3 linear block is
    # rotation*scale*shear; take the nearest orthonormal rotation R and apply R^-1 = R.T.
    linear = (matrix.T)[:3, :3]
    try:
        u, _s, vt = np.linalg.svd(linear)
    except np.linalg.LinAlgError:  # pragma: no cover - degenerate transform
        return None
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:  # guard against a reflection
        u = u.copy()
        u[:, -1] *= -1
        rotation = u @ vt
    transform = np.eye(4)
    transform[:3, :3] = rotation.T  # world orientation -> canonical, scale untouched
    return transform


def _assemble_visual_collision(
    stage: Any, object_prim_path: str, *, frame: str = "world"
) -> tuple[trimesh.Trimesh | None, trimesh.Trimesh | None, bool]:
    """Build (visual, collision, needs_sampling) from an object's mesh prims.

    A dedicated collision prim contributes directly. A renderable mesh contributes its
    geometry to the visual and, when it carries ``CollisionAPI``, its approximation-derived
    proxy to the collision — so the check works on convex-approx assets with no separate
    collision mesh. ``needs_sampling`` is True when the collision geometry can diverge from
    the visual *inside* a shared bounding box — i.e. when any proxy is a convex
    over-approximation OR any collision mesh is separately authored (an authored convex hull
    of a concave visual shares its AABB exactly; only sampling can see the bulge).

    ``frame``: ``"world"`` (default) bakes each mesh's full world transform — required for the
    cross-object interpenetration check, where objects must share a frame. ``"local"`` removes the
    object's world orientation (taken from the first mesh prim and reused for all parts, preserving
    relative offsets and physical scale), making the per-object visual-vs-collision divergence
    pose-invariant — the convex-hull proxy is then built on consistently-oriented vertices
    regardless of how the body placed/settled. The proxy is synthesised *after* canonicalisation so
    the hull itself is canonical.
    """
    from pxr import Usd, UsdGeom, UsdPhysics

    root = stage.GetPrimAtPath(object_prim_path)
    if not root or not root.IsValid():
        return None, None, False

    # The canonicalising inverse-rotation is taken from the first mesh prim and reused for all
    # parts, so every mesh is de-rotated consistently and relative offsets (and scale) are kept.
    to_local: np.ndarray | None = None
    canonicalise = frame == "local"

    visual_parts: list[trimesh.Trimesh] = []
    collision_parts: list[trimesh.Trimesh] = []
    needs_sampling = False
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        tm = _mesh_prim_to_trimesh(prim)
        if tm is None:
            continue
        if canonicalise:
            if to_local is None:
                to_local = _world_orientation_inverse(prim)  # ref = first mesh prim's orientation
            if to_local is not None:
                tm.apply_transform(to_local)  # remove world orientation (scale preserved)
        if _is_dedicated_collision_prim(prim):
            collision_parts.append(tm)
            needs_sampling = True  # authored collider: interior divergence invisible to AABBs
            continue
        visual_parts.append(tm)
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            proxy, proxy_synth = _collision_proxy(tm, _read_mesh_approximation(prim))
            collision_parts.append(proxy)
            needs_sampling = needs_sampling or proxy_synth

    return _concat(visual_parts), _concat(collision_parts), needs_sampling


def object_mesh_divergence(
    stage: Any,
    object_prim_path: str,
    *,
    n_samples: int = 2000,
    bvh_skip_margin_m: float = 0.003,
) -> dict[str, Any]:
    """Assemble visual + (proxy) collision then run the directional divergence.

    Computes in the asset's **local** frame (canonicalised to the first mesh prim's own world
    transform) so the divergence is pose-invariant — intrinsic to the asset, independent of its
    scene placement or settled orientation. The cross-object interpenetration check stays in world
    frame.
    """
    visual, collision, needs_sampling = _assemble_visual_collision(
        stage, object_prim_path, frame="local"
    )
    return directional_mesh_divergence(
        visual,
        collision,
        n_samples=n_samples,
        bvh_skip_margin_m=bvh_skip_margin_m,
        force_sample=needs_sampling,
    )


# ---------------------------------------------------------------------------
# Pairwise interpenetration (mesh/contact depth, not raw AABB overlap)
# ---------------------------------------------------------------------------


def mesh_pair_penetration_depth_m(
    mesh_a: trimesh.Trimesh | None,
    mesh_b: trimesh.Trimesh | None,
    *,
    n_samples: int = 2000,
) -> float:
    """Max depth (m) by which two meshes' surfaces lie *inside* one another.

    AABB overlap is necessary but not sufficient for real interpenetration — two bounding
    boxes can clip at a corner while the meshes never touch (the false-positive the corpus
    surfaced: a 7 mm³ AABB overlap of two validly-placed items). This samples each surface
    and measures how far it sits inside the other body via the rtree-free signed distance
    (positive inside). Returns ``0.0`` when the meshes do not actually overlap, so the
    decision layer can flag only genuine mesh penetration.

    A ``0.0`` here means "assessed, no overlap" — distinct from "could not assess". If
    sampling/closest-point fails on a non-degenerate mesh the error propagates rather than
    being swallowed as ``0.0``, so the USD wrapper can route the pair to the AABB-volume
    fallback instead of silently passing a pair it never actually evaluated.
    """
    if _degenerate(mesh_a) or _degenerate(mesh_b):
        return 0.0
    # _degenerate() returned False for both, so neither mesh is None (mypy cannot see it).
    a_min, a_max = np.asarray(mesh_a.bounds[0]), np.asarray(mesh_a.bounds[1])  # type: ignore[union-attr]
    b_min, b_max = np.asarray(mesh_b.bounds[0]), np.asarray(mesh_b.bounds[1])  # type: ignore[union-attr]
    if np.any(a_min > b_max) or np.any(b_min > a_max):
        return 0.0  # AABBs disjoint => no contact at all
    a_points = _sample_surface(mesh_a, n_samples)
    b_points = _sample_surface(mesh_b, n_samples)
    a_into_b = np.clip(_signed_distance_inside_positive(mesh_b, a_points), 0.0, None)
    b_into_a = np.clip(_signed_distance_inside_positive(mesh_a, b_points), 0.0, None)
    return float(max(np.max(a_into_b), np.max(b_into_a)))


def pairwise_collision_penetration_depth_m(
    stage: Any,
    object_prim_path_a: str,
    object_prim_path_b: str,
    *,
    n_samples: int = 2000,
) -> float | None:
    """Mesh-level penetration depth (m) between two objects' *collision* geometry.

    Uses the same approximation-derived collision proxies PhysX simulates (so the depth
    reflects what actually collides), then delegates to :func:`mesh_pair_penetration_depth_m`.
    Returns ``None`` when the pair could not be assessed at mesh level — either object has no
    usable collision geometry, or sampling/closest-point failed — so the decision layer falls
    back to the coarse AABB-volume floor rather than treating an un-assessed pair as clear.
    """
    _, collision_a, _ = _assemble_visual_collision(stage, object_prim_path_a)
    _, collision_b, _ = _assemble_visual_collision(stage, object_prim_path_b)
    if _degenerate(collision_a) or _degenerate(collision_b):
        return None
    try:
        return mesh_pair_penetration_depth_m(collision_a, collision_b, n_samples=n_samples)
    except Exception:
        return None  # un-assessable (degenerate sampling) => AABB-volume fallback, not 0.0


# ---------------------------------------------------------------------------
# Directional visual-vs-collision divergence
# ---------------------------------------------------------------------------


def _degenerate(mesh: trimesh.Trimesh | None) -> bool:
    return (
        mesh is None or len(mesh.faces) == 0 or len(mesh.vertices) == 0 or float(mesh.area) <= 0.0
    )


#: Most (point, triangle) pairs one exact closest-point batch evaluates. Each pair costs a few
#: hundred bytes of numpy temporaries, so a batch stays near 100 MB however large the mesh is.
_CLOSEST_POINT_PAIR_BATCH = 200_000

#: Query points sent to the centroid trees at once.
_CLOSEST_POINT_QUERY_CHUNK = 256


def _closest_point_bounded(
    mesh: trimesh.Trimesh, points: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exact closest point on ``mesh`` for each point, in bounded memory.

    Returns ``(closest, distance, triangle_id)`` with the result
    ``trimesh.proximity.closest_point_naive`` gives, ties going to the lowest triangle index as
    its ``argmin`` does, without its points x triangles intermediate (about 66 bytes a pair: a
    2,000-point query on a 2.4M-face mesh asked for over 300 GB). It needs only numpy, scipy and
    trimesh, so it runs where rtree and embree are absent (the dev venv and Isaac Sim's python).

    Triangles are grouped by their radius about their centroid (the farthest vertex), within a
    factor of two, with one ``cKDTree`` of centroids per group. Any triangle's distance bounds
    a point's answer ``d``; every triangle within ``d`` of the point has its centroid within
    ``d + r`` of it, ``r`` its group's largest radius, so a ball query per group returns a
    candidate set holding every closest triangle. Candidates are evaluated exactly in batches
    of at most ``_CLOSEST_POINT_PAIR_BATCH`` pairs.
    """
    from scipy.spatial import cKDTree  # type: ignore[import-untyped]  # scipy ships no stubs

    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    n_points = len(points)
    best_d2 = np.full(n_points, np.inf)
    best_tid = np.full(n_points, np.iinfo(np.int64).max, dtype=np.int64)
    best_close = np.zeros((n_points, 3))
    if n_points == 0:
        return best_close, np.zeros(0), np.zeros(0, dtype=np.int64)

    centroids = triangles.mean(axis=1)
    radius = np.sqrt(
        np.max([((triangles[:, j] - centroids) ** 2).sum(axis=1) for j in range(3)], axis=0)
    )
    positive = radius[radius > 0.0]
    floor = float(positive.min()) if len(positive) else 1.0
    group_key = np.ceil(np.log2(np.maximum(radius, floor) / floor)).astype(np.int64)
    groups: list[tuple[np.ndarray, Any, float]] = []
    for key in np.unique(group_key):
        face_ids = np.flatnonzero(group_key == key)
        groups.append((face_ids, cKDTree(centroids[face_ids]), float(radius[face_ids].max())))

    def evaluate(point_ids: np.ndarray, face_ids: np.ndarray) -> None:
        """Fold exact distances for the given pairs into the running best per point."""
        for start in range(0, len(point_ids), _CLOSEST_POINT_PAIR_BATCH):
            pid = point_ids[start : start + _CLOSEST_POINT_PAIR_BATCH]
            fid = face_ids[start : start + _CLOSEST_POINT_PAIR_BATCH]
            close = trimesh.triangles.closest_point(triangles[fid], points[pid])
            d2 = ((points[pid] - close) ** 2).sum(axis=1)
            # Per point, the smallest squared distance, ties to the lowest triangle index.
            order = np.lexsort((fid, d2, pid))
            pid, fid, d2, close = pid[order], fid[order], d2[order], close[order]
            first = np.ones(len(pid), dtype=bool)
            first[1:] = pid[1:] != pid[:-1]
            pid, fid, d2, close = pid[first], fid[first], d2[first], close[first]
            better = (d2 < best_d2[pid]) | ((d2 == best_d2[pid]) & (fid < best_tid[pid]))
            pid, fid, d2, close = pid[better], fid[better], d2[better], close[better]
            best_d2[pid] = d2
            best_tid[pid] = fid
            best_close[pid] = close

    for start in range(0, n_points, _CLOSEST_POINT_QUERY_CHUNK):
        chunk = np.arange(start, min(start + _CLOSEST_POINT_QUERY_CHUNK, n_points))
        # An upper bound per point: the exact distance to the faces of each group's few nearest
        # centroids (more than one, so a degenerate face whose distance is NaN cannot leave a
        # point without a finite bound).
        seed_pids, seed_fids = [], []
        for face_ids, tree, _ in groups:
            k = min(4, len(face_ids))
            _, nearest = tree.query(points[chunk], k=k)
            nearest = np.asarray(nearest, dtype=np.int64).reshape(len(chunk), k)
            seed_pids.append(np.repeat(chunk, k))
            seed_fids.append(face_ids[nearest.ravel()])
        evaluate(np.concatenate(seed_pids), np.concatenate(seed_fids))
        bound = np.sqrt(best_d2[chunk])
        # Every face that can be at least as close as the bound, group by group.
        for face_ids, tree, group_radius in groups:
            reach = (bound + group_radius) * (1.0 + 1e-9) + 1e-12
            counts = tree.query_ball_point(points[chunk], reach, return_length=True)
            sub_start = 0
            while sub_start < len(chunk):
                # Points whose candidates together fit one batch (at least one point).
                total = np.cumsum(counts[sub_start:])
                sub_end = sub_start + max(1, int(np.searchsorted(total, _CLOSEST_POINT_PAIR_BATCH)))
                sub = chunk[sub_start:sub_end]
                hits = tree.query_ball_point(
                    points[sub], reach[sub_start:sub_end], return_sorted=False
                )
                lengths = np.fromiter((len(h) for h in hits), dtype=np.int64, count=len(hits))
                if lengths.sum():
                    local = np.fromiter(
                        (i for h in hits for i in h), dtype=np.int64, count=int(lengths.sum())
                    )
                    evaluate(np.repeat(sub, lengths), face_ids[local])
                sub_start = sub_end

    return best_close, np.sqrt(best_d2), best_tid


def _signed_distance_inside_positive(mesh: trimesh.Trimesh, points: np.ndarray) -> np.ndarray:
    """Signed distance (positive inside) without rtree/embree.

    ``trimesh.proximity.signed_distance`` relies on a ray engine (rtree) that is absent
    in both the project venv and the Isaac python. We instead find the exact closest point
    (:func:`_closest_point_bounded`, bounded memory) and decide the sign from the nearest face
    normal: a point on the outward side of its closest surface triangle is outside (negative).
    Robust for the convex collision hulls and box-like meshes this check targets; portable
    across both pythons.
    """
    closest, distance, triangle_id = _closest_point_bounded(mesh, points)
    normals = mesh.face_normals[triangle_id]
    outward = np.einsum("ij,ij->i", points - closest, normals) > 0.0
    return np.where(outward, -distance, distance)


def directional_mesh_divergence(
    visual: trimesh.Trimesh | None,
    collision: trimesh.Trimesh | None,
    *,
    n_samples: int = 2000,
    bvh_skip_margin_m: float = 0.003,
    force_sample: bool = False,
) -> dict[str, Any]:
    """Directional signed divergence between a visual and a collision mesh.

    Returns a dict the decision layer thresholds:
    ``{mesh_present, mode, phantom_max_m, phantom_p95_m, clip_max_m, clip_p95_m}``.
    ``mode`` is one of ``missing`` / ``degenerate`` / ``aabb_only`` / ``sampled``.

    ``force_sample`` skips the cheap AABB pre-pass. Required when the collision can diverge
    from the visual *inside* a shared bounding box: a synthesized convex proxy OR a
    separately-authored collision mesh (either can share the visual's AABB while bulging
    across concavities — the divergence is interior, invisible to the bounding-box check).
    """
    if _degenerate(visual) or _degenerate(collision):
        mode = "missing" if (visual is None or collision is None) else "degenerate"
        return {"mesh_present": False, "mode": mode}

    # _degenerate() returned False for both, so neither mesh is None (mypy cannot see it).
    v_min, v_max = np.asarray(visual.bounds[0]), np.asarray(visual.bounds[1])  # type: ignore[union-attr]
    c_min, c_max = np.asarray(collision.bounds[0]), np.asarray(collision.bounds[1])  # type: ignore[union-attr]
    # Cheap pre-pass: how far each box sticks out beyond the other, per axis.
    phantom_gap = float(max(0.0, np.max(np.maximum(v_min - c_min, c_max - v_max))))
    clip_gap = float(max(0.0, np.max(np.maximum(c_min - v_min, v_max - c_max))))
    if not force_sample and phantom_gap <= bvh_skip_margin_m and clip_gap <= bvh_skip_margin_m:
        return {
            "mesh_present": True,
            "mode": "aabb_only",
            "phantom_max_m": round(phantom_gap, 6),
            "phantom_p95_m": round(phantom_gap, 6),
            "clip_max_m": round(clip_gap, 6),
            "clip_p95_m": round(clip_gap, 6),
        }

    try:
        collision_points = _sample_surface(collision, n_samples)
        visual_points = _sample_surface(visual, n_samples)
        # signed distance is positive inside; outside-of-other depth is the divergence.
        phantom_depth = np.clip(
            -_signed_distance_inside_positive(visual, collision_points), 0.0, None
        )
        clip_depth = np.clip(-_signed_distance_inside_positive(collision, visual_points), 0.0, None)
    except Exception as exc:  # pragma: no cover - defensive; degenerate sampling
        return {"mesh_present": False, "mode": "degenerate", "error": str(exc)}

    return {
        "mesh_present": True,
        "mode": "sampled",
        "phantom_max_m": round(float(np.max(phantom_depth)), 6),
        "phantom_p95_m": round(float(np.percentile(phantom_depth, 95)), 6),
        "clip_max_m": round(float(np.max(clip_depth)), 6),
        "clip_p95_m": round(float(np.percentile(clip_depth, 95)), 6),
    }


def reconstruction_mesh_stats(stage: Any, prim_paths: list[str]) -> dict[str, Any]:
    """Measure the surface-density evidence for the reconstruction-fidelity gate.

    Face count and mesh-area/AABB-surface-area ratio over the union of the given subtrees,
    measured from the stage (never trusted from the producer). Both are unit-invariant, so
    no metersPerUnit normalisation applies. Returns ``{"measured": False}`` when no usable
    mesh geometry exists — the gate warns rather than silently passing.
    """
    meshes = [
        mesh
        for path in prim_paths
        for mesh in (usd_subtree_to_trimesh(stage, path),)
        if mesh is not None and len(mesh.faces) > 0
    ]
    combined = _concat(meshes)
    if combined is None:
        return {"measured": False}
    extents = combined.bounds[1] - combined.bounds[0]
    aabb_area = 2.0 * float(
        extents[0] * extents[1] + extents[1] * extents[2] + extents[0] * extents[2]
    )
    mesh_area = float(combined.area)
    return {
        "measured": True,
        "face_count": int(len(combined.faces)),
        "mesh_area": mesh_area,
        "aabb_area": aabb_area,
        "area_ratio": (mesh_area / aabb_area) if aabb_area > 0.0 else 0.0,
    }
