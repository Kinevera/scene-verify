"""The ``scene_verify/1`` verdict: its constants, typed structures and validator.

A verdict is the JSON object the scene verifier engine writes for one scene
(``SceneVerifyReport.to_verdict_json()`` in the ``scene-verify`` distribution) and a consumer
reads, such as SceneForge's ``scene_verify`` QA gate. Its shape::

    {
      "schema_version": "scene_verify/1",
      "scene_id": "<non-empty string>",
      "overall_status": "pass" | "warn" | "fail",
      "verified_at": "<ISO 8601 timestamp>",
      "verifier_version": "<non-empty string>",
      "gates": [
        {"gate": "<name>", "status": "pass" | "warn" | "fail", "score": <number> | null,
         "bucket": "<one of BUCKETS>", "detail": {...}},
        ...
      ],
      "bucket_attribution": {"<bucket>": ["<gate name>", ...], ...},
      "usd_sha256": "<64 lowercase hex digits>"
    }

``overall_status`` is the most severe gate status, and ``bucket_attribution`` lists every gate
that did not pass under its bucket, in gate order. ``usd_sha256`` is the SHA-256 of the exact
file bytes the verifier opened; it is required since 0.4.0 (scene-verify-0001, amendment of
2026-11-08), so a verdict always names the stage it graded. A verdict that carries keys this
module does not know is still accepted. This module imports only the standard library.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, TypeGuard

#: The schema this contract describes, written into every verdict's ``schema_version``.
SCHEMA_VERSION: Final = "scene_verify/1"

#: A gate's or a verdict's status.
GateStatus = Literal["pass", "warn", "fail"]

#: Every status, ordered from least to most severe: a verdict's ``overall_status`` is the most
#: severe of its gates' statuses.
GATE_STATUSES: Final[tuple[GateStatus, ...]] = ("pass", "warn", "fail")

#: Each bucket names exactly one root cause. A gate's bucket is fixed at construction so a
#: single failure is never counted in two buckets (a missing static tag is attributed to
#: ``missing_static_metadata`` and never to ``physics_instability``, even though, left in the
#: simulator, it would also drift).
Bucket = Literal[
    "load",
    "mesh_disagreement",
    "interpenetration",
    "physics_instability",
    "fall_through",
    "missing_static_metadata",
    "labeling",
    "reconstruction_fidelity",
]

#: Every bucket a gate can be attributed to.
BUCKETS: Final[tuple[Bucket, ...]] = (
    "load",
    "mesh_disagreement",
    "interpenetration",
    "physics_instability",
    "fall_through",
    "missing_static_metadata",
    "labeling",
    "reconstruction_fidelity",
)

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_SHOWN_VALUE_MAX_LENGTH = 80


def is_accepted_schema_version(value: object) -> TypeGuard[str]:
    """Whether ``value`` names this contract's major: exactly ``scene_verify/1`` or a string
    starting ``scene_verify/1.``. Any other major (``scene_verify/2``) is not accepted."""
    return isinstance(value, str) and (
        value == SCHEMA_VERSION or value.startswith(SCHEMA_VERSION + ".")
    )


class VerdictError(ValueError):
    """Raised by :func:`parse_verdict` when a verdict breaks the contract. The message names
    the offending field by its path, for example ``verdict.gates[2].status``."""


@dataclass(frozen=True)
class GateVerdict:
    """One gate's outcome within a verdict."""

    gate: str
    status: GateStatus
    score: float | None
    bucket: Bucket
    detail: Mapping[str, Any]


@dataclass(frozen=True)
class Verdict:
    """A validated ``scene_verify/1`` verdict."""

    schema_version: str
    scene_id: str
    overall_status: GateStatus
    verified_at: str
    verifier_version: str
    gates: tuple[GateVerdict, ...]
    bucket_attribution: Mapping[Bucket, tuple[str, ...]]
    #: sha256 hex digest of the exact USD stage bytes the verdict grades.
    usd_sha256: str


