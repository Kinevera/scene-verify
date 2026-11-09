# scene-verify

Physics checks for simulator scenes. scene-verify opens a USD scene in NVIDIA Isaac Sim, runs a
set of checks on it, and writes a **verdict**: `pass`, `warn` or `fail`. The verdict names each
check's result and the SHA-256 of the exact file it graded.

Cybernetic uses it to check every scene its SceneForge pipeline reconstructs from captures before
that scene is approved for robot simulation and evaluation.

## The checks

| Check | What it asks |
| --- | --- |
| `scene_load` | Does the stage open, and do the declared objects exist? |
| `visual_collision_agreement` | Do the visual mesh and the collision mesh match? |
| `interpenetration` | Do objects overlap at the start and after settling? |
| `static_settle` | Does the scene stay still when physics runs (60 steps by default)? |
| `fall_through` | Does anything fall through the support surface? |
| `static_metadata_present` | Are the objects that should be static tagged as static? |
| `recon_registration_coverage` | For a reconstruction: were enough capture frames used? |
| `recon_surface_density` | For a reconstruction: does the surface have enough detail? |

The last two run only when the input declares the scene a reconstruction. Each check's limits
are in `packages/engine/src/scene_verify/thresholds.yaml`, and `--thresholds` overrides them.
The overall verdict is the worst result of any check.

## Two packages, one version

- **Contract** (`packages/contract`, distribution `scene-verify-contract`, import
  `scene_verify_contract`): the `scene_verify/1` verdict format and `parse_verdict`, which
  validates a verdict and raises `VerdictError` naming the bad field. It uses the standard
  library only, so a service that only reads verdicts installs this part alone.
- **Engine** (`packages/engine`, distribution `scene-verify`, import `scene_verify`): the
  checks and the runner. It needs numpy, scipy, trimesh (below 5) and PyYAML. `pxr`, `isaacsim`,
  `omni` and `carb` come from Isaac Sim.

## Status

Version **0.4.0** is tagged; **0.4.1**, which bounds the memory of the mesh-distance query, is
built and not yet tagged. Since 0.4.0 every verdict must carry `usd_sha256`, the SHA-256 of
the exact file the verifier opened (`CHANGELOG.md`).

Built for Isaac Sim 5.1. On 2026-11-08 it also ran on Isaac Sim 6.2.0, in NVIDIA's NGC
container, against a real reconstructed scene; the verdict was `warn`, from
`visual_collision_agreement`. The test suite runs without Isaac Sim, which it stubs.

## Install

Python 3.11 or later. Both packages install from this repository by tag:

```
pip install \
  "scene-verify-contract @ git+https://github.com/Kinevera/scene-verify@v0.4.1#subdirectory=packages/contract" \
  "scene-verify @ git+https://github.com/Kinevera/scene-verify@v0.4.1#subdirectory=packages/engine"
```

Name both packages. The engine pins `scene-verify-contract==0.4.1`, and no package index
carries it, so a bare pin could resolve to someone else's package.

Isaac Sim 6.2 already ships numpy, scipy, trimesh and PyYAML, so inside its Python add
`--no-deps`:

```
/isaac-sim/python.sh -m pip install --no-deps \
  "scene-verify-contract @ git+https://github.com/Kinevera/scene-verify@v0.4.1#subdirectory=packages/contract" \
  "scene-verify @ git+https://github.com/Kinevera/scene-verify@v0.4.1#subdirectory=packages/engine"
```

## Run

Describe the scene in a bundle file:

```json
{
  "scene_id": "kitchen-001",
  "usd_stage_path": "/data/scene.usdz",
  "objects": [
    {"object_id": "static_shell", "prim_path": "/World/StaticShell", "is_static_expected": true}
  ],
  "support_prim_path": "/World/StaticShell"
}
```

Then run it with Isaac Sim's Python:

```
<isaac-sim>/python.sh -m scene_verify.runners.usd_bundle \
    --bundle scene_bundle.json --artifacts-dir artifacts
```

The runner writes `verdict.json` and `evidence.json` under
`artifacts/scene_verify/<scene_id>/`. It exits 0 on pass or warn, 2 on fail and 1 on error.
Isaac Sim's `python.sh` turns every non-zero exit into 1, so read `verdict.json` for the result.
The full bundle format is in `packages/engine/src/scene_verify/bundle.py`.

## Read a verdict

```python
import json
from scene_verify_contract import VerdictError, parse_verdict

verdict = parse_verdict(json.loads(text))  # raises VerdictError on a malformed verdict
print(verdict.overall_status, verdict.usd_sha256)
```

## Develop

```
scripts/setup-dev.sh          # git hooks and .venv from uv.lock
make check                    # ruff, format, mypy, lock check
make test                     # pytest; no GPU or Isaac Sim needed
```

`AGENTS.md` holds the contribution workflow, and `docs/adr/` holds the design decisions.
`docs/history/` keeps older design and measurement notes from before the code moved here.

## License

No license has been chosen yet. Until one is added, all rights are reserved.
