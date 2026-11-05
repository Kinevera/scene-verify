# scene_verify v0.2: reconstruction-fidelity gates + authored-phase interpenetration

Stacks on `feat/scene-verify` (open/merge that first; this PR should diff against it).
Closes the two self-owned limitations disclosed in the v0.1 natural-corpus writeup
(`docs/packingbench/scene_verify_natural_corpus.md`, updated in this PR).

## What changed

### 1. Reconstruction-fidelity gates (new, opt-in by provenance)

v0.1 demonstrated its own boundary: a degenerate 109-face reconstruction is physically
self-consistent and passed every physics gate. Two new gates close it:

| gate | signal | basis |
|---|---|---|
| `recon_surface_density` | face count + mesh-area/AABB-surface-area ratio | **measured live from the stage**, never trusted from the producer |
| `recon_registration_coverage` | SfM registered-frames ratio | declared by producer (verifier cannot re-run SfM); recorded as `basis: declared_by_producer`, warns fail-closed when absent |

- Both density signals are **scale-invariant** — COLMAP output has arbitrary units, so nothing
  is denominated in metres.
- Gates run **only when the bundle declares reconstruction provenance**
  (`provenance.reconstruction`). A curated benchmark asset is legitimately low-poly; its
  verdict is **byte-identical to v0.1** — locked by
  `test_fidelity_gates_absent_without_reconstruction_declaration`.
- Thresholds live in `thresholds.yaml` (`fidelity:` section) and were **calibrated in-sample
  on the pilot corpus** — disclosed in the writeup; the re-grade demonstrates the mechanism,
  not an out-of-sample error rate.

### 2. Authored-phase (t=0) interpenetration capture

PhysX depenetrates authored overlaps within the first settle steps, so the post-settle capture
alone was structurally blind to exactly the defect the interpenetration gate exists for (the
live soundness matrix recorded `fired=['static_settle']` for the injected case). The capture
layer now measures pairwise overlaps **before any physics step**; the gate grades both phases
with the same thresholds and phase-labels offenders.

### 3. NaN fail-open fix (found live by the soundness harness)

Degenerate signed-distance sampling returned `NaN` penetration depth, and `NaN > tolerance` is
`False` — the gate silently passed a 0.000293 m³ injected overlap at both phases. Non-finite
depths now route to the AABB-volume fallback (unit-locked:
`test_nan_penetration_depth_falls_back_to_aabb_floor`) and are normalised to `None` at the
capture seam.

### 4. Hardening

- Live soundness bar now **requires** interpenetration sensitivity (`interp_sensitivity` in
  `gate_pass`) so the fix cannot regress silently.
- Legacy projection: failing gates with no explicit mapping (fidelity gates, any future gate)
  fold into `tracked_object_state` — no gate can be projection-orphaned
  (`test_projection_unmapped_gate_fail_cannot_project_to_pass`).

## Guarantees

- **Scoring path untouched**: `git diff --stat a036127..HEAD -- app/task_definitions/packingbench.py
  app/benchmarks/packingbench/scene_validation.py` is empty.
- **Schema unchanged**: verdicts stay `scene_verify/1` (additive gates; verifier 0.2.0). The
  SceneForge gate consumes v0.2 verdicts with **zero consumer-side changes** — proven live
  (`artifacts/scene_verify/natural_corpus/approval_flow_demo_v2.txt`).

## Evidence (all executed live on this box)

- **Soundness re-run** (`pack_3_dense_close_i1/soundness/discrimination_matrix.json`):
  interpenetration fired live for the first time (`fired=['interpenetration', 'static_settle']`,
  sensitivity=True), clean stayed green, crux disjoint, `gate_pass=True`.
- **Natural corpus re-grade** (fidelity gates live): 2 pass / 1 warn / 3 fail —
  `wh_secret` (10/90 registered, 109 faces) fails both fidelity gates; physics-gate outcomes
  unchanged from v0.1. Table: `artifacts/scene_verify/natural_corpus/results_table.md`.
- **Approval flow on v0.2 verdicts**: pass → approved; fidelity fail → 409 naming
  `recon_registration_coverage, recon_surface_density`; missing → 409; stale hash → 409.
- **venv**: `tests/scene_verify` 84 passed; adapter/benchmark-verify suites green.
  (The 15 `test_packingbench_seed_persistence` failures are a pre-existing robot-catalog
  test-fixture issue — they reproduce identically at base `a036127`.)

## Known limitations (unchanged or new-and-disclosed)

- Fidelity thresholds are in-sample; out-of-sample validation = next natural corpus.
- Registration ratio is producer-declared (audited fail-closed, not re-derived); density can be
  gamed by subdivision — these gates catch degenerate output, not adversarial producers.
- Metric-scale sanity still needs an external anchor (COLMAP is scale-free).
- No prevalence number and no vision-policy eval delta (externally blocked, as before).
