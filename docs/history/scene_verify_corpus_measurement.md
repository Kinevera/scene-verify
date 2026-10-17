# Scene-verifier corpus measurement — v0.1 (9 instances)

The verifier's first encounter with more than one real scene. Run:
`run_scene_verify_corpus.py --robot yam --storage-root .../storage` (venv orchestrator;
launches `verify_scene_bundle.py` in a fresh Isaac process per row). Report:
`artifacts/scene_verify/corpus/corpus_report.json`.

## Result: 9 instances → **5 pass / 4 fail**

(Current, after the interpenetration refinement and the deterministic-sampling fix below. The
first run, on the coarse-AABB interpenetration gate with unseeded sampling, was 4 pass / 5 fail;
the intermediate run was 5 pass / 1 warn / 3 fail — see the follow-up sections for the journey.)

| instance | items | verdict | non-passing gates |
|---|---|---|---|
| pack_1_i1 | 1 | **pass** | — |
| pack_1_i2 | 1 | **pass** | — |
| pack_1_i3 | 1 | **pass** | — |
| pack_2_close_i1 | 2 | fail | static_settle |
| pack_2_close_i2 | 2 | fail | visual_collision_agreement (book_brick collider) |
| pack_2_close_i3 | 2 | **pass** | — |
| pack_3_dense_close_i1 | 3 | **pass** | — |
| pack_3_dense_close_i2 | 3 | fail | static_settle + visual_collision_agreement |
| pack_3_dense_close_i3 | 3 | fail | static_settle + fall_through (+ mesh warn) |

Per-gate (current): scene_load 9/9 pass · interpenetration **9/9 pass** · static_settle 6/3 ·
fall_through 8/1 · static_metadata_present 9/9 pass · visual_collision_agreement 6 pass / 1 warn / 2 fail
(every non-pass is the same asset: `book_brick`).

**All single-item rows pass; the genuine physics failures are entirely in the multi-item
`pack_2`/`pack_3` rows (settle/fall-through). The only mesh-agreement failures are `book_brick`,
a genuinely loose collider (see below).**

## Headline finding (the eval-credibility result)

The benchmark's **own cached scene-validation summaries mark all 9 rows "pass"** — but those
are baked-in contract fixtures in `scene_validation.py`, not live runs. They are stale: a
**live host validator fails the same scenes**.

Ground-truth, two failing rows run through the unmodified validator:

| instance | validator result | pump_bottle settled_displacement |
|---|---|---|
| pack_3_dense_close_i3 | **fail** (spawn_pose_alignment, spawn_stability) | **3.07 m** (ejected) |
| pack_2_close_i1 | **fail** (spawn_pose_alignment, spawn_stability) | **0.27 m** (topple) |

Because the verifier and validator now share `build_packingbench_scene`, this is the expected
agreement — and it's the point: **a measurable fraction of scenes the benchmark records as
validated actually fail live physical validation.** The seeded dense scenes are unstable —
items shove/topple/eject on settle (pack_3_i3: a bottle thrown 3+ m and falling to z=−3.3 m).
The verifier surfaces this; the benchmark's stale cache hides it. This is exactly the
scene-credibility signal the verifier exists to produce.

## Honest breakdown of the fails (true vs marginal)

- **Real, validator-confirmed:** `static_settle` / `fall_through` on the dense rows. pack_3_i3
  is a catastrophic blowup (not a tolerance debate); pack_2_i1 is a clean 0.27 m topple. These
  are genuine scene-physics defects.
- **Marginal / verifier-refinement, NOT yet trustworthy as scene defects:**
  - **interpenetration is coarse.** Some fails are tiny AABB overlaps (pack_3_i1: 7 mm³ — a
    1.9 mm cube) that are almost certainly bounding-box false-positives on validly-but-tightly
    placed items. The gate needs mesh/contact-level overlap, not raw AABB, before its dense-row
    fails count as defects. (The larger overlaps, ~850 mm³, co-occur with real blowups.)
  - **book_brick mesh agreement sits right at threshold** (phantom 0.015–0.017 vs 0.015 fail)
    across rows — a consistent borderline collider over-approximation. Real-but-minor, or the
    threshold is a touch tight; either way it's a margin call, not a clear defect.

