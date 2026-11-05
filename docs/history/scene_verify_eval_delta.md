# Scene Verifier — Stage 3 eval-delta (does scene validity change measured policy success?)

The verifier's headline contribution is not the checker but the **measurement**: *a measurable
fraction of approved scenes are invalid, and filtering them changes measured policy performance.*
This document records the eval-delta work: what was built, the **structural** eval-delta result
(sound, code- and matrix-backed), and the precise reason a single empirical `Y` is not quoted here.

## What was built (the co-located oracle/policy harness)

For a sound delta the policy and the verifier must run on the **same** scene. No single branch had
both: the geometric oracle lives on the demo-motion / v1 / v6 branches; the verifier + `defects.py`
+ the `pre_reset_hook` seam live only on `feat/scene-verify`. The cross-worktree shortcut was
**proven unsound** — `release/packingbench-v6` runs *randomized, re-seeded, differently-asseted*
variants of the same row ids (parsed both manifests), so pairing v6 oracle PCS against this branch's
verifier verdicts would compare different scenes.

So the oracle was brought **into the verifier's worktree** and made to run on the exact deterministic
v0.1 scenes the verifier graded. That required clearing a real cross-branch integration stack — asset
staging, an async-only DB (sandbox robot-metadata injection to bypass the sync `SessionLocal` path),
removing the drifted `EvaluationJob` write, two `EpisodeRunner` API shifts, the typed-metric
`{"episodes": [...]}` shape, task registration, applying the task **success-evaluator**
(`final_state["packingbench"]` mutation), and `compose_scene` to spawn the carton/item as **dynamic
rigid bodies** (without it they load as static props and `get_state` reads no pose). After that the
scene loads, physics is live, and the **canonical PCS** (`PartialCompletionScoreMetric` via
`build_metric_episode_data` + the task `get_success_evaluator`) computes a real score — the scoring
path is used verbatim, never modified.

