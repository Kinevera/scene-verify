# PR: SceneForge Verify — generic USD scene verification layer + Benchmark Verify

**Branch:** `feat/scene-verify` → base `main`

## What this adds

A benchmark-agnostic scene verification engine (`app/scene_verify/`) that grades any USD
scene bundle in live Isaac Sim and emits a stable `scene_verify/1` verdict JSON, plus the
PackingBench adapter, task-level Benchmark Verify, and the measurement/soundness evidence
that makes the verdicts defensible.

### The engine — 6 gates, 3-state verdict

| Gate | Bucket | Detects |
|---|---|---|
| `scene_load` | load | stage fails to open/compose |
| `visual_collision_agreement` | mesh_disagreement | collision hull diverges from visual (directional signed distance: phantom = collision outside visual, clip = visual outside collision — never symmetric Chamfer) |
| `interpenetration` | interpenetration | post-settle AABB overlap between objects |
| `static_settle` | physics_instability | objects drift/topple during passive settle (linear 0.01 m / angular 5°) |
| `fall_through` | physics_instability | object bottom below the captured floor plane |
| `static_metadata_present` | missing_static_metadata | static-expected object missing its static tag (labeling, structurally disjoint from physics) |

Verdicts self-declare the graded stage's `usd_sha256`, binding the verdict to the exact
bytes it graded. Partial captures (failed pose capture / missing AABB / crashed tag scan)
surface as `warn` with the unassessed ids listed — never a silent pass.

### PackingBench adapter (frozen contract untouched)

`app/benchmarks/packingbench/scene_verify_packingbench.py` projects the verdict onto the
legacy six-check summary via the existing `.from_checks()` factory only. Every failing
verdict gate reaches at least one legacy check (property-tested), so a failing verdict can
never project to a passing summary.

### Benchmark Verify (task level)

`verify_packingbench_task`: object count, label uniqueness, workspace containment (real
Sutherland–Hodgman oriented-rectangle clipping), instruction ambiguity. 9/9 official rows
byte-reproducible; end-to-end negative test on a mutated instance.

### Runners + hardening

`scripts/tools/verify_usd_bundle.py` / `verify_scene_bundle.py`: bundles may raise
`settle_steps` but never lower it below the config floor; kinematically-pinned
free-declared objects are explicitly unfrozen; a declared-but-unresolvable
`support_prim_path` is a loud error; `scene_id` is path-sanitized.

## Measurement (committed artifacts)

- **Corpus:** 9 v0.1 rows → **5 pass / 4 fail**, every failure root-caused with a concrete
  offender (`docs/packingbench/scene_verify_corpus_rootcause.md`).
- **Soundness:** injected-defect discrimination matrix green (clean stays green; each
  defect fires only its own gate; physics vs labeling buckets provably disjoint).
- **Robustness:** threshold sensitivity sweep — 3/4 failures decisive (1.5×–32× over the
  fail lines, stable ×0.8–×2.0); `pack_2_close_i2` is honestly marginal (phantom at 1.15×
  the fail line, flips at mesh×1.2) and is flagged as such. Two corpus runs 3 days apart
  produced byte-identical evidence.
- **Eval delta:** the unmodified PCS scorer is provably blind to collision-vs-visual
  divergence (falsifiable CI lock) and co-detects fall-through via stability
  (`docs/packingbench/scene_verify_eval_delta.md`).

## Guarantees

- `app/task_definitions/packingbench.py` (PCS scoring) and
  `app/benchmarks/packingbench/scene_validation.py` (frozen 6-check contract): **zero
  changes across all layer commits** — verify with
  `git diff --stat ed0b6cd~1..HEAD -- app/task_definitions/packingbench.py app/benchmarks/packingbench/scene_validation.py`
  (empty).
- Original `validate_packingbench_scene.py` byte-for-byte unchanged.

## Tests

80 tests in the layer's tier (`tests/scene_verify/`, `tests/benchmarks/test_scene_verify_packingbench.py`,
`tests/benchmarks/test_benchmark_verify.py`), all green. Isaac-side: live soundness gate +
corpus re-grades executed on this box (Isaac Sim 5.1).

## Docs

`docs/packingbench/scene_verify_end_to_end.md` (architecture + runbook),
`scene_verify_corpus_measurement.md`, `scene_verify_corpus_rootcause.md`,
`scene_verify_eval_delta.md`, `scene_verify_phase0_results.md`.

## Known limitations (deliberate, documented)

- Interpenetration gate has zero live true-positives on this corpus (PhysX depenetrates
  before capture; static pairs excluded) — structural coverage only, disclosed in docs.
- Directional labels are best-effort on open/non-watertight meshes
  (`fix_normals` applied, meaningful on closed meshes).
- `closest_point_naive` is O(samples×faces); huge authored-collider meshes saturate at
  `warn`, never fail-open.

Companion PR (SceneForge repo): `feat/sceneforge-scene-verify-qa-gate` — the thin QA gate
that consumes these verdicts and blocks approval.