So the honest number is **not** "5/9 scenes are invalid." It is: **all physically-sound
single-item rows pass; the dense multi-item rows fail live physics validation (validator-
confirmed), with the headline that the benchmark's recorded scene-validity status overstates
reality — plus two verifier refinements (coarse interpenetration, borderline mesh threshold)
surfaced by meeting real scenes.**

## Infrastructure finding

**Isaac hard-aborts (core dump in `carbOnPluginPreStartup`) on the *second* scene build in one
process.** The corpus runner therefore launches one Isaac process per row. The soundness
runner's in-process multi-build (clean baseline + 5 defects in one process) hits the same
crash and needs the same subprocess-per-case fix before it can run live.

## Follow-up: interpenetration refined to mesh/contact level (done)

The one change the corpus data called for is now in. `interpenetration` no longer fails on raw
AABB overlap; for every AABB-overlapping dynamic pair it computes the **mesh-level penetration
depth between the collision proxies** (`geometry.pairwise_collision_penetration_depth_m`) and
fails only when that depth exceeds `interpenetration.max_penetration_depth_m` (default 3 mm).
The coarse AABB-volume floor remains only as a fallback for a pair with no usable collision
geometry, so the gate never silently passes a pair it could not assess at mesh level.

Re-running the same 9 rows (same scoring path, unchanged) confirms the dense-row interpenetration
fails were **all coarse-AABB false-positives**:

| instance | before | after | interpenetration: AABB overlap → mesh depth |
|---|---|---|---|
| pack_3_dense_close_i1 | fail (interpenetration) | **pass** | 7 mm³ → **0.0 m** |
| pack_3_dense_close_i2 | fail (mesh+interp+settle) | fail (settle) | 847 mm³ → **0.0 m** |
| pack_3_dense_close_i3 | fail (mesh+interp+settle+fall) | fail (mesh+settle+fall) | 102 mm³ → **0.0 m** |

`interpenetration` now passes **9/9** — even the 847 mm³ AABB overlap is a bounding-box corner-clip
with zero actual mesh penetration.

> Honest scope of this gate: it has **zero live true positives on record** (0 of 15+ committed
> verdicts, injected defects included) and is structurally unlikely to fire on a settled capture —
> PhysX depenetrates an injected overlap during the settle, so the displacement trips
> `static_settle` instead (the committed soundness matrices show exactly that). Additionally,
> pairs involving a static-expected object are excluded at capture, so item-vs-carton penetration
> is never assessed by it, and the AABB pre-pass uses visual-purpose bounds, so collider-only
> penetration is invisible to it. Its demonstrated live effect so far is removing AABB
> false-positives; positive sensitivity is proven only in the controlled venv suite. Crucially, **every genuine, validator-confirmed physics fail is
untouched**: pack_3_i3 still ejects (static_settle max linear 5.85 m + fall_through), pack_2_i1
still topples (0.159 m), pack_3_i2 still drifts past tolerance (0.0150 m > 0.010 m). The refinement
removed false *fails*, not real ones — and pack_3_dense_close_i1, whose only failure was the
false-positive, now correctly passes.

Intermediate distribution after this step: **5 pass / 1 warn / 3 fail** (was 4 pass / 5 fail).
The remaining `warn`/`fail` flips were all `book_brick` mesh-agreement — resolved next.

## Follow-up: book_brick mesh-agreement — noise vs. real (done)

The remaining margin call was `book_brick`'s `visual_collision_agreement`, which flipped warn↔fail
across runs. The dedicated look settled **both** questions — is it real, and why does it flap:

- **It is a real, substantial collider over-approximation, not a false positive.** Across the three
  rows that carry `book_brick`, `clip_max` is rock-stable at **0.011862 m** and `phantom_max` clusters
  at **~0.014–0.016 m** — both far above the 0.005 m warn line. The collider genuinely bulges ~12–16 mm
  beyond the visual mesh. The gate is correct to flag it; this is exactly the asset-fidelity signal
  the verifier exists to surface.
