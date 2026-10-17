# scene-verify

The scene verifier for Cybernetic simulator scenes. It holds two parts, released together under
one version:

- the `scene_verify/1` contract: the verdict schema and its validation, with no Isaac Sim,
  geometry or USD dependency;
- the engine: the geometry and Isaac Sim checks that grade a scene and produce a verdict.

SceneForge's API pins the contract only; SceneForge's verify stage worker and RoboEval's
PackingBench pin the engine (SceneForge ADR sceneforge-0009). The code moves here from RoboEval's
`feat/scene-verify-fidelity` branch under SceneForge issue #87.

Status: designed. The repository is being set up; nothing is released yet.
