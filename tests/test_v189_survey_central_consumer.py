from __future__ import annotations

from importlib.util import find_spec
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import workbench.agent.context_tools as context_tools
import workbench.agent.notebook.evidence as notebook_evidence
import workbench.services.survey_consumer_service as survey_service
from workbench.artifacts import sha256_file, write_json
from workbench.orchestrator import run_workflow
from workbench.predictive_research.contracts import ContractError
from workbench.projects import create_project
from workbench.providers.catalog import load_builtin_catalog


FIXTURES = Path(__file__).parent / "fixtures"


def test_survey_central_source_contract_is_present() -> None:
    """Survey needs a dedicated server-owned source and consumer contract."""

    assert find_spec("workbench.evidence.survey_projection_adapter") is not None
    assert find_spec("workbench.services.survey_consumer_service") is not None


def _materialize_survey_run(tmp_path: Path, *, model_type: str = "ols") -> tuple[Path, Path]:
    source = tmp_path / f"{model_type}.csv"
    frame = pd.read_csv(FIXTURES / "survey" / "design.csv")
    if model_type == "logit":
        rng = np.random.default_rng(20260820)
        probability = 1.0 / (1.0 + np.exp(-(0.35 * frame["x1"] - 0.08 * frame["x2"])))
        frame["binary_y"] = rng.binomial(1, probability)
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, f"survey-{model_type}")
    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type=model_type,
        y="binary_y" if model_type == "logit" else "y",
        x=["x1", "x2"],
        sampling_weight="weight",
        survey_strata_col="stratum",
        survey_psu_col="psu",
    )
    assert outcome["status"] == "completed", outcome
    return project.root, project.root / "runs" / outcome["run_id"]


def _server_capability(run_root: Path) -> object:
    return survey_service.issue_survey_run_capability(
        run_root.parent.parent,
        run_root.name,
    )


def _rewrite_bound_artifact(run_root: Path, update) -> None:
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    record = next(
        item for item in index["artifacts"] if item.get("artifact_type") == "model_result"
    )
    path = run_root / record["path"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    update(payload)
    binding = payload["result_binding"]
    unsigned = dict(payload)
    unsigned_binding = dict(binding)
    unsigned_binding.pop("payload_sha256", None)
    unsigned["result_binding"] = unsigned_binding
    import hashlib

    binding["payload_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    write_json(path, payload)
    for item in index["artifacts"]:
        if item.get("artifact_id") == payload["model_id"]:
            item["sha256"] = sha256_file(path)
    write_json(index_path, index)


@pytest.mark.parametrize("model_type", ("ols", "logit"))
def test_authorized_survey_snapshot_is_shared_by_agent_and_notebook(
    tmp_path: Path, model_type: str
) -> None:
    project_root, run_root = _materialize_survey_run(tmp_path, model_type=model_type)

    agent = context_tools.read_survey_evidence_for_agent(_server_capability(run_root))
    notebook = notebook_evidence.read_survey_evidence_for_notebook(
        _server_capability(run_root)
    )
    report = survey_service.read_survey_consumer_projection(
        _server_capability(run_root), "report"
    )

    assert agent["status"] == "validated"
    assert notebook["status"] == "validated"
    assert report["status"] == "validated"
    assert agent["model_family"] == notebook["model_family"] == model_type
    assert report["model_family"] == model_type
    assert agent["survey_design"] == notebook["survey_design"]
    assert report["survey_design"] == agent["survey_design"]
    assert agent["source"] == notebook["source"]
    assert report["source"] == agent["source"]
    report_surface = survey_service.read_survey_report_evidence(_server_capability(run_root))
    assert report_surface["payload_schema"] == "workbench.survey.report-evidence.v1"
    assert report_surface["receipt"]["kind"] == "evidence.survey.server-receipt.v1"
    assert agent["source"]["server_identity"]["run_id"] == run_root.name
    assert project_root.name.startswith("survey-")


def test_central_survey_reader_rejects_path_raw_packet_and_forged_capability(
    tmp_path: Path,
) -> None:
    _project_root, run_root = _materialize_survey_run(tmp_path)

    for value in (run_root, str(run_root), {"raw": "packet"}):
        with pytest.raises(ContractError) as error:
            survey_service.read_survey_consumer_projection(value, "agent")
        assert error.value.code == "SURVEY_RUN_CAPABILITY_REQUIRED"

    forged = object.__new__(survey_service._SurveyRunCapability)
    object.__setattr__(forged, "_token", "forged")
    with pytest.raises(ContractError) as error:
        survey_service.read_survey_consumer_projection(forged, "agent")
    assert error.value.code == "SURVEY_RUN_CAPABILITY_REQUIRED"

    with pytest.raises(ContractError):
        context_tools.read_survey_evidence_for_agent(run_root)
    with pytest.raises(ContractError):
        notebook_evidence.read_survey_evidence_for_notebook({"raw": "packet"})


def test_survey_unavailable_reason_survives_authorized_snapshot(tmp_path: Path) -> None:
    _project_root, run_root = _materialize_survey_run(tmp_path)

    def mark_unavailable(payload: dict[str, object]) -> None:
        payload["survey_evidence_status"] = "unavailable"
        payload["survey_unavailable_reason"] = "SURVEY_TEST_UNAVAILABLE"

    _rewrite_bound_artifact(run_root, mark_unavailable)

    projection = survey_service.read_survey_consumer_projection(
        _server_capability(run_root), "agent"
    )

    assert projection["status"] == "unavailable"
    assert projection["reason"] == "SURVEY_TEST_UNAVAILABLE"
    assert projection["survey_design"]["variance_method"]


@pytest.mark.parametrize("mutation", ("remove_status", "malformed_status", "malformed_binding"))
def test_survey_invalid_persisted_status_or_binding_is_unavailable(
    tmp_path: Path, mutation: str
) -> None:
    _project_root, run_root = _materialize_survey_run(tmp_path)

    def invalidate(payload: dict[str, object]) -> None:
        if mutation == "remove_status":
            payload.pop("survey_evidence_status", None)
        elif mutation == "malformed_status":
            payload["survey_evidence_status"] = "validated-but-not-a-status"
        else:
            binding = payload["result_binding"]
            assert isinstance(binding, dict)
            binding["strategy"] = "forged_strategy_v1"

    _rewrite_bound_artifact(run_root, invalidate)
    projection = (
        survey_service.read_survey_report_evidence(_server_capability(run_root))
        if mutation == "malformed_binding"
        else survey_service.read_survey_consumer_projection(
            _server_capability(run_root), "agent"
        )
    )

    assert projection["status"] == "unavailable"
    assert projection.get("reason") in {
        "SURVEY_EVIDENCE_STATUS_INVALID",
        "SURVEY_PERSISTED_ARTIFACT_REQUIRED",
        "SURVEY_RESULT_BINDING_INVALID",
        "SURVEY_PERSISTED_ARTIFACT_UNAVAILABLE",
    }


def test_survey_provider_contribution_is_catalog_visible() -> None:
    catalog = load_builtin_catalog()
    provider = next(
        item for item in catalog.providers if item.provider_id == "workbench.survey"
    )

    assert provider.exposure_paths[0].path_id == "workbench.survey.central_source"
    assert {
        declaration.consumer_id for declaration in provider.projection_declarations
    } == {"agent", "notebook", "report"}
    assert all(
        declaration.coverage_status == "required"
        for declaration in provider.projection_declarations
    )
