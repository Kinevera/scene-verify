# Changelog

The release notes for each version. Both distributions, `scene-verify-contract` and
`scene-verify`, carry one version, released as an annotated tag `vX.Y.Z` on `main` whose GitHub
release copies the version's entry. A contract change (the verdict shape or the validator's
rules) has a line here and a record in `docs/adr/` (`AGENTS.md`, binding rule 2).

## 0.4.1 (unreleased)

- **Engine:** the signed distance behind `visual_collision_agreement` and the mesh-level
  penetration depth finds each point's closest triangle through per-size-class `cKDTree`s of
  triangle centroids, evaluating candidates in fixed-size batches, instead of trimesh's
  all-pairs `closest_point_naive`. The all-pairs query allocated points x triangles (about
  66 bytes a pair): 2,000 samples on a multi-million-face reconstruction asked for hundreds of
  GB and froze a 125 GB host. The new query needs only numpy, scipy and trimesh (no rtree or
  embree) and returns the same closest point, distance and triangle, ties included, so every
  measured value and verdict is unchanged. No contract change; the engine pins
  `scene-verify-contract==0.4.1`.

## 0.4.0

- **Contract:** `usd_sha256` is required in every `scene_verify/1` verdict: 64 lowercase hex
  characters, the SHA-256 of the exact USD file bytes the verifier opened. `parse_verdict`
  refuses a verdict without it, and `Verdict.usd_sha256` is a `str`. The schema stays
  `scene_verify/1`; every 0.3.0 reader accepts every 0.4.0 verdict (scene-verify-0001,
  amendment of 2026-11-08).
- **Engine:** the runner hashes the USD file before it opens the stage and refuses to write a
  verdict when the bytes differ after grading. `SceneVerifyReport.to_verdict_json()` and
  `dump_report` raise `ValueError` for a report without `usd_sha256`. The engine pins
  `scene-verify-contract==0.4.0`.
- **Install:** `README.md` installs both distributions from git by tag with a subdirectory,
  with no credential once the repository is public.

## 0.3.0

- The first version: the `scene_verify/1` contract with `parse_verdict`, and the engine with
  the generic runner `scene_verify.runners.usd_bundle`, moved from RoboEval
  (scene-verify-0001). `usd_sha256` is optional.