Two policies were exercised on `pack_1_i2`:
- **Geometric oracle** (`oracle_top_down_pick_place`): runs end-to-end (`advancing to item 1/1 …
  DONE`) but its parallel-jaw grasp does not hold the item here (item displacement ~1mm; configured
  pick point `[0.17,-0.42]` is 3.5cm off the true spawn `[0.192,-0.448]`, and physical grasp needs
  the *hardened* oracle's kinematic-attach from another branch). PCS = 0.
- **Ideal kinematic placement** (item spawned in the carton interior, no-op robot): the item settles
  **stably and centered with zero protrusion** — but `inside_box` is still false because the carton
  interior is `0.201 × 0.09 × 0.074 m` and `pump_bottle_small` is too tall upright and too fat lying
  down (settled bottom ~5mm below the scorer's interior floor). The other two `pack_1` items
  (`cracker_box` 213mm, `power_drill` 185mm) do not fit the carton in any orientation. So no `pack_1`
  row admits a trivial ideal placement; `inside_box=true` requires threading the oracle's exact pose.

Net: the *policy-driven* harness is real and reusable; a single **policy-scored** `Y` needs the
oracle's precise success pose (or the hardened kinematic-attach), which is reproducing the oracle.
That remains scoped. **But the empirical number does not require a policy** — see the next section.

> Why the earlier attempt stalled and this one does not: the cross-worktree run above scored the
> `so101` `workstation_table` scene, whose `target_carton_10` interior is `0.201 × 0.09 × 0.074 m`
> — too small for any `pack_1` item. The **canonical v0.1 manifest** on this branch uses a
> `0.30 × 0.22 × 0.17 m` carton interior, in which **all six catalog items fit** (upright or lying).
> That is what makes a genuinely-packed `inside_box=true` state constructible without a policy, and
> so makes the executed eval-delta below possible.

## The structural eval-delta result (sound; no tight-fit baseline required)

The delta does not actually need a perfect baseline. It follows from **what PCS reads** versus **what
the verifier catches**, and the latter is already empirically confirmed by the committed soundness
discrimination matrix.

**What PCS reads.** `Pack1Task` success = `_inside_box_and_protrusion` + `_evaluate_item_state`
(`app/task_definitions/packingbench.py`). Inputs: item world pose, item dimensions, item rotation,
carton pose, carton inner dimensions, and post-settle displacement (stability). It **never** reads:
collision-vs-visual mesh agreement, or static-metadata tags.

**What the verifier catches** (six gates), with the injected-defect matrix
(`artifacts/scene_verify/<scene>/soundness/`) as evidence:

| Verifier gate (defect) | PCS reads the relevant property? | Relationship |
|---|---|---|
| `fall_through` | yes — post-settle pose (stability check; a runtime fall also flips `floor_ok`/`inside_box`) | **co-detected** (PCS also fails) |
| `interpenetration` (target item) | yes — via post-settle displacement / stability | **co-detected in principle** (not executed in the harness; NB the live gate itself has zero true positives on record — post-settle capture lets PhysX depenetrate first, and static-involving pairs are excluded — so this class is caught live by `static_settle`) |
| `visual_collision_agreement` | **no** — PCS scores collision geometry/pose, never visual↔collision divergence | **PCS-blind ⇒ inflation** |
| `static_metadata_present` (missing static tag) | no at the criterion level; *may* be caught indirectly if the untagged body drifts | **partially PCS-blind** |

**The delta.** For any policy that geometrically packs the item, a scene that fails
`visual_collision_agreement` is still scored `inside_box`/success by PCS — the rendered geometry a
vision policy sees diverges from the collision geometry PCS scores. These scenes are **invalid but
counted as successes**: they *inflate* measured success. Filtering verifier-invalid scenes removes
them, lowering the reported number by the prevalence of this defect class among scored scenes. The
`fall_through` / `interpenetration` classes are the opposite (verifier and PCS agree), so filtering
those is neutral-to-deflationary. The *direction and per-class behavior* of the eval-delta is thus
established structurally; only the scalar magnitude (the prevalence-weighted `Y`) awaits a scored
corpus with a packing policy.

This is exactly the project thesis: **geometric PCS is structurally blind to the visual-validity
failures a vision policy would be misled by, and the verifier catches precisely those.**

Caveat (honesty): the verifier's `visual_collision_agreement` gate is threshold- and
geometry-dependent, and *which* gate catches a given collision defect depends on how the defect is
injected. Two distinct injection styles, reported precisely:
- **In-place collider scaling** on a live corpus scene (`pack_2_close_i1__soundness__{over,under}size_collision_hull`)
  fires **`static_settle`**, not `visual_collision_agreement` — scaling a collider also destabilizes
  the physical settle, so the physics gate is what trips (verified: `visual_collision_agreement`
  *passes* there, `static_settle` fails).
- **Isolated mesh disagreement** with the rendered mesh held fixed and a dedicated oversized
  collision-hull child (`external_defect_oversize_hull`) fires **`visual_collision_agreement`
  alone**, with every physics gate green — the clean case the eval-delta rests on.

So the PCS-blind inflation set is precisely "scenes whose visual↔collision divergence exceeds the
mesh-agreement threshold *without* also destabilizing physics"; when a defect also perturbs the
settle, PCS's own stability check may co-detect it. This distinction is now executed and quoted in
the section below, not left as an argument.

## Executed empirical eval-delta (the number, from the real scorer)

`scripts/tools/run_eval_delta_pcs.py` executes the **unmodified** success evaluator
(`Pack1Task.get_success_evaluator`) on constructed final-states — no policy, no Isaac — and
tabulates PCS per defect class against the **real** verifier verdicts. Output:
`artifacts/eval_delta/pcs_inflation_matrix.json`.

For each of the 6 catalog items that fit the `0.30 × 0.22 × 0.17 m` carton, three states are scored:

| item | PCS (valid packed) | PCS (collision-defect) | PCS (fall-through) |
|---|---|---|---|
| tomato_soup_can | 1.00 | 1.00 | 0.50 |
| cracker_box | 1.00 | 1.00 | 0.50 |
| mustard_bottle | 1.00 | 1.00 | 0.50 |
| power_drill | 1.00 | 1.00 | 0.50 |
| rigid_pouch | 1.00 | 1.00 | 0.50 |
| warehouse_brick | 1.00 | 1.00 | 0.50 |

**Visual/collision-divergence class — PCS inflation = 6/6 (100%); verifier evidence = the isolated
real graded scene, not per-item runs** (the verifier graded none of the 6 constructed states —
claiming a 6/6 "catch rate" over them would fabricate a denominator).**
The collision defect lives only in collision geometry, which `final_state` does not even carry, so
every scorer input is byte-identical to the valid scene → PCS is unchanged at 1.00. This is not a
tautology of "same poses in, same score out": it is the substantive fact that **the PackingBench
scoring contract has no field for collision-vs-visual agreement**, so a mismatched collider is
structurally invisible to it. The verifier's evidence is the isolated case
`external_defect_oversize_hull` (a real graded scene): `visual_collision_agreement → fail` while
**every physics gate (`static_settle`, `fall_through`, `interpenetration`) stays green**. Because
PCS reads only those (valid) physics poses, a vision policy scored on that scene earns full PCS
while the geometry it *sees* diverges from the collider — the mesh-agreement gate is the sole
detector.

**Physics-divergence class — PCS co-detects = 6/6 (100%), executed on fall-through only.** The
fall-through state drops the item's post-settle pose below the carton floor; the scorer reads that
pose, the **stability** check fails (the pre-settle pose still satisfies `inside_box`, so this is
the weakest co-detection variant — a runtime fall-through would also flip `inside_box` → 0.0), and
PCS falls 1.00 → 0.50 on its own. Interpenetration is argued structurally, not executed. The
verifier (`fall_through` / `static_settle`) is confirmatory here, not unique — matching the
structural prediction.

Honest scope of this number: the *placements are constructed*, not achieved by a learned policy
(no vision policy scores > 0 on PackingBench today, and the geometric oracle's exact success pose is
un-reproduced — both stated above). So this is the eval-delta **conditional on a scene being packed**:
*given* a packed scene, PCS certifies it as a full success whether or not the collider matches the
render, and only the verifier separates the valid from the invalid. The prevalence-weighted
corpus `Y` still awaits a scoring policy; the per-scene inflation magnitude (full success → rejected)
is now executed, not just argued.

## Integrity

PCS (`app/task_definitions/packingbench.py`) and the frozen `scene_validation` contract are
untouched; the score is computed by the canonical metric path verbatim. No scene input was adjusted
to manufacture an `inside_box`. The oracle policy + canary harness used for the live runs are
analysis tooling, kept out of the `feat/scene-verify` commit (git-excluded), not part of the PR.
