"""Survival evidence contract, driven by a real run rather than a literal.

v1.8.6 built this packet from a hand-written dictionary: four observations, two
events, a Kaplan-Meier curve typed out by hand. Round-tripping a literal proves
the contract accepts what the test author believed the engine emits, which is a
different claim from accepting what it actually emits -- and the two drifted
apart the moment v1.8.7 changed the validation block, with nothing here noticing.

A3-1 asks for exactly this: the packet now comes from the committed fixture,
through the engine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.survival import SurvivalEvidenceContract
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "v186_families"


@pytest.fixture(scope="module")
def survival_packet(tmp_path_factory) -> dict:
    tmp_path = tmp_path_factory.mktemp("survival_contract")
    source = tmp_path / "families.csv"
    source.write_text((FIXTURES / "families.csv").read_text())
    project = create_project(tmp_path, "survival_contract")
    outcome = run_workflow(
        project.root, [source], mode="auto",
        model_type="survival_cox", y="duration", x=["x1", "x2", "grp"],
        model_options={"event_column": "event"},
    )
    assert outcome["status"] == "completed", outcome
    # The evidence packet is its own artifact, not one of the model_results:
    # `survival_cox_1.json` only names it via `survival_evidence_artifact`.
    evidence = project.root / "runs" / outcome["run_id"] / "survival" / "evidence.json"
    assert evidence.exists(), "the run produced no survival evidence artifact"
    return read_json(evidence)


def test_survival_contract_round_trips_a_real_engine_packet(survival_packet) -> None:
    packet = SurvivalEvidenceContract.from_dict(survival_packet)

    assert packet.to_dict() == survival_packet
    assert packet.duration_column == "duration"
    assert packet.event_column == "event"

    oracle = json.loads((FIXTURES / "oracle.json").read_text())["survival_cox"]
    assert packet.nobs == oracle["n_obs"]
    assert packet.censoring["events"] == oracle["n_events"]
    # `at_risk`, not `n_at_risk`: the retired literal used the latter, which the
    # engine has never emitted. A hand-written packet can be wrong about the
    # thing it is meant to pin down, and this one was.
    at_risk = [row["at_risk"] for row in packet.risk_set]
    assert at_risk == sorted(at_risk, reverse=True), "the risk set must not grow"
    assert at_risk[0] <= oracle["n_obs"]
    # Not equal to n_obs: the first row is the first *event* time, by which point
    # anything censored earlier has already left.
    assert at_risk[0] >= oracle["n_obs"] - 5


def test_survival_evidence_reports_the_oracle_it_was_checked_against(survival_packet) -> None:
    """The packet claims a level; the claim has to be backed on its face."""
    validation = survival_packet["validation"]
    assert validation["level"] == "external_oracle_exact"
    assert "coxph" in validation["external_oracle"]


def test_survival_contract_rejects_missing_censoring_and_risk_set_evidence(
    survival_packet,
) -> None:
    payload = dict(survival_packet)
    payload.pop("censoring")

    with pytest.raises(Exception, match="survival_evidence"):
        SurvivalEvidenceContract.from_dict(payload)


def test_survival_contract_rejects_an_unbacked_validation_claim(survival_packet) -> None:
    """The failure the level split makes possible, asserted so it stays closed.

    Claiming an external oracle while naming none is the shape of an unsupported
    assertion -- the thing these contracts exist to refuse.
    """
    payload = dict(survival_packet)
    payload["validation"] = {
        "level": "external_oracle_exact",
        "external_oracle": "not_verified",
    }

    with pytest.raises(Exception, match="external_oracle"):
        SurvivalEvidenceContract.from_dict(payload)
