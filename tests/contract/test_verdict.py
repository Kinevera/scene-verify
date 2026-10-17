"""The scene_verify/1 validator: what it accepts, and each way it rejects a verdict.

These tests use hand-written verdicts only, so they need nothing beyond the contract. The
engine side (every verdict the engine emits passes ``parse_verdict``) is locked in
tests/engine/test_verdict_contract.py.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable
from typing import Any, get_args

import pytest

from scene_verify_contract import (
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

USD_SHA256 = "0" * 63 + "a"


def _gate(name: str, status: str = "pass", bucket: str = "load", score: Any = 0.0) -> dict:
    return {"gate": name, "status": status, "score": score, "bucket": bucket, "detail": {}}


def _verdict(**overrides: Any) -> dict[str, Any]:
    """A fail verdict shaped exactly as the engine writes one."""
    verdict: dict[str, Any] = {
        "schema_version": "scene_verify/1",
        "scene_id": "scene_a",
        "overall_status": "fail",
        "verified_at": "2026-10-17T10:00:00+00:00",
        "verifier_version": "0.3.0",
        "gates": [
            _gate("scene_load"),
            _gate("visual_collision_agreement", "warn", "labeling", None),
            _gate("interpenetration", "fail", "interpenetration", 1.0),
            _gate("static_settle", "pass", "physics_instability", 0.1),
        ],
        "bucket_attribution": {
            "labeling": ["visual_collision_agreement"],
            "interpenetration": ["interpenetration"],
        },
        "usd_sha256": USD_SHA256,
    }
    verdict.update(overrides)
    return verdict


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_constants_match_their_literal_types():
    assert SCHEMA_VERSION == "scene_verify/1"
    assert GATE_STATUSES == ("pass", "warn", "fail")
    assert GATE_STATUSES == get_args(GateStatus)
    assert BUCKETS == get_args(Bucket)
    assert len(set(BUCKETS)) == len(BUCKETS) == 8


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("scene_verify/1", True),
        ("scene_verify/1.0", True),
        ("scene_verify/1.7", True),
        ("scene_verify/2", False),
        ("scene_verify/10", False),
        ("scene_verify/1x", False),
        ("scene_verify/", False),
        ("scene_verify/1 ", False),
        ("", False),
        (None, False),
        (1, False),
    ],
)
def test_accepted_major(value, accepted):
    assert is_accepted_schema_version(value) is accepted


def test_verdict_error_is_a_value_error():
    assert issubclass(VerdictError, ValueError)


# ---------------------------------------------------------------------------
# Accepted verdicts
# ---------------------------------------------------------------------------


def test_parses_a_full_verdict_into_typed_fields():
    verdict = parse_verdict(_verdict())
    assert isinstance(verdict, Verdict)
    assert verdict.schema_version == "scene_verify/1"
    assert verdict.scene_id == "scene_a"
    assert verdict.overall_status == "fail"
    assert verdict.verified_at == "2026-10-17T10:00:00+00:00"
    assert verdict.verifier_version == "0.3.0"
    assert verdict.usd_sha256 == USD_SHA256
    assert [gate.gate for gate in verdict.gates] == [
        "scene_load",
        "visual_collision_agreement",
        "interpenetration",
        "static_settle",
    ]
    assert verdict.gates[1] == GateVerdict(
        gate="visual_collision_agreement", status="warn", score=None, bucket="labeling", detail={}
    )
    assert verdict.bucket_attribution == {
        "labeling": ("visual_collision_agreement",),
        "interpenetration": ("interpenetration",),
    }


def test_all_pass_verdict_without_usd_binding():
    data = _verdict(
        overall_status="pass",
        gates=[_gate("scene_load"), _gate("static_settle", bucket="physics_instability")],
        bucket_attribution={},
    )
    del data["usd_sha256"]
    verdict = parse_verdict(data)
    assert verdict.overall_status == "pass"
    assert verdict.bucket_attribution == {}
    assert verdict.usd_sha256 is None


def test_warn_verdict():
    data = _verdict(
        overall_status="warn",
        gates=[_gate("scene_load"), _gate("fall_through", "warn", "fall_through", None)],
        bucket_attribution={"fall_through": ["fall_through"]},
    )
    assert parse_verdict(data).overall_status == "warn"


def test_two_gates_in_one_bucket_keep_gate_order():
    data = _verdict(
        overall_status="fail",
        gates=[
            _gate("recon_registration_coverage", "fail", "reconstruction_fidelity", 0.9),
            _gate("recon_surface_density", "warn", "reconstruction_fidelity", 0.5),
        ],
        bucket_attribution={
            "reconstruction_fidelity": ["recon_registration_coverage", "recon_surface_density"]
        },
    )
    verdict = parse_verdict(data)
    assert verdict.bucket_attribution == {
        "reconstruction_fidelity": ("recon_registration_coverage", "recon_surface_density")
    }


def test_a_minor_schema_version_is_accepted():
    assert parse_verdict(_verdict(schema_version="scene_verify/1.3")).schema_version == (
        "scene_verify/1.3"
    )


def test_unknown_keys_are_ignored():
    data = _verdict(added_later={"anything": 1})
    data["gates"][0]["added_later"] = True
    verdict = parse_verdict(data)
    assert verdict.scene_id == "scene_a"


def test_an_integer_score_is_read_as_a_float():
    data = _verdict()
    data["gates"][2]["score"] = 1
    score = parse_verdict(data).gates[2].score
    assert score == 1.0 and isinstance(score, float)


def test_gate_detail_is_kept():
    data = _verdict()
    data["gates"][2]["detail"] = {"offenders": [{"object_a": "a", "object_b": "b"}]}
    assert parse_verdict(data).gates[2].detail == {
        "offenders": [{"object_a": "a", "object_b": "b"}]
    }


def test_round_trips_through_json_text():
    assert parse_verdict(json.loads(json.dumps(_verdict()))) == parse_verdict(_verdict())


def test_a_utc_z_timestamp_is_accepted():
    assert parse_verdict(_verdict(verified_at="2026-10-17T10:00:00Z")).verified_at.endswith("Z")


def test_does_not_mutate_its_input():
    data = _verdict()
    before = copy.deepcopy(data)
    parse_verdict(data)
    assert data == before


# ---------------------------------------------------------------------------
# Rejections: each names the offending field
# ---------------------------------------------------------------------------


def _drop(key: str) -> Callable[[dict], None]:
    return lambda v: v.pop(key)


def _set(key: str, value: Any) -> Callable[[dict], None]:
    return lambda v: v.__setitem__(key, value)


def _set_gate(index: int, key: str, value: Any) -> Callable[[dict], None]:
    return lambda v: v["gates"][index].__setitem__(key, value)


def _drop_gate_key(index: int, key: str) -> Callable[[dict], None]:
    return lambda v: v["gates"][index].pop(key)


REJECTIONS: list[tuple[str, Callable[[dict], None], str]] = [
    # schema_version
    ("schema missing", _drop("schema_version"), "verdict is missing 'schema_version'"),
    ("schema major 2", _set("schema_version", "scene_verify/2"), "verdict.schema_version"),
    ("schema prefix only", _set("schema_version", "scene_verify/1x"), "verdict.schema_version"),
    ("schema not a string", _set("schema_version", 1), "verdict.schema_version"),
    # scene_id
    ("scene_id missing", _drop("scene_id"), "verdict is missing 'scene_id'"),
    ("scene_id empty", _set("scene_id", ""), "verdict.scene_id must be a non-empty string"),
    ("scene_id not a string", _set("scene_id", 7), "verdict.scene_id must be a non-empty string"),
    # overall_status
    ("overall missing", _drop("overall_status"), "verdict is missing 'overall_status'"),
    ("overall unknown", _set("overall_status", "ok"), "verdict.overall_status must be one of"),
    ("overall not a string", _set("overall_status", None), "verdict.overall_status must be one"),
    (
        "overall weaker than its gates",
        _set("overall_status", "pass"),
        "verdict.overall_status is 'pass' but its most severe gate status is 'fail'",
    ),
    (
        "overall stronger than its gates",
        lambda v: v["gates"][2].update(status="warn"),
        "verdict.overall_status is 'fail' but its most severe gate status is 'warn'",
    ),
    # verified_at
    ("verified_at missing", _drop("verified_at"), "verdict is missing 'verified_at'"),
    ("verified_at empty", _set("verified_at", ""), "verdict.verified_at must be a non-empty"),
    ("verified_at not ISO", _set("verified_at", "yesterday"), "verdict.verified_at must be an ISO"),
    ("verified_at a number", _set("verified_at", 1760695200), "verdict.verified_at must be a non"),
    # verifier_version
    (
        "verifier_version missing",
        _drop("verifier_version"),
        "verdict is missing 'verifier_version'",
    ),
    ("verifier_version empty", _set("verifier_version", ""), "verdict.verifier_version must be"),
    # gates
    ("gates missing", _drop("gates"), "verdict is missing 'gates'"),
    ("gates not a list", _set("gates", {"scene_load": "pass"}), "verdict.gates must be a list"),
    ("gates a string", _set("gates", "scene_load"), "verdict.gates must be a list"),
    ("gates empty", _set("gates", []), "verdict.gates must list at least one gate"),
    ("gate not an object", _set("gates", ["scene_load"]), "verdict.gates[0] must be a JSON object"),
    ("gate name missing", _drop_gate_key(0, "gate"), "verdict.gates[0] is missing 'gate'"),
    ("gate name empty", _set_gate(0, "gate", ""), "verdict.gates[0].gate must be a non-empty"),
    ("gate status missing", _drop_gate_key(1, "status"), "verdict.gates[1] is missing 'status'"),
    ("gate status unknown", _set_gate(1, "status", "skip"), "verdict.gates[1].status must be one"),
    ("gate score missing", _drop_gate_key(2, "score"), "verdict.gates[2] is missing 'score'"),
    ("gate score a bool", _set_gate(2, "score", True), "verdict.gates[2].score must be a finite"),
    (
        "gate score a string",
        _set_gate(2, "score", "1.0"),
        "verdict.gates[2].score must be a finite",
    ),
    ("gate score NaN", _set_gate(2, "score", math.nan), "verdict.gates[2].score must be a finite"),
    ("gate score inf", _set_gate(2, "score", math.inf), "verdict.gates[2].score must be a finite"),
    ("gate bucket missing", _drop_gate_key(3, "bucket"), "verdict.gates[3] is missing 'bucket'"),
    ("gate bucket unknown", _set_gate(3, "bucket", "vibes"), "verdict.gates[3].bucket must be one"),
    ("gate detail missing", _drop_gate_key(3, "detail"), "verdict.gates[3] is missing 'detail'"),
    ("gate detail a list", _set_gate(3, "detail", []), "verdict.gates[3].detail must be a JSON"),
    (
        "gate name repeated",
        _set_gate(3, "gate", "scene_load"),
        "verdict.gates[3].gate repeats the gate name 'scene_load'",
    ),
    # bucket_attribution
    (
        "attribution missing",
        _drop("bucket_attribution"),
        "verdict is missing 'bucket_attribution'",
    ),
    (
        "attribution not an object",
        _set("bucket_attribution", []),
        "verdict.bucket_attribution must be a JSON object",
    ),
    (
        "attribution unknown bucket",
        lambda v: v["bucket_attribution"].update(vibes=["scene_load"]),
        "verdict.bucket_attribution key must be one of",
    ),
    (
        "attribution value not a list",
        lambda v: v["bucket_attribution"].update(labeling="visual_collision_agreement"),
        "verdict.bucket_attribution['labeling'] must be a list of gate names",
    ),
    (
        "attribution omits a non-passing gate",
        lambda v: v["bucket_attribution"].pop("labeling"),
        "verdict.bucket_attribution must list each gate that did not pass",
    ),
    (
        "attribution lists a passing gate",
        lambda v: v["bucket_attribution"].update(load=["scene_load"]),
        "verdict.bucket_attribution must list each gate that did not pass",
    ),
    (
        "attribution under the wrong bucket",
        _set(
            "bucket_attribution",
            {"load": ["visual_collision_agreement"], "interpenetration": ["interpenetration"]},
        ),
        "verdict.bucket_attribution must list each gate that did not pass",
    ),
    # usd_sha256
    ("usd_sha256 null", _set("usd_sha256", None), "verdict.usd_sha256 must be a sha256 digest"),
    ("usd_sha256 short", _set("usd_sha256", "ab" * 8), "verdict.usd_sha256 must be a sha256"),
    (
        "usd_sha256 uppercase",
        _set("usd_sha256", USD_SHA256.upper()),
        "verdict.usd_sha256 must be a sha256 digest",
    ),
    (
        "usd_sha256 padded",
        _set("usd_sha256", USD_SHA256 + "\n"),
        "verdict.usd_sha256 must be a sha256 digest",
    ),
]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [pytest.param(mutate, message, id=label) for label, mutate, message in REJECTIONS],
)
def test_rejects_a_malformed_verdict_naming_the_field(mutate, message):
    data = _verdict()
    mutate(data)
    with pytest.raises(VerdictError) as raised:
        parse_verdict(data)
    assert message in str(raised.value)


@pytest.mark.parametrize("data", [None, "scene_verify/1", [], 3, b"{}"])
def test_rejects_a_verdict_that_is_not_an_object(data):
    with pytest.raises(VerdictError, match="verdict must be a JSON object"):
        parse_verdict(data)


def test_a_long_offending_value_is_shortened_in_the_message():
    with pytest.raises(VerdictError) as raised:
        parse_verdict(_verdict(schema_version="x" * 500))
    assert len(str(raised.value)) < 200
    assert str(raised.value).endswith("...")


def test_status_values_type_check_as_the_literal():
    # The typed result carries the contract's literal values, not arbitrary strings.
    statuses: tuple[GateStatus, ...] = tuple(g.status for g in parse_verdict(_verdict()).gates)
    buckets: tuple[Bucket, ...] = tuple(g.bucket for g in parse_verdict(_verdict()).gates)
    assert set(statuses) <= set(GATE_STATUSES)
    assert set(buckets) <= set(BUCKETS)
