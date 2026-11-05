"""The ``scene_verify/1`` verdict contract, with no dependency outside the standard library.

A consumer that reads verdicts (SceneForge's API) pins this distribution alone; the engine
(``scene_verify``) takes its schema version, statuses and buckets from here, so the contract
has one source of truth (scene-verify-0001).
"""

from scene_verify_contract.verdict import (
    BUCKETS,
    GATE_STATUSES,
    SCHEMA_VERSION,
    Bucket,
    GateStatus,
    GateVerdict,
    Verdict,
    VerdictError,
    is_accepted_schema_version,
    parse_verdict,
)

__all__ = [
    "BUCKETS",
    "GATE_STATUSES",
    "SCHEMA_VERSION",
    "Bucket",
    "GateStatus",
    "GateVerdict",
    "Verdict",
    "VerdictError",
    "is_accepted_schema_version",
    "parse_verdict",
]
