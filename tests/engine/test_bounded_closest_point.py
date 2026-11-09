"""The signed-distance query behind the mesh-agreement and penetration checks answers exactly as
trimesh's all-pairs ``closest_point_naive`` does, in memory bounded independently of mesh size.

The all-pairs query allocates points x triangles: 2,000 samples on a multi-million-face
reconstruction asked for hundreds of GB and froze a 125 GB host with no swap (2026-11-09).
"""

from __future__ import annotations

import time
import tracemalloc

import numpy as np
import pytest
import trimesh

from scene_verify import geometry as geom


def _query_points(mesh: trimesh.Trimesh, seed: int) -> np.ndarray:
    """Points around, on, and at the vertices of ``mesh``: inside, outside, and exact ties."""
    rng = np.random.default_rng(seed)
    lo, hi = mesh.bounds
    pad = 0.5 * (hi - lo)
    around = rng.uniform(lo - pad, hi + pad, size=(400, 3))
    on_surface, _ = trimesh.sample.sample_surface(mesh, 200, seed=seed)
    return np.vstack([around, on_surface, mesh.vertices[:60]])


@pytest.mark.parametrize(
    "mesh",
    [
        trimesh.creation.box(extents=(1.0, 2.0, 0.5)),
        trimesh.creation.icosphere(subdivisions=3),
        trimesh.creation.annulus(r_min=0.3, r_max=1.0, height=0.4),
        trimesh.creation.capsule(height=1.0, radius=0.3),
        # Mixed triangle sizes: a large box hull beside a dense small sphere.
        trimesh.util.concatenate(
            [
                trimesh.creation.box(extents=(3.0, 3.0, 0.2)),
                trimesh.creation.icosphere(subdivisions=4, radius=0.2),
            ]
        ),
    ],
    ids=["box", "icosphere", "annulus", "capsule", "mixed_sizes"],
)
def test_closest_point_matches_the_all_pairs_query(mesh: trimesh.Trimesh) -> None:
    points = _query_points(mesh, seed=7)
    naive_close, naive_dist, naive_tid = trimesh.proximity.closest_point_naive(mesh, points)
    close, dist, tid = geom._closest_point_bounded(mesh, points)
    np.testing.assert_allclose(dist, naive_dist, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(close, naive_close, rtol=0.0, atol=1e-12)
    # Same triangle, ties included (lowest index wins), so the sign's face normal is the same.
    np.testing.assert_array_equal(tid, naive_tid)


def test_signed_distance_sign_is_unchanged() -> None:
    mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    points = np.array([[0.0, 0.0, 0.0], [0.2, -0.1, 0.3], [0.9, 0.0, 0.0], [0.0, 0.0, -2.0]])
    signed = geom._signed_distance_inside_positive(mesh, points)
    np.testing.assert_allclose(signed, [0.5, 0.2, -0.4, -1.5], atol=1e-12)


def test_large_mesh_query_runs_in_bounded_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("the all-pairs query allocates points x triangles")

    # Fail fast rather than exhaust the host if the all-pairs query comes back.
    monkeypatch.setattr(trimesh.proximity, "closest_point_naive", refuse)
    mesh = trimesh.creation.icosphere(subdivisions=8)  # 1,310,720 faces
    assert len(mesh.faces) > 1_000_000
    _ = mesh.triangles, mesh.face_normals  # cached mesh data, not the query's cost
    points, _ = trimesh.sample.sample_surface(mesh, 2000, seed=0)
    points = points * 1.01  # 1 cm outside the unit sphere

    tracemalloc.start()
    try:
        started = time.monotonic()
        signed = geom._signed_distance_inside_positive(mesh, points)
        elapsed = time.monotonic() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # The all-pairs query would need about 2,000 x 1.3M x 66 bytes, some 170 GB.
    assert peak < 1_000_000_000, f"peak {peak / 1e6:.0f} MB"
    assert elapsed < 30.0, f"took {elapsed:.1f} s"
    np.testing.assert_allclose(signed, -0.01, atol=1e-4)
