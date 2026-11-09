# scene-verify-0001: The verifier moves from RoboEval as a contract and an engine released under one tag

- **Status:** Accepted; amended 2026-11-05 (the validator's rules) and 2026-11-08
  (`usd_sha256` required, the repository to become public)
- **Date:** 2026-10-17
- **Scope:** What moves from RoboEval into this repository, how it is packaged, versioned and
  pinned, how its history moves, and how the repository is set up and receives changes

## Context

SceneForge ADR sceneforge-0009 (2026-10-13) puts the scene verifier in its own Cybernetic-EAI
repository as one versioned package with two parts: the `scene_verify/1` contract (the verdict
schema and its validation, with no Isaac dependency) and the engine (the geometry and Isaac Sim
checks that produce a verdict). SceneForge's API pins the contract only; SceneForge's verify stage
worker (SceneForge #28 and #78) and RoboEval's PackingBench pin the engine. SceneForge issue #87
asks for the repository, the move of RoboEval's verifier work with its history where practical,
the two parts released at a version, and both consumers pinned.

The verifier exists only on RoboEval's unmerged `feat/scene-verify-fidelity` branch: 26 commits
by Neil Tripathi from 2026-06-22 to 2026-07-06, ending at ffda3a96, built on RoboEval `dev`
(merge base 3a9a3146, 2026-06-08) and 317 commits behind it on 2026-10-17. On that branch:

- `app/scene_verify/` is self-contained: `core.py` and `bundle.py` import only the standard
  library (PyYAML inside one function), `geometry.py` imports numpy and trimesh and `pxr` inside
  functions, and `defects.py` imports `pxr` inside functions. `core.py` holds both the verdict
  schema (`SCHEMA_VERSION = "scene_verify/1"`, `SceneVerifyReport.to_verdict_json()`) and the
  grading logic; no validator for a received verdict exists.
- The generic Isaac Sim runner `scripts/tools/verify_usd_bundle.py` imports
  `capture_scene_evidence` from the PackingBench-bound `scripts/tools/verify_scene_bundle.py`,
  which imports `aabb_overlap_xyz` from PackingBench's `runtime_contact.py` and pose helpers from
  RoboEval's `app/scene/object_physics.py`. The runners target Isaac Sim 5.1
  (`isaacsim==5.1.0.0` in RoboEval's worker requirements).
- There is no `pyproject.toml`; the code runs as part of RoboEval's backend app. The tests mock
  Isaac Sim modules and use a real `pxr`; no test needs a GPU. The branch also carries corpus
  outputs under `artifacts/`, one of them a 9.3 MB USD file.

SceneForge's API reads `scene_verify/1` verdicts with its own hand-written checks
(`_build_scene_verify_check`) and carries no copy of the schema. No `Cybernetic-EAI/scene-verify`
repository existed before 2026-10-17.

## Decision

The maintainer ruled six questions through the question prompt on 2026-10-17, between about
13:35 and 14:00 local time (UTC+4), each as recommended, and asked for the repository to
be created and the code moved.

1. **The repository is `Cybernetic-EAI/scene-verify` (Q1).** The repository, the engine's
   distribution and its import package share the contract's name.
   The repository moved with the organization to `Kinevera/scene-verify` by 2026-11-02 (the old
   URL redirects); the name is unchanged.
2. **It is private (Q2).** A consumer that pins it (SceneForge's CI and images, RoboEval) needs a
   read credential, such as a read-only deploy key or a fine-grained token stored as that
   consumer's repository secret, each added with the maintainer's approval when the pin lands.
   Until SceneForge pins the contract, its own checks stand in for it (sceneforge-0009).
3. **The engine and the generic runner move; PackingBench's code stays (Q3).** This repository
   takes `app/scene_verify/` (core, bundle, defects, geometry, `thresholds.yaml`), the generic
   runner `verify_usd_bundle.py` with `capture_scene_evidence` moved into the engine, the RoboEval
   helpers they import copied in as engine code (`aabb_overlap_xyz`, and the pose read and
   dynamic-physics setup from `object_physics.py`), the verifier's own tests with small fixtures,
   and the `scene_verify` docs. RoboEval keeps PackingBench's adapter and scene builder, the
   PackingBench-bound runner, the corpus scripts and `artifacts/`. The engine imports nothing
   from RoboEval.
4. **Two distributions in one uv workspace, released under one tag (Q4).**
   `scene-verify-contract` (import `scene_verify_contract`) holds the `scene_verify/1` verdict
   types and constants extracted from `core.py` and a validator for a received verdict, new code
   written for the contract (its rules are in the amendment below), with no dependency outside
   the standard library. `scene-verify` (import `scene_verify`) is the engine: it depends on the
   contract at the same version and on numpy, trimesh and PyYAML, and takes `pxr` and `isaacsim`
   from the runtime it runs in. Both require Python 3.11 or later. Both ship under one annotated
   tag with a GitHub release, the first being v0.3.0, and the engine's `VERIFIER_VERSION` follows
   the tag. A consumer pins the tag as a git dependency with a subdirectory, so SceneForge's lock
   holds the contract only.
5. **One import commit with provenance (Q5).** The first commit of the moved code holds the files
   as they stand at RoboEval ffda3a96, at their RoboEval paths. It names the source repository,
   branch and SHA, lists each file's source path, and credits Neil Tripathi as co-author. The
   restructuring follows as separate commits, so a diff shows every change from RoboEval's code.
   The branch's 26 commits stay in RoboEval as the full history.
6. **The org standard, with the code landing by a reviewed PR (Q6).** Default branch `dev`,
   merge commits only, head branches deleted on merge. A one-file README commit seeded `main`
   and `dev`, the only direct push. Everything else arrives as a topic-branch PR into `dev`:
   `AGENTS.md` and a `CLAUDE.md` pointer, the import and restructuring commits, `make` targets,
   CI, the commit-message and pre-push hooks with `scripts/setup-dev.sh`, and this record. It gets
   one review round (primary, blind peer, final diff) and merges on the maintainer's approval
   naming the PR; a promotion PR then takes `dev` to `main`, where v0.3.0 is tagged.
7. **The engine declares scipy and keeps trimesh below 5 (Q7, ruled at about 15:15 local, as
   recommended).** trimesh needs scipy to build the convex-hull collision proxy and to repair
   winding; without it the proxy silently falls back to the visual mesh, so a convexHull asset
   can pass when it should fail. The engine therefore declares `scipy>=1.10` (Isaac Sim 5.1
   bundles 1.15.3). The verifier's numbers were evidenced on trimesh 4.5 and 4.12 only, so the
   engine requires `trimesh>=4.5,<5`; lifting the cap needs a run that shows the verdicts
   unchanged.

Adopted as detail, not asked: the runner moves as it is, written against Isaac Sim 5.1 and not
run on 6.2. SceneForge's sceneforge-0021 (item 2) requires the engine to be checked on Isaac Sim
6.2 under SceneForge #87 or #28 before it runs there; that check needs SceneForge's Isaac Sim
worker image (#78), so it falls to #28.

### Amendment (2026-11-05): the validator's rules

The validator's rules are part of the contract (`AGENTS.md`, binding rule 2), and the record
above named the validator without them. On 2026-11-05 the maintainer ruled, as recommended, to
record the validator's rules as built. `parse_verdict` in `scene_verify_contract` accepts a
verdict only when all of the following hold, and otherwise raises `VerdictError` naming the
first field that breaks one by its path, such as `verdict.gates[2].score`:

1. The verdict is a JSON object. Keys the contract does not define are ignored.
2. `schema_version` is present and is the string `scene_verify/1` or a string that starts with
   `scene_verify/1.`; any other major, such as `scene_verify/2`, is refused.
3. `scene_id`, `verified_at` and `verifier_version` are present and are non-empty strings.
4. `verified_at` parses with Python's `datetime.fromisoformat`. That accepts more than a full
   timestamp: a date alone (`2026-11-05`), a date and time without a UTC offset, and the basic format
   without separators (`20261105`) all pass.
5. `overall_status` is present and is one of `pass`, `warn` or `fail`.
6. `gates` is present and is a non-empty list. Each gate is a JSON object with a `gate` name that
   is a non-empty string, a `status` from `pass`, `warn` or `fail`, a `score`, a `bucket` from the
   closed set (`load`, `mesh_disagreement`, `interpenetration`, `physics_instability`,
   `fall_through`, `missing_static_metadata`, `labeling`, `reconstruction_fidelity`), and a
   `detail` that is a JSON object. All five keys are required.
7. A gate's `score` is null or a number that is not a boolean and is finite as a float: NaN,
   infinity, and an integer too large to convert to a float are refused. An integer score is
   read as a float. No other range is checked.
8. No two gates share a name.
9. `overall_status` equals the most severe gate status, in the order `pass`, `warn`, `fail`.
10. `bucket_attribution` is present, is a JSON object whose keys are buckets from the closed set
    and whose values are lists of non-empty strings, and equals exactly the attribution the
    gates imply: every gate whose status is not `pass`, listed under its own bucket in gate
    order, with no other bucket and no other name.
11. `usd_sha256` is optional. When the key is present, its value is a string of exactly 64
    lowercase hex characters; null, an empty string, uppercase hex or surrounding whitespace is
    refused.

SceneForge's current `scene_verify` gate (in its scene release service) is looser than these
rules. It treats a null or blank `usd_sha256` as absent, strips and lowercases the value before
comparing it, and checks neither that `overall_status` agrees with the gates nor the gates'
buckets and `bucket_attribution`. When SceneForge adopts `parse_verdict` (SceneForge #28), it
will therefore refuse some verdicts its gate passes today; the change is in the fail-closed
direction. Verdicts the engine writes are unaffected: it writes `usd_sha256` as a lowercase hex
digest and omits the key when it has no stage digest.

### Amendment (2026-11-08): `usd_sha256` is required, and the repository is to become public

On 2026-11-08 the maintainer ruled, for SceneForge #28, that every verdict names the stage it
graded, and that this repository becomes public.

1. **`usd_sha256` is required (replaces rule 11 above).** `parse_verdict` refuses a verdict
   without `usd_sha256` (`verdict is missing 'usd_sha256'`). Its value is a string of exactly
   64 lowercase hex characters, the SHA-256 of the exact file bytes the verifier opened; null,
   an empty string, uppercase hex, non-hex characters, any other length or surrounding
   whitespace is refused. The typed `Verdict.usd_sha256` is a `str` and no longer defaults to
   `None`.
2. **The engine always writes it and hashes the bytes it opens.** The runner
   (`scene_verify.runners.usd_bundle`) hashes the USD file before it opens the stage, hashes it
   again once grading is done, and raises without writing a verdict, evidence or sidecar when
   the two differ. `SceneVerifyReport.to_verdict_json()`, and so `dump_report`, raises
   `ValueError` for a report that has no `usd_sha256`, so the engine never writes a verdict the
   contract refuses.
3. **The schema stays `scene_verify/1`.** The accepted-major rule (rule 2) protects readers: a
   reader of `scene_verify/1` must be able to read every `scene_verify/1` verdict. Requiring a
   field that was already defined, with the same meaning and format, keeps that promise: every
   0.3.0 reader accepts every 0.4.0 verdict. What the change refuses is a producer's verdict that
   omits the key, and the only producer, this engine's runner, has written it on every verdict
   since the move. No record here defines a major as a stricter validator, and a
   `scene_verify/2` would make every 0.3.0 reader, SceneForge's included, refuse verdicts it
   reads correctly today. The change is in the fail-closed direction, as the amendment of
   2026-11-05 described for SceneForge's adoption of `parse_verdict`. A change that alters an
   existing field's meaning or format, or removes one, still needs a new major.
4. **Version 0.4.0.** Both distributions and `VERIFIER_VERSION` move to 0.4.0, a minor bump:
   the engine's public `to_verdict_json()` now raises where it omitted a key, and the contract
   refuses verdicts it accepted. The engine pins `scene-verify-contract==0.4.0`. The change is
   listed in `CHANGELOG.md`, which holds the release notes the GitHub release copies.
5. **The repository is to become public (reverses Q2).** The visibility change is a settings
   change the maintainer makes; until it is made, installing still needs a read credential.
   Once it is public, a consumer installs both distributions from git by tag with a
   subdirectory and no credential, as `README.md` shows, and the Q2 consequence that every
   consumer's CI and image builds need a read credential falls away. The engine's exact pin
   `scene-verify-contract==0.4.0` names no source, and no such distribution is on a package
   index, but a package of that name published there later could satisfy it; a consumer names
   the contract's git URL beside the engine's, so the resolver takes the contract from this
   repository.

## Consequences

- SceneForge and RoboEval adopt a verifier change by moving their pin; a change to the verdict
  shape or to the validator's rules is a contract change that SceneForge sees as a version bump
  in its lock.
- Pinning needs a read credential in every consumer's CI and image builds while the repository
  is private; the amendment of 2026-11-08 makes it public, which removes the need.
- RoboEval's branch keeps its own copy until RoboEval pins the engine and keeps only its adapter
  (SceneForge #87's third item); until then the two copies can drift.
- The copied RoboEval helpers are now maintained here, apart from RoboEval's originals.
- The validator is new code: before this repository, nothing validated a verdict on receipt
  except SceneForge's own checks, which stay in SceneForge whatever the validator does
  (sceneforge-0009).
- The engine's runner is unproven on Isaac Sim 6.2, the version SceneForge's worker image runs
  (sceneforge-0021).
- A new repository brings its own CI, hooks and review: the same workflow as SceneForge, applied
  to a small codebase.

## Alternatives considered

- **Name it `scene-verifier` or `SceneVerify`:** names the thing rather than the contract, or
  matches the product repositories' casing; either splits the repository name from the import
  package.
- **Public:** pins need no credential, but the verifier's code, thresholds and fixtures would be
  published, and turning it private later breaks every pin. **Private now, contract public
  later:** defers the credential question at the cost of a likely second move.
- **Move the library only:** smaller, but the engine would have no Isaac Sim runner and #28 would
  write one. **Move everything on the branch:** the engine would import PackingBench code and the
  repository would carry the corpus outputs.
- **One distribution with an `[engine]` extra:** one thing to release, but SceneForge's lock
  would carry the engine's code. **Wheels attached to releases:** byte-exact pins, but a release
  job to build and maintain now, and a private repository's asset URLs still need a credential.
- **Filtered history with git-filter-repo:** keeps blame and authorship, at the cost of more
  steps and early commits under PackingBench-era paths, with three of the 26 commits also
  touching PackingBench files.
- **Minimal now, standard later:** a pinnable tag sooner, but an unreviewed first release.
  **Tag from `dev`:** one PR fewer before the first pin, with the release tag on the integration
  branch.

## Revisit trigger

- A consumer cannot obtain a read credential for a private repository, which reopens Q2.
- RoboEval pins the engine and removes its copy, or decides not to.
- The runner fails on Isaac Sim 6.2 in SceneForge #28.
- A third consumer needs the engine without numpy, trimesh or PyYAML.
- A producer needs to write a verdict for a scene that is not one USD file, so it has no single
  file to hash, which reopens the amendment of 2026-11-08 (item 1).
