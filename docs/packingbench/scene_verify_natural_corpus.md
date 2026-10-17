# Artifact QA is insufficient: what geometry/physics verification catches that the benchmark scorer cannot

*Scene-verify results on a natural reconstruction corpus (in-the-wild video → COLMAP/MVS → USD),
plus the live approval-flow demonstration. All numbers in this note are from executed runs on
this box; nothing is extrapolated.*

## TL;DR (deliberately conservative)

- We reconstructed warehouse/industrial scenes from in-the-wild YouTube walkthrough footage
  through the real pipeline (COLMAP SfM + dense MVS + Poisson + USD packaging) and graded them
  live in Isaac with `scene_verify`. The same natural scene packaged *naively* (no collider, no
  static tag) **fails** — the verifier catches it with a 5.16 m free-fall signature.
- **v0.1 result (physics gates only): 7 attempts → 6 packaged scenes graded, all pass + 1
  reconstruction failure caught upstream.** That all-pass row set exposed the fidelity boundary:
  a degenerate 109-face shell is physically self-consistent and passed every physics gate.
- **v0.2 result (fidelity gates added): the same 6 scenes re-graded live → 2 pass, 1 warn,
  3 fail.** The 109-face shell now fails both fidelity gates (registration 10/90, 109 faces);
  the substantial reconstructions (171k / 1.5M faces) still pass. Fidelity gates apply only to
  scenes that declare reconstruction provenance — curated benchmark verdicts are unchanged
  (locked by test).
- The SceneForge approval gate was demonstrated live on these exact verdicts — pinned to
  `scene_verify/1`, it consumes v0.2 verdicts unchanged: **pass → approved; fidelity-fail →
  HTTP 409 naming `recon_registration_coverage, recon_surface_density`; missing verdict → 409;
  stale hash → 409.**
- The scorer-blindness result stands: the benchmark's PCS scorer provably has no collision-geometry
  input (falsifiable CI lock), so none of these defect classes are catchable downstream of scoring.
- **What this is not:** 7 scenes is a pilot, not a prevalence estimate — and the fidelity
  thresholds were *calibrated on this same pilot corpus*, so its 3-fail rows demonstrate the
  mechanism, not an error rate. See §3.

## 1. The gap

A scene pipeline's artifact QA answers: *are the files present, do the checksums match, are the
payloads non-placeholder?* It cannot answer: *is this scene a fair physical world to evaluate a
robot policy in?* A USD stage can be complete, checksummed, and beautifully rendered while its
collision geometry diverges centimeters from what the camera sees, or while its objects are not
in physical equilibrium at t=0.

The benchmark scorer cannot close this gap either, and we can prove it: PackingBench's PCS
scorer never reads collision geometry. That is locked as a falsifiable CI test — a final state
carrying an explicit, huge collision-divergence report scores identically to a clean one
(`tests/scene_verify/test_eval_delta_pcs.py::test_collision_divergence_field_is_ignored_by_pcs`).
A policy evaluated in a scene with phantom collision geometry is scored by physics the camera
never saw, and no number downstream of the scorer will say so.

`scene_verify` sits between those two: six physics gates (load, visual↔collision agreement,
interpenetration — graded at both the authored t=0 state and post-settle — static settle,
fall-through, static metadata), plus two reconstruction-fidelity gates for scenes that declare
reconstruction provenance (registration coverage, surface density). All graded live in Isaac Sim
on the exact USD bytes (the verdict self-declares `usd_sha256`), fail-closed on anything it
could not assess.

## 2. A natural corpus, end to end

Every prior corpus number came from curated benchmark scenes or injected defects. This is the
first *natural* corpus: warehouse/industrial scenes reconstructed from in-the-wild walkthrough
footage (YouTube, 720p, 44–90 s segments, 1 fps frames), through the real pipeline:

```
video segment → frames → COLMAP SfM (GPU SIFT, sequential matching, CPU BA)
  → dense MVS (GPU patch-match) → Poisson mesh
  → usd_from_mesh --static-collider   (CORRECT packaging)
  → verify_usd_bundle.py              (Isaac Sim 5.1, live)
```

Packaging is deliberately correct for the main rows: the question is "what do honest
reconstructions of real spaces look like to the verifier?", not "can it catch a packaging
mistake" (that discrimination is already established on the Tanks&Temples truck pair and the
injected-defect soundness matrix — and re-confirmed on this corpus below).

### Results (n = 7 attempts; provenance in `artifacts/scene_verify/natural_corpus/provenance.json`)

v0.1 physics-only grading passed all six correctly-packaged scenes. The v0.2 re-grade below adds
the two reconstruction-fidelity gates (`recon_registration_coverage`, declared SfM registration
ratio; `recon_surface_density`, face count + mesh/AABB area ratio measured live from the stage):

