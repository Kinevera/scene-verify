# Scene Verifier — end-to-end (every scene auto-verified)

This document ties together the full scene-verification layer: the engine, the two Isaac
runners (PackingBench-bound and generic), the task-level Benchmark Verify, and the SceneForge
approval gate that consumes the verdict. The design goal is that **every approved scene is
geometry/physics-verified, not only PackingBench scenes** — achieved by an embodiment-agnostic
engine plus a generic USD-bundle runner, with SceneForge fail-closed when no verdict exists.

## Components

| Component | Repo | Level | Entry |
|---|---|---|---|
| Engine (Isaac-free decision layer) | PackingBench `app/scene_verify/` | scene | `evaluate_scene_verify()` |
| PackingBench runner | PackingBench | scene | `scripts/tools/verify_scene_bundle.py` (`--instance-id`) |
| **Generic USD runner** | PackingBench | scene | `scripts/tools/verify_usd_bundle.py` (`--bundle`) |
| Soundness gate | PackingBench | scene | `scripts/tools/run_scene_verify_soundness.py` |
| Corpus measurement | PackingBench | scene | `scripts/tools/run_scene_verify_corpus.py` |
| **Benchmark Verify** (task validity) | PackingBench | task | `scripts/tools/run_benchmark_verify.py` |
| **SceneForge Verify gate** | SceneForge | scene | `_build_scene_verify_check` (QA gate `scene_verify`) |

The engine has **no benchmark identity**. A scene is described to it as evidence
(`CapturedSceneEvidence`); any producer can build that evidence. Two producers exist today:
the PackingBench manifest runner and the generic bundle runner. Both call the **same**
`capture_scene_evidence()` so there is one capture implementation and no scoring drift.

## The `scene_verify/1` verdict (the cross-repo contract)

```json
{
  "schema_version": "scene_verify/1",
  "scene_id": "...",
  "overall_status": "pass | warn | fail",
  "verified_at": "<iso8601>",
  "verifier_version": "0.1.0",
  "gates": [ {"gate": "...", "status": "pass|warn|fail", "score": 0.0, "bucket": "...", "detail": {}} ],
  "bucket_attribution": {}
}
```

`overall_status` = fail if any gate fails, else warn if any warns, else pass. The SceneForge
gate reads only `schema_version` (prefix `scene_verify/`), `overall_status`, and
`gates[].{gate,status}`. Both sides are locked to this contract by tests:
`tests/scene_verify/test_verdict_contract.py` (producer) and the SceneForge
`test_scene_verify_real_engine_*` / `test_scene_verify_real_external_scene_*` tests (consumer,
fed the engine's real `verdict_pass.json` / `verdict_fail.json` and the externally-authored
`external_real_{valid_pass,defect_fail}.json` verdicts).

## End-to-end flow (how a non-PackingBench scene gets verified and gates approval)

1. **Author a bundle** — describe the USD declaratively (see `app/scene_verify/bundle.py`):
   ```json
   {
     "scene_id": "my_scene",
     "usd_stage_path": "scenes/my_scene/scene.usd",
     "support_prim_path": "/World/table",
     "objects": [
       {"object_id": "carton", "prim_path": "/World/carton", "is_static_expected": true},
       {"object_id": "widget", "prim_path": "/World/widget"}
     ]
   }
   ```
2. **Verify in Isaac** — the generic runner opens the USD, makes declared free objects dynamic
   rigid bodies, runs the passive settle, captures evidence, scores it, and writes a sidecar
   beside the USD:
   ```
   /opt/isaac-sim/python.sh scripts/tools/verify_usd_bundle.py \
       --bundle my_scene_bundle.json --emit-sidecar
   # writes  <usd_dir>/scene_verify.json   (== verdict.json)
   ```
   It never fakes a gate: declared free objects are genuinely settled, and the support/ground
   is read as authored — a table with no collider trips `fall_through` rather than being floored.
   The runner is hardened against producer-controlled softening: the bundle may RAISE
   `settle_steps` but never lower it below the thresholds floor (a `settle_steps: 0` bundle
   would neutralize the physics gates); a free-declared object that arrives kinematically
   pinned (`kinematicEnabled=true`) is explicitly unfrozen so a "frozen scene" cannot sail
   through settle/fall untouched; and a declared `support_prim_path` that does not resolve is
   a loud bundle error, not a silent fall-through downgrade. The verdict also self-declares
   `usd_sha256` — the hash of the exact USD bytes it graded — so any consumer holding the USD
   can reject a verdict produced for different geometry.
3. **SceneForge promotes the sidecar** — the packaging stage's
   `_resolve_runtime_scene_verify_verdict` reads `<usd_dir>/scene_verify.json`, carries it to
   `metadata["packaging"]["scene_verify"]`, and the QA stage copies it into the qa_report.
