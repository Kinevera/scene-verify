# PackingBench Scene Verifier — MVP floor + Phase-0 results

A scene-level geometry/physics **verifier** that scores whether a scene is geometrically
faithful, physically sane, and fair to evaluate a policy on — orthogonal to the PCS
scoring path. It emits a three-state (`pass`/`warn`/`fail`) verdict with single-root-cause
bucket attribution, and is designed so a future thin SceneForge QA gate can consume the
verdict to block `approve`.

The verifier **engine is standalone and embodiment-agnostic** (`app/scene_verify/`): scene
evidence in, generic `scene_verify/1` verdict out, with no PackingBench/SceneForge identity.
PackingBench is its *first consumer* (a thin adapter + the Isaac runner); a SceneForge QA
gate will be a *second consumer*. Scoring (`app/task_definitions/packingbench.py`) and the
frozen `scene_validation.py` six-check contract are **untouched** — verified with `git diff`.

## Components (all additive)

| File | Role |
|---|---|
| `app/scene_verify/core.py` | **Engine** — Isaac-free decision layer: gates, thresholds, bucket attribution, `scene_verify/1` verdict. No benchmark imports. |
| `app/scene_verify/geometry.py` | **Engine** — USD→trimesh extraction, **directional** visual-vs-collision divergence, static-tag scan |
| `app/scene_verify/defects.py` | **Engine** — defect injectors for the soundness harness |
| `app/scene_verify/thresholds.yaml` | **Engine** — all tunables (single source of truth; mirrors validator constants) |
| `app/benchmarks/packingbench/scene_verify_packingbench.py` | **PackingBench adapter** — projects a verdict onto the legacy six-check summary; writes `validation_summary.json` |
| `scripts/tools/verify_scene_bundle.py` | **PackingBench consumer** — Isaac runner using the shared faithful builder (robot included; see finding 2): builds a real scene, settles, captures evidence, calls the engine |
| `scripts/tools/run_scene_verify_soundness.py` | **PackingBench consumer** — live Isaac soundness gate (clean + injected defects → discrimination matrix) |
| `tests/scene_verify/test_scene_verify_soundness.py` | Engine venv suite (no Isaac) |
| `tests/benchmarks/test_scene_verify_packingbench.py` | Adapter venv suite incl. the projection-completeness property (a verdict failing ANY single gate must project to a failing legacy summary; `visual_collision_agreement` folds into `tracked_object_state` — regression: pack_2_close_i2 once projected verdict-fail to legacy-pass) |

## Gates and buckets

| Gate | Bucket | Fails when |
|---|---|---|
| `scene_load` | load | scene/objects did not load |
| `visual_collision_agreement` | mesh_disagreement / labeling | collision protrudes beyond visual (phantom) or visual beyond collision (clip); missing collision mesh → labeling warn |
| `interpenetration` | interpenetration | two dynamic objects' collision proxies actually penetrate (mesh-level depth > tolerance; AABB overlap is only a cheap pre-pass) |
| `static_settle` | physics_instability | a **dynamic** object drifts past linear/angular tolerance |
| `fall_through` | fall_through | a **dynamic** object's settled bottom sinks below the support plane |
| `static_metadata_present` | missing_static_metadata | a **static-expected** object is not kinematically anchored |

`static_settle`/`fall_through` consider only dynamic objects and `static_metadata_present`
only the USD tag scan, so physics-instability and missing-static-metadata are structurally
disjoint — one root cause is never double-counted.

The mesh check uses **directional/signed** depth, never symmetric Chamfer (collision hulls
are legitimately simplified; Chamfer false-positives every scene). rtree/embree are absent
in both the venv and Isaac python, so signed distance is computed via
`closest_point_naive` + nearest-face-normal sign (portable across both pythons).

## Soundness (credibility gate) — venv suite GREEN

`tests/scene_verify/test_scene_verify_soundness.py` — all green (count grows with the engine). It proves the verifier
discriminates each defect class on authored geometry and that the buckets stay disjoint:

| injected defect | flips gate | bucket |
|---|---|---|
| oversize collision hull (×1.5) | visual_collision_agreement (phantom) | mesh_disagreement |
| undersize collision hull (×0.6) | visual_collision_agreement (clip) | mesh_disagreement |
| missing static tag | static_metadata_present | missing_static_metadata |
| interpenetration | interpenetration | interpenetration |
| fall-through (collider removed) | fall_through | fall_through |