def parse_verdict(data: object) -> Verdict:
    """Validate a received verdict and return it typed.

    ``data`` is the decoded JSON object (for example ``json.loads`` of ``verdict.json``).
    Raises :class:`VerdictError` naming the first field that breaks the contract: a missing or
    ill-typed field, an unknown major in ``schema_version``, an unknown status or bucket, a
    ``verified_at`` that is not ISO 8601, a non-finite score, a repeated gate name, an
    ``overall_status`` that is not the most severe gate status, a ``bucket_attribution`` that
    does not match the gates, or a missing ``usd_sha256`` or one that is not 64 lowercase hex
    digits. Keys the contract does not define are ignored.
    """
    root = _mapping(data, "verdict")

    schema_version = _required(root, "schema_version", "verdict")
    if not is_accepted_schema_version(schema_version):
        raise VerdictError(
            f"verdict.schema_version must be {SCHEMA_VERSION!r} or start with "
            f"{SCHEMA_VERSION + '.'!r}, got {_show(schema_version)}"
        )

    scene_id = _non_empty_string(root, "scene_id", "verdict")
    overall_status = _status(_required(root, "overall_status", "verdict"), "verdict.overall_status")
    verified_at = _non_empty_string(root, "verified_at", "verdict")
    try:
        datetime.fromisoformat(verified_at)
    except ValueError:
        raise VerdictError(
            f"verdict.verified_at must be an ISO 8601 timestamp, got {_show(verified_at)}"
        ) from None
    verifier_version = _non_empty_string(root, "verifier_version", "verdict")

    raw_gates = _required(root, "gates", "verdict")
    if not isinstance(raw_gates, list | tuple):
        raise VerdictError(f"verdict.gates must be a list, got {_show(raw_gates)}")
    if not raw_gates:
        raise VerdictError("verdict.gates must list at least one gate")
    gates = tuple(_gate(raw, f"verdict.gates[{index}]") for index, raw in enumerate(raw_gates))
    seen: set[str] = set()
    for index, gate in enumerate(gates):
        if gate.gate in seen:
            raise VerdictError(f"verdict.gates[{index}].gate repeats the gate name {gate.gate!r}")
        seen.add(gate.gate)

    worst = _worst_status(gate.status for gate in gates)
    if overall_status != worst:
        raise VerdictError(
            f"verdict.overall_status is {overall_status!r} but its most severe gate status "
            f"is {worst!r}"
        )

    bucket_attribution = _bucket_attribution(
        _required(root, "bucket_attribution", "verdict"), "verdict.bucket_attribution"
    )
    expected_attribution = _attribution_from_gates(gates)
    if dict(bucket_attribution) != expected_attribution:
        raise VerdictError(
            "verdict.bucket_attribution must list each gate that did not pass under its "
            f"bucket, in gate order: expected {_show(_as_lists(expected_attribution))}, "
            f"got {_show(_as_lists(bucket_attribution))}"
        )

    usd_sha256 = _required(root, "usd_sha256", "verdict")
    if not isinstance(usd_sha256, str) or _SHA256_HEX.fullmatch(usd_sha256) is None:
        raise VerdictError(
            "verdict.usd_sha256 must be a sha256 digest of 64 lowercase hex digits, "
            f"got {_show(usd_sha256)}"
        )

    return Verdict(
        schema_version=schema_version,
        scene_id=scene_id,
        overall_status=overall_status,
        verified_at=verified_at,
        verifier_version=verifier_version,
        gates=gates,
        bucket_attribution=bucket_attribution,
        usd_sha256=usd_sha256,
    )


def _gate(data: object, where: str) -> GateVerdict:
    gate = _mapping(data, where)
    name = _non_empty_string(gate, "gate", where)
    status = _status(_required(gate, "status", where), f"{where}.status")
    score = _required(gate, "score", where)
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise _score_error(score, where)
        try:
            # A JSON integer too large for a float raises OverflowError here.
            as_float = float(score)
        except OverflowError:
            raise _score_error(score, where) from None
        if not math.isfinite(as_float):
            raise _score_error(score, where)
        score = as_float
    bucket = _bucket(_required(gate, "bucket", where), f"{where}.bucket")
    detail = _mapping(_required(gate, "detail", where), f"{where}.detail")
    return GateVerdict(gate=name, status=status, score=score, bucket=bucket, detail=dict(detail))


def _score_error(score: object, where: str) -> VerdictError:
    return VerdictError(f"{where}.score must be a finite number or null, got {_show(score)}")


def _bucket_attribution(data: object, where: str) -> dict[Bucket, tuple[str, ...]]:
    attribution: dict[Bucket, tuple[str, ...]] = {}
    for key, value in _mapping(data, where).items():
        bucket = _bucket(key, f"{where} key")
        if not isinstance(value, list | tuple) or not all(
            isinstance(name, str) and name for name in value
        ):
            raise VerdictError(f"{where}[{key!r}] must be a list of gate names, got {_show(value)}")
        attribution[bucket] = tuple(value)
    return attribution


def _attribution_from_gates(gates: tuple[GateVerdict, ...]) -> dict[Bucket, tuple[str, ...]]:
    attribution: dict[Bucket, tuple[str, ...]] = {}
    for gate in gates:
        if gate.status != "pass":
            attribution[gate.bucket] = (*attribution.get(gate.bucket, ()), gate.gate)
    return attribution


def _worst_status(statuses: Iterable[GateStatus]) -> GateStatus:
    worst: GateStatus = "pass"
    for status in statuses:
        if GATE_STATUSES.index(status) > GATE_STATUSES.index(worst):
            worst = status
    return worst


def _status(value: object, where: str) -> GateStatus:
    for status in GATE_STATUSES:
        if isinstance(value, str) and value == status:
            return status
    raise VerdictError(f"{where} must be one of {', '.join(GATE_STATUSES)}, got {_show(value)}")


def _bucket(value: object, where: str) -> Bucket:
    for bucket in BUCKETS:
        if isinstance(value, str) and value == bucket:
            return bucket
    raise VerdictError(f"{where} must be one of {', '.join(BUCKETS)}, got {_show(value)}")


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VerdictError(f"{where} must be a JSON object, got {_show(value)}")
    return value


def _required(mapping: Mapping[str, Any], key: str, where: str) -> object:
    if key not in mapping:
        raise VerdictError(f"{where} is missing {key!r}")
    return mapping[key]


def _non_empty_string(mapping: Mapping[str, Any], key: str, where: str) -> str:
    value = _required(mapping, key, where)
    if not isinstance(value, str) or not value:
        raise VerdictError(f"{where}.{key} must be a non-empty string, got {_show(value)}")
    return value


def _as_lists(attribution: Mapping[Bucket, tuple[str, ...]]) -> dict[str, list[str]]:
    return {bucket: list(names) for bucket, names in attribution.items()}


def _show(value: object) -> str:
    shown = repr(value)
    if len(shown) > _SHOWN_VALUE_MAX_LENGTH:
        shown = shown[: _SHOWN_VALUE_MAX_LENGTH - 3] + "..."
    return shown