4. **The gate enforces it** — `scene_verify` is in `_QA_CHECK_ORDER`, AND-reduced into
   `overall_passed`. pass → approvable; warn → approvable (advisory); fail / missing-verdict /
   missing-qa_report / unknown-schema → **not approvable** (HTTP 409). A scene that was never
   verified has no verdict and is therefore **fail-closed** — it cannot be approved. Two
   further locks: the schema check pins the major (`scene_verify/1` exactly; a hypothetical
   `scene_verify/2` is unrecognized → blocked, so a semantics-weakening bump cannot be
   silently trusted), and when the verdict carries `usd_sha256` it is compared against the
   packaged `usd_stage` artifact's recorded sha256 checksum — a stale verdict for rewritten
   geometry blocks with an explicit mismatch detail (content binding, not just path binding).

## Task-level Benchmark Verify (orthogonal, pre-policy)

`scene_verify` asks *is this scene faithful?* Benchmark Verify asks *is this task well-posed?*
— item count agreement, in-workspace reachable spawns, no overlapping spawn footprints
(exact oriented-rectangle overlap, not AABB), items staged clear of the carton, resolvable
instruction. Pure manifest logic, no Isaac:

```
python scripts/tools/run_benchmark_verify.py   # writes artifacts/scene_verify/benchmark_verify/report.json
```

It never touches the frozen `scene_validation` 6-check contract or the PCS scoring path.

## Validated on a real, externally-authored scene (not a PackingBench export)

The generalization claim was tested on a scene the verifier had never seen and that nobody on
this project authored: **Pixar's "Kitchen Set"** (`openusd.org`, ~1788 meshes, Z-up,
`metersPerUnit = 0.01`). A `SceneBundle` declared two props (`BottleLargeRose_1`, `JarA_1`) free
and the counter top as support; the generic runner (`verify_usd_bundle.py`) graded it end-to-end.

**Verdict: `fail`** — and correct. The scene has **zero colliders and zero rigid bodies**
(`collisionAPI = 0`, `rigidBodyAPI = 0` across all 1788 meshes): a render asset, not a
physics-ready scene. The verifier surfaced exactly that:
- `visual_collision_agreement` → **warn / labeling** (`mesh_present: false` — no collision mesh authored),
- `static_settle` → **fail / physics_instability** (the unsupported props drift), and
- `fall_through` → **fail** (the bottle free-falls to `−3.58 m`, well below the `1.08 m` counter).

This is precisely the signal a SceneForge approval gate should act on: a scene that renders fine
but cannot be evaluated on. The verdict sidecar it wrote is byte-identical in shape to the
PackingBench one and is consumed by the SceneForge gate unchanged.

### Real-scene finding → fix: authored units must be honored at load

Testing on a real scene surfaced a robustness bug that PackingBench (always `metersPerUnit = 1.0`)
could never expose: `verify_usd_bundle` **hard-coded `World(stage_units_in_meters=1.0)`**, so a
centimetre-authored scene loaded **100× oversized** and PhysX settled at the wrong scale, while
`GetStageMetersPerUnit` reported `1.0` post-load (Isaac normalizes the metadata). Fix, two parts,
generic-path only (PackingBench builder untouched, and every change is a no-op at `mpu = 1.0`):
1. `build_generic_scene` reads the **authored** `metersPerUnit` *before* `World()` resets it and
   passes it through (`World(stage_units_in_meters=authored_mpu)`) so PhysX simulates at true scale.
2. `capture_scene_evidence` normalizes every captured length (poses, AABBs, `table_top_z`,
   penetration, mesh divergence) to metres by the stage's `metersPerUnit` — the single capture seam.

After the fix the Kitchen Set verdict reports real metres (`table_top_z = 1.08 m`, bottle bottom
`−3.58 m`) and both physics gates fire for the right reason. PackingBench regression re-checked
live: `pack_1_i2` still `metersPerUnit = 1.0`, `table_top_z = 0.501`, `overall_status = pass`
(unchanged). The lesson the real scene taught: for "every scene" the **ingestion** layer (unit
normalization + collider generation) is the real work; the engine generalizes as designed.

## Controlled external corpus: a clean pass + an isolated defect, end-to-end through the gate

The Kitchen Set proves the path *runs* on alien geometry and correctly rejects a non-physics-ready
asset — but it is degenerate (zero colliders), so it can only ever produce a `fail`, and a
diffuse one. It cannot show the two things a SceneForge gate must actually do: **approve a
genuinely-valid arbitrary scene**, and **block on one specific defect while everything else is
green**. So a small, fully-real, non-PackingBench corpus was authored to close that gap.

`scripts/tools/make_external_scene_corpus.py` (authored with the venv's `usd-core`, no Isaac
boot) writes two genuine `UsdGeom.Mesh` scenes — a static table collider with a dynamic box
resting on it — in two variants, each with a matching `SceneBundle`:

| Variant | Geometry | Real verifier verdict |
|---|---|---|
| `external_valid_box_on_table` | box is its own convex collider (visual == collision) | **pass** — all six gates green on genuine settled physics |
| `external_defect_oversize_hull` | box carries a **dedicated collision hull 1.5× the visual** | **fail** — `visual_collision_agreement` only; every other gate green |

