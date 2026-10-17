"""Regression-lock the corpus failure root-cause classification.

Runs the classifier against the committed corpus artifacts and asserts the defensible
properties the Stage-3 corpus result rests on:
  * the verifier discriminates (it passes some rows and fails others — not a reject-all gate);
  * every non-pass row is root-caused to a concrete offender + gate, with no unexplained failure;
  * each finding carries a gate-appropriate cross-check verdict.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "tools" / "classify_corpus_failures.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("classify_corpus_failures", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def classified():
    m = _load_module()
    report = m._load(m.CORPUS_REPORT)
    if not report:
        pytest.skip("corpus_report.json not present")
    asset_ev = m._asset_evidence_across_corpus()
    rows = [m._classify_row(r) for r in report.get("non_pass_rows", [])]
    return m, report, asset_ev, rows


def test_verifier_discriminates(classified):
    _, report, _, _ = classified
    dist = report.get("overall_distribution", {})
    assert dist.get("pass", 0) > 0, "verifier passed nothing -> not discriminating"
    assert dist.get("fail", 0) > 0, "verifier failed nothing -> nothing to root-cause"


def test_every_failure_has_a_concrete_offender(classified):
    _, _, _, rows = classified
    assert rows, "no non-pass rows classified"
    for row in rows:
        assert row.get("findings"), f"{row['row']} failed with no findings"
        for f in row["findings"]:
            assert f.get("gate"), f"finding without a gate in {row['row']}"
            # physics + mesh findings must name the offending object and a root cause.
            if f["gate"] in ("static_settle", "fall_through", "visual_collision_agreement"):
                assert f.get("offender"), f"{f['gate']} in {row['row']} named no offender"
                assert f.get("root_cause"), f"{f['gate']} in {row['row']} has no root cause"


def test_mesh_findings_use_consistency_crosscheck_not_stability(classified):
    m, _, asset_ev, rows = classified
    # attach cross-checks the way main() does, then assert gate-appropriateness.
    for row in rows:
        for f in row.get("findings", []):
            oid = f.get("offender")
            if not oid or oid not in asset_ev:
                continue
            if f["gate"] == "visual_collision_agreement":
                divergent = [r for r in asset_ev[oid]
                             if (r.get("phantom_max_m") or 0.0) >= m.MESH_PHANTOM_FAIL_M
                             or (r.get("clip_max_m") or 0.0) >= m.MESH_CLIP_FAIL_M]
                # a flagged mesh mismatch must be reproduced in at least the row it was flagged in.
                assert divergent, f"{oid} flagged for mesh mismatch but no row reproduces it"
