# scene-verify

The scene verifier for Cybernetic simulator scenes. It holds two parts, released together under
one version:

- **The contract**, `packages/contract`: distribution `scene-verify-contract`, import
  `scene_verify_contract`. The `scene_verify/1` verdict: its schema version and accepted-major
  rule, gate statuses, buckets and typed structures, and `parse_verdict`, which validates a
  received verdict and raises `VerdictError` naming the offending field. Standard library only.
- **The engine**, `packages/engine`: distribution `scene-verify`, import `scene_verify`. The
  geometry and Isaac Sim checks that grade a USD scene and write a verdict, and the generic runner
  `scene_verify.runners.usd_bundle`. It depends on the contract at the same version and on numpy,
  trimesh and PyYAML; `pxr`, `isaacsim`, `omni` and `carb` come from the Isaac Sim runtime.

SceneForge's API pins the contract only; SceneForge's verify stage worker and RoboEval's
PackingBench pin the engine (scene-verify-0001, SceneForge sceneforge-0009). The code moved here
from RoboEval's `feat/scene-verify-fidelity` branch at ffda3a96 under SceneForge issue #87;
`docs/history/` keeps that branch's design and measurement notes, which name RoboEval's paths.

## Status

Built, not released: no tag exists yet, and the first release is to be v0.3.0. The tests run
without Isaac Sim (they stub it). The runner moved unchanged from its Isaac Sim 5.1 form and has
not run on Isaac Sim 6.2.

## Install by tag

Both parts require Python 3.11 or later. The repository is private, so installing needs a read
credential for it, such as a read-only deploy key or a fine-grained token.

The contract alone:

```
scene-verify-contract @ git+https://github.com/Cybernetic-EAI/scene-verify@v0.3.0#subdirectory=packages/contract
```

The engine requires `scene-verify-contract==0.3.0`, which is on no package index, so name both:

```
scene-verify-contract @ git+https://github.com/Cybernetic-EAI/scene-verify@v0.3.0#subdirectory=packages/contract
scene-verify @ git+https://github.com/Cybernetic-EAI/scene-verify@v0.3.0#subdirectory=packages/engine
```

Validate a verdict with the contract:

```python
from scene_verify_contract import VerdictError, parse_verdict

verdict = parse_verdict(json.loads(text))  # raises VerdictError on a malformed verdict
```

## Run the runner under Isaac Sim's Python

Install the two requirements above into Isaac Sim's Python, then:

```
<isaac-sim>/python.sh -m scene_verify.runners.usd_bundle \
    --bundle scene_bundle.json --artifacts-dir artifacts --emit-sidecar
```

The bundle is a `SceneBundle` JSON (`scene_verify/bundle.py`): the USD stage, the prims to grade
and the support prim. The run writes `verdict.json` and `evidence.json` under
`<artifacts-dir>/scene_verify/<scene_id>/`, and `--emit-sidecar` also writes `scene_verify.json`
beside the USD. A relative path resolves against the working directory. `--thresholds` and
`--settle-steps` override the shipped thresholds. It exits 0 on pass or warn, 2 on fail and 1 on
error, and prints `SCENE_VERIFY_RESULT scene_id=<id> overall_status=<status>`, which a caller
should read instead of the exit code where Isaac Sim's `python.sh` collapses non-zero codes to 1.

## Develop

```
scripts/setup-dev.sh          # git hooks and .venv from uv.lock (uv fetches Python 3.12)
scripts/setup-dev.sh --check  # verify the setup without changing anything
make check                    # ruff check, ruff format --check, mypy, uv lock --check
make test                     # pytest; no GPU or Isaac Sim (pxr is usd-core)
make hooks-check              # the git hook battery
```

`AGENTS.md` holds the workflow; `docs/adr/` holds the decisions.
