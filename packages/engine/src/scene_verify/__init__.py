"""Embodiment-agnostic scene verifier — USD-scene evidence in, verdict out.

The engine has no benchmark identity. Consumers build scene evidence with their own
adapters (e.g. PackingBench's ``scripts/tools/verify_scene_bundle.py``, a SceneForge QA
worker) and read the generic ``scene_verify/1`` verdict. Consumer-specific projections
live in that consumer's code, never here.
"""

from scene_verify.core import (
    SCHEMA_VERSION,
    VERIFIER_VERSION,
    Bucket,
    CapturedObjectEvidence,
    CapturedPairOverlap,
    CapturedSceneEvidence,
    GateResult,
    GateStatus,
    SceneVerifyReport,
    VerifyThresholds,
    default_thresholds_path,
    dump_report,
    evaluate_mesh_agreement_gate,
    evaluate_scene_verify,
    load_verify_thresholds,
    scene_verify_out_dir,
    worst_status,
)

__all__ = [
    "SCHEMA_VERSION",
    "VERIFIER_VERSION",
    "Bucket",
    "CapturedObjectEvidence",
    "CapturedPairOverlap",
    "CapturedSceneEvidence",
    "GateResult",
    "GateStatus",
    "SceneVerifyReport",
    "VerifyThresholds",
    "default_thresholds_path",
    "dump_report",
    "evaluate_mesh_agreement_gate",
    "evaluate_scene_verify",
    "load_verify_thresholds",
    "scene_verify_out_dir",
    "worst_status",
]