Both were graded by the real Isaac runner (`verify_usd_bundle.py --emit-sidecar`); the verdicts
live under `artifacts/scene_verify/external_*/`. The discrimination is earned, not asserted: the
valid box's per-object divergence is exactly `0.0 m`, while the oversized-hull box measures
`~0.03 m` of directional visual↔collision divergence — comfortably past the `0.015 m` fail band —
and *only* that gate fires (settle, fall-through, interpenetration, static-metadata all stay
green because the rigid body still rests on the hull). An earlier revision reported the 1.5×
hull as `clip`-type and attributed that to canonicalization — that attribution was **wrong**:
the authored meshes were wound inward, which flipped every sign in the normal-based signed
distance and swapped phantom↔clip. `_mesh_prim_to_trimesh` now normalizes winding
(`trimesh.repair.fix_normals`) and the re-graded verdict reports the oversized hull correctly
as `phantom` (collision outside visual). Either way it is the same `mesh_disagreement`
inflation class — collision geometry physics scores diverging from the visual geometry a
vision policy renders, **the exact class PCS is structurally blind to**
(see `scene_verify_eval_delta.md`).

These two **real engine verdicts** are then driven through SceneForge's actual gate, not a mock:
the SceneForge tests `test_scene_verify_real_external_scene_pass_approves_end_to_end` and
`..._defect_blocks_end_to_end` feed each verdict to a qa_report artifact and exercise the full
lifecycle — the valid scene flows QA → `qa-pass` (200) → `approve` (200, `status: approved`); the
defective scene is blocked at `qa-pass` with **HTTP 409** whose detail names
`visual_collision_agreement`. This is the first end-to-end proof on a clean *non-PackingBench*
pass and on a single-gate-isolated block — provenance traceable to a committed generator, not a
hand-authored verdict fixture.

## Genuine reconstruction output: the full SceneForge-native pipeline, on-box

The strongest version of "validates SceneForge scenes" is to grade the verifier against the
output of SceneForge's *actual reconstruction toolchain*. That toolchain (the
`colmap_2dgs_polaris_v1` preset: COLMAP SfM/MVS → 2DGS meshing → `usd_from_mesh`) is external
and was not installed; "Polaris" is not a proprietary binary but the recipe name wrapping
public COLMAP + the public 2D-Gaussian-Splatting repo + a mesh→USD packager. So it was
**installed and run on this box** (no sudo: Miniconda + conda-forge `colmap 3.13 (CUDA)` into a
user env; `usd_from_mesh` implemented with `trimesh` + `usd-core` in `scripts/tools/usd_from_mesh.py`).

A real capture was reconstructed end-to-end:
1. **Capture** — 32 real photos (Tanks&Temples "truck", subsampled from the standard set).
2. **Reconstruct** — the preset's exact command, `colmap automatic_reconstructor --image_path …
   --workspace_path …` (GPU SIFT + CUDA patch-match on the A5000): 22 images registered →
   dense MVS (114k fused points) → Poisson mesh, **460 460 faces**.
3. **Package** — `usd_from_mesh --mesh meshed-poisson.ply --output scene.usda --static-collider`
   authors the reconstructed surface as a static environment body (triangle-mesh collider, no
   rigid body) plus a `SceneBundle`.
4. **Verify** — `verify_usd_bundle.py` graded it under Isaac.

**Result — genuine discrimination on reconstruction output:**

| Packaging of the same 460k-face COLMAP/MVS mesh | Verdict |
|---|---|
| Correct (static collider + static tag) | **pass** — all six gates green |
| Raw render geometry (no collider, not tagged static) | **fail** — `static_settle` (the un-collidered mesh, read as a free body, free-falls ~5.16 m); `visual_collision_agreement`/`fall_through` warn (no collision mesh / no support authored) |

Both real verdicts are committed under `artifacts/scene_verify/recon_truck_*` and the bundles +
sidecars under `artifacts/scene_verify/_recon_corpus/` (the 20 MB flattened `scene.usda` files are
regenerable from the steps above and are not checked in). They are then driven through the actual
SceneForge gate by `test_scene_verify_real_reconstruction_{packaged,unpackaged}_end_to_end`:
the packaged reconstruction flows QA → `qa-pass` → `approve` (200); the raw one is blocked at
`qa-pass` with **HTTP 409** naming `static_settle`. This closes the gap to the literal goal —
the verifier validates the output of SceneForge's own reconstruction pipeline, accepting a
correctly-packaged real scene and rejecting a not-physics-ready one. (The 2DGS meshing step was
not needed: COLMAP's own dense+Poisson mesh is a complete reconstruction; 2DGS would only change
mesh quality, not the verification contract.)

## Integrity invariants (upheld by construction)

- PCS scoring path (`app/task_definitions/packingbench.py`) is untouched.
- The frozen `scene_validation` 6-tuple contract is untouched; the verifier derives its own
  richer report and only projects a conformant legacy summary via the existing factory.
- Visual-vs-collision uses directional/signed distance, never symmetric Chamfer.
- No gate is loosened to manufacture a pass; the one threshold-adjacent change (Benchmark
  Verify's oriented-overlap epsilon) is a correctness fix for the rotated-AABB false-positive,
  verified against the true OBB intersection (which was 0.0).