| scene_id | verdict | failed gate | offender | measured value | threshold |
|---|---|---|---|---|---|
| recon_wh_garage_shop_packaged | **pass** | - | - | - | - |
| recon_wh_coach_factory_packaged | **pass** | - | - | - | - |
| recon_wh_aisle_picker_packaged | **warn** | recon_registration_coverage (warn) | reconstructed_scene | registered 10/44 (0.23) | fail<0.15 warn<0.5 |
| ↳ | | recon_surface_density (warn) | reconstructed_scene | 42,315 faces, area ratio 0.0164 | fail<2000 faces, warn<50000 or ratio<0.01 |
| recon_wh_fabric_packaged | **fail** | recon_surface_density (fail) | reconstructed_scene | 443 faces, area ratio 0.0001 | fail<2000 faces, warn<50000 or ratio<0.01 |
| recon_wh_forklift_aisle_packaged | **fail** | recon_surface_density (fail) | reconstructed_scene | 1,114 faces, area ratio 0.0025 | fail<2000 faces, warn<50000 or ratio<0.01 |
| ↳ | | recon_registration_coverage (warn) | reconstructed_scene | registered 17/90 (0.19) | fail<0.15 warn<0.5 |
| recon_wh_secret_packaged | **fail** | recon_registration_coverage (fail) | reconstructed_scene | registered 10/90 (0.11) | fail<0.15 warn<0.5 |
| ↳ | | recon_surface_density (fail) | reconstructed_scene | 109 faces, area ratio 0.0007 | fail<2000 faces, warn<50000 or ratio<0.01 |
| recon_wh_garage_shop_raw_raw | **fail** | static_settle (fail) | reconstructed_scene | moved 5.156 m / 0.0° | 0.01 m / 5.0° |
| ↳ same row, co-signals | | visual_collision_agreement (warn) | reconstructed_scene | collision mesh absent | collider required |
| ↳ | | fall_through (warn) | - | - | no support plane captured |
| wh_staging_aisle | **not_graded** | (reconstruction failed) | - | SfM registered 4/55 frames; empty Poisson surface; packager refused | - |

All fidelity numbers above are from the live Isaac re-grade (face counts measured from the
stage; they match the source Poisson meshes exactly). Every physics-gate outcome is unchanged
from v0.1 — the fidelity gates are additive.

The scenes span the quality spectrum of real reconstruction: `wh_garage_shop` is a genuine dense
result (90/90 frames registered, 1,564,909 faces — it also live-exercised the mesh gate's
large-mesh guard without incident); `wh_coach_factory` is substantial (171,932 faces);
`wh_secret` registered only 10/90 frames and produced a 109-face shell. One attempt never
reached the verifier at all: mostly-static camera → 4/55 registered → degenerate surface → the
packager refused it. That row stays in the table; hiding upstream failures would overstate
coverage.

### The discrimination row

`recon_wh_garage_shop_raw_raw` is the same 1.56M-face natural mesh authored the way a naive
packager would emit it: render geometry only. Treated as a free body it free-falls 5.156 m in
the settle window (threshold 0.01 m), with the mesh gate independently warning that collision
geometry is absent and fall-through warning that no support was captured. Natural scene, real
packaging variant, three gates converging on "not physics-ready" — this is the defect class the
gate exists to stop, demonstrated on this corpus rather than on a curated fixture.

## 3. The fidelity boundary — found by v0.1, gated by v0.2

The v0.1 all-pass rows were read precisely at the time: correctly-packaged static
reconstructions are physically self-consistent worlds, and `wh_secret`'s 109-face shell passing
demonstrated that physics gates certify **physics-readiness, not reconstruction fidelity**. A
degenerate but self-consistent reconstruction is a *fidelity* failure — wrong surface coverage —
which no physics gate can see.

v0.2 closes that boundary with two gates that apply **only to scenes whose bundle declares
reconstruction provenance** (a curated benchmark asset is legitimately low-poly; grading its
density would be meaningless — curated verdicts are byte-identical, locked by test):

- **`recon_surface_density`** — measured live from the stage, never trusted from the producer:
  absolute face count plus mesh-area/AABB-surface-area ratio. Both are scale-invariant, which
  matters because COLMAP output has arbitrary units — nothing in these gates may be denominated
  in metres.
- **`recon_registration_coverage`** — the declared SfM registration ratio (the verifier cannot
  re-run SfM; the gate records `basis: declared_by_producer` and warns fail-closed when the
  declaration is absent).

Honest framing of the 2-pass/1-warn/3-fail re-grade: thresholds were **calibrated on this same
pilot corpus** (the separations were wide — 109/443/1,114 faces vs. 42k/171k/1.5M; 0.11–0.23
registration vs. 0.52–1.0), so these rows demonstrate the mechanism end-to-end, not an error
rate. The out-of-sample test is the next natural corpus. Metric-scale sanity remains future
work (COLMAP is scale-free; it needs an external anchor).