- **The warn↔fail flap was a *reproducibility* defect, not a threshold problem.** Both the divergence
  and penetration checks estimate a max statistic from a finite **random** surface sample; with an
  unseeded RNG the same scene produced slightly different numbers each run, so a value near the 0.015 m
  line flipped verdict between identical runs. Fix: a **fixed sample seed** (`geometry.MESH_SAMPLE_SEED`,
  via `trimesh.sample.sample_surface(..., seed=)`, portable across the venv/Isaac trimeshes) — same
  scene now yields **bit-identical** numbers and verdict run-to-run (verified live: pack_3_dense_close_i3
  `book_brick` = 0.014491 / 0.011862 / warn on two consecutive Isaac runs). **No threshold moved, no
  statistic changed**; seed 0 is a conventional default chosen before seeing outcomes, not tuned.

### Follow-up: cross-row spread eliminated (pose-invariant divergence, done)

Seeding fixed *within-scene* reproducibility, but a residual remained *across* rows: `book_brick`'s
`phantom_max` still spanned ~0.0145–0.0164 because the **convex-hull proxy** was re-triangulated by qhull
under each scene's rotation, shifting where the seeded samples landed (the identical `clip_max` proved the
underlying geometry was the same — only orientation differed; `book_brick` settles to anything from ~10° yaw
to a full off-axis tumble across rows).

A per-object divergence is intrinsic to the asset, so it should not depend on scene orientation at all. The
verifier now **removes the object's world orientation before measuring** (`geometry._world_orientation_inverse`
— the nearest rotation to the first mesh prim's world transform, applied to both visual and proxy). Crucially
it removes *only orientation*, preserving world scale: an early version that mapped into the prim's full local
frame reported authored, pre-scale sizes (~30× off, 0.53 m) — a scale-correctness test now guards that. The
proxy hull is rebuilt on consistently-oriented vertices every scene, so the divergence is pose-invariant.

Result (live, all three `book_brick` rows): `phantom_max` = **0.017181 m, bit-identical** (cross-row spread
**0.000000 m**, was 0.0026 m), at correct world scale, all consistently `fail`. The flap is gone; the gate now
reports the asset's true, stable ~17 mm over-approximation. (No threshold or statistic changed; the
interpenetration check stays in world frame — objects must share a frame to detect cross-object overlap.)

Final distribution: **5 pass / 4 fail** (unchanged). The 4 fails: 3 genuine physics (settle/fall-through,
validator-confirmed) + `book_brick`'s real loose collider, now flagged reproducibly and pose-invariantly.

## Next

- The soundness runner is now subprocess-per-case (`verify_scene_bundle.py --inject <defect>`,
  one fresh Isaac process per case) — the in-process multi-build that crashed Isaac is gone.
  Point `--instance-id` at a multi-item row (e.g. `pack_2_close_i1`) to exercise the
  interpenetration/fall-through defects live.
- The stale-cache finding is worth raising with the benchmark owners: cached
  `scene_validation` summaries no longer match live physics for the multi-item rows.
- **`book_brick` has a genuinely loose collider (~17 mm beyond its visual mesh)** — worth raising
  with the asset owners to tighten it; the verifier flags it correctly, reproducibly, and now
  pose-invariantly (bit-identical across all rows regardless of settle orientation).

## Stage 3 — the two measurement dimensions, and the honest delta

Scene-validity is measured along **two orthogonal axes**, each with its own corpus number:

1. **Scene-level (`scene_verify`, this document):** 9 instances → **5 pass / 4 fail**. The 4
   fails are 3 validator-confirmed physics failures on the dense multi-item rows + `book_brick`'s
   loose collider. Headline: *the benchmark's cached scene-validation status overstates validity*
   — live physics fails scenes the cache records as passed.

2. **Task-level (`benchmark_verify`, Stage 2b):** 9 instances → **9 pass / 0 fail**
   (`run_benchmark_verify.py`, report at `artifacts/scene_verify/benchmark_verify/report.json`).
   Every shipped task is well-posed: item counts agree, all spawns are in-workspace and
   non-overlapping (by exact oriented-rectangle overlap — the rotated-AABB false positive on
   `pack_3_dense_close_i3` was confirmed a non-overlap and is correctly *not* flagged), and the
   instruction resolves. So the corpus's invalidity is entirely **scene-physics**, not
   task-authoring — a useful separation: the two layers fail for different reasons and neither
   masks the other.

