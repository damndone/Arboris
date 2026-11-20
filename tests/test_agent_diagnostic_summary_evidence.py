"""Bounded inspection retains existing diagnostic risks without exposing rows."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.test_agent_context_tools import _write_project_run
from workbench.agent.context_tools import InspectDiagnosticsRequest, NodeOperationContextProvider
from workbench.agent.tools import ToolVisibleError


def _registered_diagnostic(tmp_path, payload, *, companion=False):
    project = tmp_path / "project"
    _write_project_run(project)
    run = project / "runs" / "run-a"
    if companion:
        model_path = run / "model_results/ols_1.json"
        model = json.loads(model_path.read_text())
        model_path.write_text(json.dumps({**model, "model_type": payload.get("model_type", model["model_type"])}))
    model_sha = hashlib.sha256((run / "model_results/ols_1.json").read_bytes()).hexdigest()
    artifact_id = "ols_1.completion" if companion else "diagnostics_ols_1"
    if companion:
        payload = {"model_id": "ols_1", "model_payload_sha256": model_sha, **payload}
    path = run / "model_results" / (artifact_id + ".json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (run / "artifacts_index.json").write_text(json.dumps({"artifacts": [
        {"artifact_id": "ols_1", "artifact_type": "model_result", "path": "model_results/ols_1.json",
         "sha256": model_sha, "inputs": ["cleaned_dataset"]},
        {"artifact_id": artifact_id,
         "artifact_type": "analysis_completion_evidence" if companion else "model_diagnostic",
         "path": str(path.relative_to(run)), "sha256": digest, "inputs": ["ols_1", "cleaned_dataset"]},
    ]}), encoding="utf-8")
    return project, path, artifact_id, digest


def _inspect(project):
    return NodeOperationContextProvider(project).inspect_diagnostics(InspectDiagnosticsRequest(
        request_id="diagnostics", owner_run_id="run-a", op_node_id="model:ols_1",
        active_head_run_id="run-a"))


def _evidence(result, artifact_id="diagnostics_ols_1"):
    return next(item for item in result["diagnostics"]["persisted_diagnostics"]
                if item["source"]["artifact_id"] == artifact_id)


def test_inspection_keeps_recorded_influence_summary_and_registered_source(tmp_path):
    # The scalar shape is the normal persisted OLS diagnostic producer's shape.
    influence = {"max": 1.0498, "threshold": 0.05, "n_high": 3, "n_severe": 3, "leverage_max": 0.3472}
    payload = {"model_id": "ols_1", "model_type": "ols_robust", "nobs": 80,
               "breusch_pagan": {"lm": 9.206461674926505, "p_value": 0.002411623627556376},
               "cooks_distance": influence, "residuals": [92713.25] * 200,
               "studentized_residuals": [92713.25] * 200}
    project, path, artifact_id, digest = _registered_diagnostic(tmp_path, payload)
    before = path.read_bytes()
    result = _inspect(project)
    evidence = _evidence(result)
    assert evidence["summary"]["cooks_distance"] == influence
    assert evidence["summary"]["breusch_pagan"] == payload["breusch_pagan"]
    assert evidence["source"] == {"run_id": "run-a", "artifact_id": artifact_id, "sha256": digest}
    assert evidence["model_id"] == "ols_1"
    assert evidence["omitted_field_count"] == 2
    assert "92713.25" not in json.dumps(result)
    assert len(json.dumps(result, ensure_ascii=False)) < 8192
    assert path.read_bytes() == before


@pytest.mark.parametrize("family,diagnostic", [
    ("panel_ols", {"panel": {"status": "computed", "n_entities": 17, "cluster_count": 17,
                            "serial_dependence_test": "not_performed", "scientific_validity": "not_certified"}}),
    ("iv_2sls", {"iv": {"weak_instruments": {"first_stage_statistic": 4.123456789012345,
                                            "strength_certified": False,
                                            "anderson_rubin_95": {"kind": "not_computed"}}}}),
])
def test_native_companion_scalars_keep_their_existing_uncertainty(tmp_path, family, diagnostic):
    project, _, _, _ = _registered_diagnostic(tmp_path, {"model_type": family, "diagnostics": diagnostic}, companion=True)
    evidence = _evidence(_inspect(project), "ols_1.completion")
    assert evidence["summary"] == diagnostic
    assert evidence["omitted_field_count"] == 0


@pytest.mark.parametrize("corruption", ["sha", "model", "companion_model_sha"])
def test_unverified_diagnostic_is_explicit_and_never_presented_as_risk_evidence(tmp_path, corruption):
    companion = corruption == "companion_model_sha"
    payload = {"model_id": "other" if corruption == "model" else "ols_1", "cooks_distance": {"n_high": 7}}
    if companion:
        payload = {"diagnostics": {"panel": {"status": "computed"}}, "model_payload_sha256": "0" * 64}
    project, path, _, _ = _registered_diagnostic(tmp_path, payload, companion=companion)
    if corruption == "sha":
        path.write_text(path.read_text() + " ")
    evidence = _evidence(_inspect(project), "ols_1.completion" if companion else "diagnostics_ols_1")
    assert evidence["status"] == "unavailable"
    assert "summary" not in evidence
    assert "explicit artifact inspection" in evidence["reason"]


def test_oversize_registered_diagnostic_is_not_read_by_default_inspection(tmp_path, monkeypatch):
    project, path, _, _ = _registered_diagnostic(tmp_path, {"model_id": "ols_1", "cooks_distance": {"n_high": 7}})
    with path.open("ab") as stream:
        stream.truncate(16_000_001)
    original = Path.read_bytes
    original_text = Path.read_text

    def forbid_large_read(self):
        assert self != path, "default diagnostic inspection read the oversized product"
        return original(self)

    def forbid_large_text_read(self, *args, **kwargs):
        assert self != path, "default diagnostic inspection read the oversized product"
        return original_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", forbid_large_read)
    monkeypatch.setattr(Path, "read_text", forbid_large_text_read)
    evidence = _evidence(_inspect(project))
    assert evidence["status"] == "unavailable"
    assert "bounded read limit" in evidence["reason"]


def test_risk_summary_precedes_unrelated_large_details_and_counts_omissions(tmp_path):
    payload = {"model_id": "ols_1", **{f"detail_{i}": {"label": "detail" * 100} for i in range(100)},
               "cooks_distance": {"n_high": 9, "n_severe": 2, "threshold": 0.04, "leverage_max": 0.42}}
    project, _, _, _ = _registered_diagnostic(tmp_path, payload)
    result = _inspect(project)
    evidence = _evidence(result)
    assert evidence["summary"]["cooks_distance"] == payload["cooks_distance"]
    assert evidence["omitted_field_count"] > 0
    assert len(json.dumps(result, ensure_ascii=False)) <= 8192


def test_malformed_registered_index_is_visible_and_never_uses_legacy_reader(tmp_path, monkeypatch):
    project, _, _, _ = _registered_diagnostic(tmp_path, {"model_id": "ols_1"})
    (project / "runs/run-a/artifacts_index.json").write_text("not json")

    def no_legacy(*args):
        pytest.fail("registered evidence failure fell back to the legacy reader")

    monkeypatch.setattr("workbench.agent.context_tools_support.node_tools.read_model_results", no_legacy)
    with pytest.raises(ToolVisibleError, match="DIAGNOSTIC_INDEX_UNAVAILABLE"):
        _inspect(project)


def test_native_packet_keeps_public_preview_without_completion_verification(tmp_path, monkeypatch):
    project, _, _, _ = _registered_diagnostic(tmp_path, {"model_id": "ols_1"})
    index_path = project / "runs/run-a/artifacts_index.json"
    index = json.loads(index_path.read_text())
    index["artifacts"].append({"artifact_id": "ols_1.result", "artifact_type": "model_result_packet"})
    index_path.write_text(json.dumps(index))
    public_reads = []

    def public_owner_reader(run_root):
        public_reads.append(run_root)
        return [{"model_id": "ols_1", "model_type": "linear_mixed_effects", "payload": {"status": "complete"}}]

    def no_completion_verifier(*args):
        pytest.fail("native public preview called the completion verifier/source reader")

    monkeypatch.setattr("workbench.services.lmm_result_adapter.read_lmm_public_results", public_owner_reader)
    monkeypatch.setattr("workbench.agent.context_tools_support.node_tools.read_completion_artifact", no_completion_verifier)
    diagnostics = _inspect(project)["diagnostics"]
    assert public_reads == [project / "runs/run-a"]
    assert "persisted_diagnostics" not in diagnostics
    assert "Native public preview" in diagnostics["evidence_verification"]
    assert "not covered" in diagnostics["evidence_verification"]