**A methodological note:** with single-mesh packaging (one mesh serving as both visual and
collider), `visual_collision_agreement` is trivially satisfiable and short-circuits at the
AABB pre-pass. The gate discriminates when colliders are separately authored or simplified —
which is exactly the external-defect fixture class (oversize hull ×1.5 → fail at 32× the line)
and the PackingBench corpus class (book_brick phantom 0.017 m → fail). On this corpus it acted
as a *presence* check (and correctly warned on the raw row).

## 4. The approval flow, demonstrated live

The SceneForge gate consumes these verdicts. `scripts/demo_scene_verify_gate.py` (SceneForge
repo) drives the real FastAPI service through the release lifecycle four times — using the
natural verdicts above, not hand-written JSON. The v0.1 run
(`artifacts/scene_verify/natural_corpus/approval_flow_demo.txt`) used the garage pass/fail
pair; the v0.2 run (`approval_flow_demo_v2.txt`) additionally proves two things live: the gate
(pinned to `scene_verify/1`) consumes v0.2 verdicts unchanged, and a **fidelity** failure — a
scene that is physically sound but degenerately reconstructed — blocks approval:

```
[1] PASS  (recon_wh_garage_shop_packaged)   qa/validate pass -> qa-pass 200 -> approve 200 'approved'
[2] FAIL  (recon_wh_secret_packaged)        qa-pass 409: 'scene_verify verdict is fail
                                            (failing gates: recon_registration_coverage, recon_surface_density)'
[3] MISSING (no qa_report artifact)         qa-pass 409: 'Missing qa_report artifact'
[4] STALE (usd_sha256 != packaged USD)      qa-pass 409: 'verdict was produced for different USD bytes ... must be re-verified'
```

The stale-hash case is the one artifact QA fundamentally cannot express: every file present,
every checksum self-consistent — the verdict is simply *about different bytes* than the packaged
stage. Content binding (verdict `usd_sha256` ↔ packaged artifact checksum) is what makes
"verified" mean "verified *this*".

## 5. What we do NOT claim (yet)

- **No prevalence number.** Seven attempts is a pilot natural corpus, not an estimate of how many
  approved SceneForge scenes are invalid. That number requires grading production reconstruction
  output at volume; the pipeline for it is now proven end to end.
- **No policy-delta on vision policies.** No vision policy on this box scores above 0.0; the
  eval-delta result is scoped to the geometric-oracle class (`scene_verify_eval_delta.md`).
- **Fidelity thresholds are in-sample.** The v0.2 gate thresholds were calibrated on this same
  pilot corpus (§3); the 3-fail re-grade demonstrates the mechanism, not an out-of-sample error
  rate. Metric-scale sanity is still future work (COLMAP output is scale-free).
- **Fidelity coverage is two signals, not a guarantee.** Registration ratio is
  producer-declared (audited fail-closed, but not re-derived), and density can be gamed by
  subdivision — these gates catch degenerate output, not adversarial producers.
- **Interpenetration is no longer live-inert — but not strictly discriminated live.** v0.1
  disclosed zero live true-positives (PhysX depenetrated authored overlaps before the only
  capture; a NaN mesh depth additionally fail-opened the comparison). v0.2 captures the
  authored t=0 state and routes non-finite depths to the AABB fallback: the injected-overlap
  soundness case now fires the gate live (`fired=['interpenetration', 'static_settle']`,
  clean stayed green — `pack_3_dense_close_i1/soundness/discrimination_matrix.json`, and live
  sensitivity is now part of the soundness bar). The settle co-trip is expected on a live
  scene; exactly-one-gate discrimination remains the controlled venv suite's property.

## 6. Reproduce

```bash
# reconstruction driver (per scene): /sdb-disk/work/natural_corpus/run_recon.sh <scene> <start> <dur>
# grade one bundle in Isaac:
/opt/isaac-sim/python.sh scripts/tools/verify_usd_bundle.py \
    --bundle /sdb-disk/work/natural_corpus/<scene>/bundle.json --emit-sidecar
# results table:
venv/bin/python scripts/tools/natural_corpus_table.py --scene-glob 'recon_wh_*' \
    --recon-failed "wh_staging_aisle:SfM registered 4/55 frames; ..."
# approval-flow demo (SceneForge repo):
TEST_DATABASE_URL=... venv/bin/python scripts/demo_scene_verify_gate.py \
    --pass-verdict .../recon_wh_garage_shop_packaged/verdict.json \
    --fail-verdict .../recon_wh_garage_shop_raw_raw/verdict.json
```

Committed evidence: verdicts under `artifacts/scene_verify/recon_wh_*/`, table + provenance +
demo transcript under `artifacts/scene_verify/natural_corpus/`.
