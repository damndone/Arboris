"""A confirmed refit's result message carries its estimates, as a workflow's does.

2026-11-08 NVIDIA positions (binary_logit, Ask): after every confirmed model.rerun the outcome
message told the Agent to read the new results with inspect_project_model_coefficients, and it
did: one model request per refit for numbers the Workbench already had.
"""
from __future__ import annotations

from types import SimpleNamespace

from tests.test_agent_context_tools import _load_provider_type, _write_project_run
from workbench.agent import operation_outcome
from workbench.agent.context_tools_support.requests import InspectProjectModelCoefficientsRequest

RECORD = {"record_id": "oprec_1", "operation_id": "model.rerun", "proposal_id": "proposal_1",
          "status": "completed", "outputs": {"status": "completed", "target_run_id": "run-a"},
          "execution": {"bindings": {"child_run_id": "run-a"}}}


def _record():
    return SimpleNamespace(status="completed", operation_id="model.rerun", changes={"model_type": "logit"},
                           to_dict=lambda: dict(RECORD))


def test_the_refit_message_carries_the_coefficients_the_inspect_tool_returns(tmp_path):
    root = tmp_path / "project"
    _write_project_run(root)
    extras = operation_outcome.outcome_extras(root, "s", _record())
    terms = tuple(row["term"] for row in extras["model_estimates"]["models"][0]["coefficients"])
    expected = _load_provider_type()(root).inspect_project_model_coefficients(
        InspectProjectModelCoefficientsRequest(run_ids=("run-a",), terms=terms))
    assert extras["model_estimates"]["models"] == expected["models"]
    text = operation_outcome.outcome_text({**operation_outcome.outcome(root, RECORD), **extras})
    assert "model_estimates: " in text and "Read the new results with" not in text
    assert "only to compare with another run" in text


def test_estimates_too_large_for_the_message_are_left_to_the_tool(tmp_path, monkeypatch):
    root = tmp_path / "project"
    _write_project_run(root)
    monkeypatch.setattr(operation_outcome, "ESTIMATES_CHARS", 10)
    extras = operation_outcome.outcome_extras(root, "s", _record())
    text = operation_outcome.outcome_text({**operation_outcome.outcome(root, RECORD), **extras})
    assert "model_estimates: " not in text
    assert "inspect_project_model_coefficients using run_ids [run-a]" in text


def test_a_run_without_a_model_gets_no_estimates(tmp_path):
    root = tmp_path / "project"
    (root / "runs" / "run-a").mkdir(parents=True)
    assert "model_estimates" not in operation_outcome.outcome_extras(root, "s", _record())


def test_the_refit_message_names_the_head_and_the_fields_that_use_the_new_model(tmp_path):
    from workbench.agent.chains import ChainStore

    root = tmp_path / "project"
    _write_project_run(root)
    ChainStore(root / "workbench").create_root(chain_id="chain-a", run_family_id="family",
                                               active_head_run_id="run-head", agent_session_id="s")
    record = _record()
    record.chain_id = "chain-a"
    text = operation_outcome.outcome_text({**operation_outcome.outcome(root, RECORD),
                                           **operation_outcome.outcome_extras(root, "s", record)})
    assert "The conversation's head stays run run-head" in text
    assert 'model_ref to the model node ("model:ols_1", a string) and model_run_id to "run-a"' in text


def test_without_a_known_head_nothing_is_guessed(tmp_path):
    root = tmp_path / "project"
    _write_project_run(root)
    text = operation_outcome.outcome_text({**operation_outcome.outcome(root, RECORD),
                                           **operation_outcome.outcome_extras(root, "s", _record())})
    assert "head stays" not in text