Crux test: a static object mistagged **and** drifting 10 cm/45° trips
`missing_static_metadata` only — never `physics_instability`.

## Live Phase-0 verdict — `pack_1_i2` (Isaac Sim 5.1, A5000)

Run: `/opt/isaac-sim/python.sh scripts/tools/verify_scene_bundle.py --instance-id pack_1_i2
--storage-root <work-dir>/backend/storage`. Verdict in
`artifacts/scene_verify/pack_1_i2/`.

Final verdict after the build-fidelity and mesh-proxy fixes — **overall = pass**:

| gate | status | finding |
|---|---|---|
| scene_load | pass | 2 objects (target_carton, pump_bottle) |
| visual_collision_agreement | **pass** | colliders assessed via approximation-derived proxies: pump_bottle `sdf`→agree (aabb_only), target_carton `convexHull`/`convexDecomposition`→sampled, phantom 1.5 mm (within tol) |
| interpenetration | pass | (graded dynamic-dynamic only; 0 such pairs) |
| static_settle | **pass** | pump_bottle settled_displacement 2.5 mm (faithful build keeps it seated) |
| fall_through | **pass** | item rests on the real table; no fall below the support plane |
| static_metadata_present | pass | articulated carton (kinematic base + live flaps) read as anchored |

### Findings (honest), and how each was resolved

1. **Articulated-carton static-tag false-positive** (live-surfaced) → fixed: anchored when
   **any** body is kinematic (regression test `test_scan_static_tag_articulated_carton`).
2. **Build fidelity** (the big one): the original robot-free build was unfaithful — without
   the robot articulation + fixed-base joint the table collision didn't hold, so the
   rigid-lock pump_bottle fell through (`static_settle`/`fall_through` fail, 0.26 m topple).
   Diagnosed against ground truth (full validator keeps it at 0.66 mm, PASS) and fixed by the
   **shared faithful builder** (`host_scene_runtime.build_packingbench_scene`) used by both the
   verifier and the validator; validator parity is byte-identical.
3. **Convex-approx mesh agreement**: these ArtVIP assets have no separate collision mesh —
   the collider is a runtime approximation (`sdf` / `convexHull` / `convexDecomposition`) on
   the visual mesh. Instead of punting to a labeling warn, the check now **synthesizes the
   collider proxy** per approximation (convex hull / bounding box, or the mesh itself for
   high-fidelity modes) and compares visual-vs-proxy. Result: a real agreement assessment
   (pass here, 1.5 mm), and it still catches a genuinely over-approximating collider (venv
   test `test_collision_proxy_convexhull_detects_overapproximation`: non-convex hull → fail).

## Known limitations / next steps

- **Live soundness gate** (`run_scene_verify_soundness.py`): now a **subprocess-per-case**
  orchestrator (`verify_scene_bundle.py --inject <defect>`, one fresh Isaac process per case —
  Isaac hard-aborts on a 2nd scene build in one process). Run it on a **clean-passing** ≥2-dynamic
  row (e.g. `pack_3_dense_close_i1`). The live gate asserts what a settled scene can prove
  reliably — clean baseline green + the crux that a labeling defect never masquerades as physics
  (`missing_static_tag` flips only `static_metadata_present`, not `static_settle`, even though the
  untagged object is now dynamic). Per-defect "exactly-one-gate" discrimination stays the
  controlled **venv suite's** job: on a real settled scene a physics defect cascades into
  `static_settle` (an injected overlap explodes apart on settle; a removed collider both falls
  through *and* drifts), and translate-then-settle injection cannot show interpenetration
  sensitivity post-settle. The matrix reports `all_discriminated`/`sensitivity_ok` for
  transparency but they are not the live bar.
- **Mesh-disagreement corpus**: needs assets with authored collision meshes; the SceneForge
  approved-bundle corpus (staged track) is the natural source.
- **SceneForge thin QA gate** (staged): add a `scene_verify` gate to `QaGateName` +
  `_build_qa_checks` that reads the `scene_verify/1` verdict and blocks `approve` on fail.
- **Corpus measurement** (staged): verifier pass/warn/fail rates + caught examples across the
  corpus; oracle raw-vs-verified PCS delta on physics/collision defects.