### The eval-delta (raw-vs-verified PCS): stated honestly, not fabricated

The original deck wanted "% change in measured policy success when invalid scenes are filtered."
That delta is **not honestly demonstrable today**, for a reason intrinsic to the current corpus:

- PCS is purely geometric/kinematic and **vision-invariant**, and no vision policy scores above
  ~0.0 on these rows. So a vision policy's success rate is 0 before *and* after filtering — the
  delta is trivially 0, which would misleadingly read as "verification doesn't matter."
- Only the **geometric oracle** responds, and only to *physics/collision* invalidity (it cannot
  react to *visual* invalidity at all). The oracle already reaches PCS=1.0 on the sound
  single-item rows and is independently blocked on the dense rows by the same instability the
  verifier flags — so "oracle PCS on verifier-failed rows" is confounded by fit/control issues,
  not a clean measurement of the verifier's filtering value.

The intellectually honest statement is therefore: **the verifier's value is shown by the
scene-validity finding above (live physics fails cache-passed scenes) and by the controlled
injected-defect discrimination (the soundness gate), not by a vision-policy PCS delta — which
this corpus cannot yet produce.** A clean delta needs either a vision-conditioned policy with
non-zero success or a corpus with *visual* (not just physics) defects; both are deferred and
named, not papered over. The generic USD path (below) is what makes ingesting such a corpus
possible without any PackingBench coupling.

## Generalization — every scene, not just PackingBench

The engine (`app/scene_verify/`) has no benchmark identity; it grades `CapturedSceneEvidence`.
Two producers feed it through one shared `capture_scene_evidence`: the PackingBench manifest
runner (`verify_scene_bundle.py`) and the **generic USD-bundle runner** (`verify_usd_bundle.py`),
which verifies any `SceneBundle` (a USD path + the prims to grade) — e.g. a SceneForge approved
bundle. With `--emit-sidecar` it writes `scene_verify.json` beside the USD, which the SceneForge
`scene_verify` QA gate promotes and enforces (fail-closed when absent). See
`scene_verify_end_to_end.md`. This is what closes the gap from "PackingBench scenes are verified"
to "**every approved scene is verified**."

## Robustness of the 5/4 distribution (sensitivity + determinism)

Two checks lock the corpus result down as a property of the scenes rather than of the
measurement (`scripts/tools/threshold_sensitivity_sweep.py`,
`artifacts/scene_verify/corpus/threshold_sensitivity.json`):

**Threshold sensitivity** — every row's pass/fail re-derived from committed `evidence.json`
under scaled thresholds (the reimplementation reproduces all 9 committed verdicts at ×1.0
before sweeping, else it aborts):

| scale | distribution | flips |
|---|---|---|
| ×0.8 (tighter) | 5/4 | none |
| ×1.0 baseline | 5/4 | — |
| ×1.2 / ×1.5 / ×2.0 (looser) | 6/3 | `pack_2_close_i2` → pass |
| settle-only ×3.0 | 5/4 | none |
| ×0.5 (much tighter) | 4/5 | `pack_2_close_i3` → fail |

Honest reading: **three of the four failures are decisive** — their offending magnitudes sit at
1.5×–32× the fail lines (stapler 1.5×/3.0×, book_brick-in-dense-i3 co-fails settle at 6×/16×,
pump_bottle 16×/32× + fall-through, which is unscaled geometry). **`pack_2_close_i2` is the one
marginal row**: its only failure is book_brick's phantom at 1.15× the fail line, so a 20% looser
mesh band flips it. That failure is still defensible — the divergence is bit-identical in all
3 rows the asset appears in (deterministic asset property, not noise) — but anyone re-tuning
`mesh_agreement` thresholds should know this row rides on it.

**Run-to-run determinism** — the corpus was graded twice, three days apart, across a geometry-
code change (`13b6edb` 2026-06-29/30 vs `cdc0b6e` 2026-07-02): all 9 `evidence.json` files are
**byte-identical** — every pose float, displacement, and divergence value reproduced exactly;
the only diffs in the row artifacts are `verified_at` timestamps (verifiable:
`git diff 13b6edb cdc0b6e -- 'artifacts/scene_verify/pack_*'`). The settle capture is fully
deterministic, so the distribution is not a physics-noise draw.
