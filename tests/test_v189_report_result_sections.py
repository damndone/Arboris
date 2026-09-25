"""Producer snapshot/section integration through a real admitted host store."""
import copy
import hashlib
import json

import pytest

from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
from workbench.artifacts import initialize_artifact_index, register_artifact, write_json
from workbench.contracts.evidence.envelope import EvidenceEnvelopeV1
from workbench.contracts.evidence.result_sections import (
    SECTION_FIELDS, StructuredResultsV1, resolve_section_content,
)
from workbench.evidence.result_dependencies import verify_result_dependencies
from workbench.services.report_evidence_owner_factory import (
    ServerOwnedReportEvidenceOwnerFactoryV1, build_workflow_report_evidence_envelope,
)
from workbench.report_view_model import build_regression_table


@pytest.fixture
def producer(tmp_path):
    root = tmp_path / "project"
    run = root / "runs" / "r1"
    run.mkdir(parents=True)
    initialize_artifact_index(run)
    packet = {"model_id": "ols_1", "model_type": "ols", "nobs": 30,
              "coefficients": {"x": {"estimate": 1.25, "std_error": 0.2,
                "p_value": 1e-25, "confidence_interval": [0.8, 1.8],
                "confidence_interval_method": "percentile_bootstrap", "confidence_level": 0.9,
                "reference_distribution": {"name": "bootstrap", "degrees_of_freedom":
                    {"status": "not_applicable", "reason": "empirical"}, "parameters": {}},
                "p_value_status": "approximate"}},
              "survey_design": {"degf": 12.0, "variance_method": "jackknife", "n_obs": 30},
              "marginal_effects": [{"term": "x", "estimate": 0.3, "p_value": 1e-20}],
              "marginal_effects_method": "average"}
    write_json(run / "model_results" / "ols_1.json", packet)
    register_artifact(run, "ols_1", run / "model_results" / "ols_1.json", "model_result", "econometrics", [])
    registry, host = _authorized_registry("scope:project:sections")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with _admit_store(evidence, registry) as store:
        factory = ServerOwnedReportEvidenceOwnerFactoryV1.from_host(store, registry,
            actor_ref="actor:sections", project_ref="project:sections", session_ref="session:sections",
            scope_ref="scope:project:sections", canonical_project_root=root, authority_handle=host.channel)
        yield factory, run, packet
        factory.close()


def prepare(producer, **overrides):
    factory, _, packet = producer
    kwargs = dict(run_id="r1", model_run_id="ols_1", upload_hash="a" * 64,
        primary_model_type="ols", regression_table=build_regression_table([("ols_1", packet)]),
        model_artifact_ids=["ols_1"], issue_dicts=[],
        report_fields={"descriptive_stats": [{"column": "x", "label": "Exposure", "count": 30, "mean": 0.125}],
            "statistical_evidence": {"results": [{"test": "t", "p_value": 1e-30, "statistic": 3.5}]},
            "variable_importance": [{"variable": "x", "best_p_value": 1e-25, "correlation": 0.8}]},
        diagnostic_summary={"diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
            "narrative_contract": {"constraints": {"causal_language_allowed": False},
                "required_mentions": [], "forbidden_claims": ["X causes Y"]},
            "run_status": {"model_fit_status": "success", "report_render_status": "pending"}})
    kwargs.update(overrides)
    method = getattr(factory, "prepare_report_evidence_envelope", None)
    assert callable(method), "host-bound structured producer API is missing"
    return method(**kwargs)


def sections(envelope):
    typed = EvidenceEnvelopeV1.from_dict(envelope)
    facts = {fact.fact_id: fact for fact in typed.numeric_facts}
    value = StructuredResultsV1.from_dict(envelope["family_evidence"]["structured_results"],
        facts=facts, dependency_ids={dep["artifact_ref"] for dep in envelope["dependencies"]})
    return {section.section_id: resolve_section_content(section, facts=facts) for section in value.sections}


@pytest.fixture
def arma_producer(producer):
    """Small real runtime, including its registered time-series/chart artifacts."""
    from tests.models.arma_garch.test_pack_runtime import _context, _source, _Recorder
    from workbench.engine.context import RunEnv
    from workbench.engine.packs.arma_garch.runner import fit_from_context

    factory, run, _ = producer
    model_id, packet, _ = fit_from_context(
        _context(_source()), RunEnv(run_root=run, run_id="r1", recorder=_Recorder()))
    path = run / "model_results" / f"{model_id}.json"
    write_json(path, packet)
    register_artifact(run, model_id, path, "model_result", "econometrics", [])
    envelope = factory.prepare_report_evidence_envelope(
        run_id="r1", model_run_id=model_id, upload_hash="a" * 64,
        primary_model_type="time_series.arma_garch",
        regression_table=build_regression_table([(model_id, packet)]),
        model_artifact_ids=[model_id], report_fields={}, diagnostic_summary={}, issue_dicts=[])
    receipt = factory.issue_production_receipt(run_id="r1", model_run_id=model_id, upload_hash="a" * 64)
    owner = factory.create_for_run(run_id="r1", model_run_id=model_id, production_receipt=receipt,
        envelope=envelope, artifact_file_sha256=factory.report_evidence_file_sha256(envelope))
    yield owner, envelope, run, packet


def test_real_arma_public_payload_projection(tmp_path):
    from tests.models.arma_garch.test_pack_runtime import _context, _source, _Recorder
    from workbench.engine.context import RunEnv
    from workbench.engine.packs.arma_garch.runner import fit_from_context
    from workbench.services.report_result_sections import _arma_public_report

    initialize_artifact_index(tmp_path)
    _, packet, _ = fit_from_context(
        _context(_source()), RunEnv(run_root=tmp_path, run_id="r1", recorder=_Recorder()))
    payloads = {key: json.loads((tmp_path / path).read_text())["payload"]
                for key, path in packet["artifact_refs"].items()}
    public = _arma_public_report(payloads, list(payloads))
    assert public["metrics"] == packet["validation"]["metrics"]
    assert public["parameters"] == payloads["ts.parameters"]
    assert public["chart_artifacts"] == sorted(key for key in payloads if key.startswith("ts.chart."))
    assert public["next_forecast"]["conditional_mean"] == packet["production_child"]["next_forecast"]["conditional_mean"]


def test_real_arma_public_sections_and_dependency_closure(arma_producer):
    owner, envelope, run, packet = arma_producer
    family = sections(envelope)["model_family_evidence"]["results"]["arma_garch_1"]
    assert "report" in family, "ARMA typed public report fields are missing"
    report = family["report"]
    assert report["metrics"] == packet["validation"]["metrics"]
    assert report["next_forecast"]["conditional_mean"] == packet["production_child"]["next_forecast"]["conditional_mean"]
    charts = sorted(key for key in packet["artifact_refs"] if key.startswith("ts.chart."))
    assert report["chart_artifacts"] == charts
    manifest_ids = {row["artifact_id"] for row in envelope["family_evidence"]["result_dependencies"]["records"]}
    assert set(charts) | {"ts.parameters", "ts.final_diagnostics", "ts.analysis_contract"} <= manifest_ids
    section = next(s for s in envelope["family_evidence"]["structured_results"]["sections"]
                   if s["section_type"] == "model_family_evidence")
    assert set(charts) <= set(section["dependency_refs"])
    numeric = [f for f in envelope["numeric_facts"] if '["report"]' in f["source_selector"]["selector"]]
    assert numeric and all(f["fact_id"] in section["fact_refs"] for f in numeric)
    assert any('["metrics"]["mae"]' in f["source_selector"]["selector"] for f in numeric)
    owner._canonical_report_artifact()


@pytest.mark.parametrize("artifact_id", ["ts.parameters", "ts.chart.acf"])
def test_real_arma_bound_artifact_tamper_rejected(arma_producer, artifact_id):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    owner, _, run, packet = arma_producer
    # The C0 artifact accessor returns the immutable sealed packet; current
    # dependency admission occurs at delivery, not at that metadata accessor.
    query = dict(consumer_id="report", section_id="model_family_evidence", offset=0)
    page = owner.read_result_section_page(**query)
    assert page["read_completeness"] == "PARTIAL" and page["delivery"]["page"]["payload_base64"]
    path = run / packet["artifact_refs"][artifact_id]
    assert path.is_file(), "tamper anchor must exist in actual runtime output"
    before = path.read_bytes()
    path.write_bytes(before + b" ")
    assert path.read_bytes() != before, "tamper must change actual artifact bytes"
    with pytest.raises(EvidenceProjectionError, match="DEPENDENCY|dependency"):
        owner.read_result_section_page(**query)


@pytest.mark.parametrize("field", ["run_id", "dataset_hash", "contract_hash", "analysis_view_hash", "model_spec", "artifact_id"])
def test_arma_producer_rejects_rehashed_foreign_execution(producer, request, monkeypatch, field):
    from workbench.evidence import result_dependencies as dependencies
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    _, run, _ = producer
    original = dependencies.capture_result_dependencies
    mutations = []

    def capture(store, **kwargs):
        if not mutations and "ts.parameters" in kwargs["artifact_ids"]:
            path = run / "artifacts" / "time_series" / "ts.parameters.json"
            value = json.loads(path.read_text())
            if field == "artifact_id":
                assert value[field] == "ts.parameters"
                value[field] = "ts.foreign"
            else:
                assert field in value["metadata"]
                value["metadata"][field] = {"foreign": True} if field == "model_spec" else "foreign-execution"
            write_json(path, value)
            index = json.loads((run / "artifacts_index.json").read_text())
            row = next(item for item in index["artifacts"] if item["artifact_id"] == "ts.parameters")
            row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            write_json(run / "artifacts_index.json", index)
            mutations.append(field)
        return original(store, **kwargs)

    monkeypatch.setattr(dependencies, "capture_result_dependencies", capture)
    with pytest.raises(EvidenceProjectionError, match="different execution"):
        request.getfixturevalue("arma_producer")
    assert mutations == [field], "the real source and mutable index must both change"
    assert not (run / "result_input.json").exists(), "foreign sources must fail before snapshot publication"


def test_host_snapshot_sections_exact_values_and_sources(producer):
    envelope = prepare(producer)
    decoded = sections(envelope)
    assert set(decoded) == set(SECTION_FIELDS)
    cell = decoded["regression_table"]["rows"][0]["models"]["ols_1"]
    assert cell["p_value"] == 1e-25
    assert cell["confidence_interval_method"] == "percentile_bootstrap"
    assert cell["confidence_level"] == 0.9
    assert cell["p_value_status"] == "approximate"
    assert decoded["descriptive_statistics"]["rows"][0]["label"] == "Exposure"
    assert decoded["statistical_tests"]["results"][0]["p_value"] == 1e-30
    assert decoded["survey_design"]["design"]["ols_1"]["variance_method"] == "jackknife"
    assert decoded["marginal_effects"]["rows"][0]["p_value"] == 1e-20
    assert decoded["workflow_status"]["status"] == "pending"
    manifest = envelope["family_evidence"]["result_dependencies"]
    assert {row["artifact_id"] for row in manifest["records"]} == {"ols_1", "result-input:r1"}
    snapshot_record = next(row for row in manifest["records"] if row["artifact_id"] == "result-input:r1")
    raw = producer[1].parent.parent.joinpath(*snapshot_record["path"]).read_bytes()
    snapshot = json.loads(raw)
    assert b"_server_owned_validation_receipts" not in raw
    for fact in envelope["numeric_facts"]:
        source = fact["source_selector"]
        assert source["artifact_ref"] == "result-input:r1"
        assert source["artifact_digest"] == hashlib.sha256(raw).hexdigest()
        # Selectors use unambiguous JSON bracket segments, including quoted model IDs.
        import re
        value = snapshot
        for token in re.findall(r'\[("(?:[^"\\]|\\.)*"|\d+)\]', source["selector"]):
            value = value[json.loads(token)]
        assert value == fact["value"], source
    assert all(f["validation_level"] == "none" and not f["oracle_checks"] for f in envelope["numeric_facts"])
    verify_result_dependencies(producer[0]._project_file_store, manifest, project_ref="project:sections", run_id="r1")


def test_sealed_snapshot_not_late_diagnostic_summary(producer):
    envelope = prepare(producer)
    write_json(producer[1] / "diagnostic_summary.json", {"late": "render complete"})
    manifest = envelope["family_evidence"]["result_dependencies"]
    verify_result_dependencies(producer[0]._project_file_store, manifest, project_ref="project:sections", run_id="r1")
    assert prepare(producer) == envelope
    with pytest.raises(Exception):
        prepare(producer, report_fields={"descriptive_stats": [{"mean": 999.0}]})


@pytest.mark.parametrize("attack", ["model_bytes", "model_and_index", "snapshot", "symlink"])
def test_snapshot_or_model_tamper_rejected(producer, attack):
    envelope = prepare(producer)
    run = producer[1]
    manifest = envelope["family_evidence"]["result_dependencies"]
    row = next(r for r in manifest["records"] if r["artifact_id"] == ("result-input:r1" if attack == "snapshot" else "ols_1"))
    path = run.parent.parent.joinpath(*row["path"])
    if attack == "symlink":
        path.unlink()
        path.symlink_to(run / "artifacts_index.json")
    else:
        path.write_bytes(b'{"changed":true}')
        if attack == "model_and_index":
            index_path = run / "artifacts_index.json"
            index = json.loads(index_path.read_text())
            next(r for r in index["artifacts"] if r["artifact_id"] == "ols_1")["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            write_json(index_path, index)
    with pytest.raises(Exception):
        verify_result_dependencies(producer[0]._project_file_store, manifest, project_ref="project:sections", run_id="r1")


def test_missing_sections_are_explicit(producer):
    envelope = prepare(producer, report_fields={}, diagnostic_summary={})
    by_id = {s["section_id"]: s for s in envelope["family_evidence"]["structured_results"]["sections"]}
    for name in ("descriptive_statistics", "statistical_tests", "diagnostics", "interpretation_constraints", "variable_importance"):
        assert by_id[name]["status"] == "unavailable"
        assert by_id[name]["reason_codes"]
        assert by_id[name]["content"] == {"kind": "null"}


@pytest.mark.parametrize("value", [float("nan"), "x" * 4097, list(range(17000))])
def test_unbounded_or_invalid_producer_input_rejected_before_snapshot(producer, value):
    with pytest.raises((ValueError, TypeError)):
        prepare(producer, report_fields={"descriptive_stats": [{"mean": value}]})
    assert not (producer[1] / "result_input.json").exists()


def test_failed_workflow_keeps_status_without_numeric_release(producer):
    envelope = prepare(producer, issue_dicts=[{"severity": "ERROR", "code": "FIT_FAILED", "message": "fit failed"}],
        diagnostic_summary={"run_status": {"model_fit_status": "failed", "report_render_status": "pending"}})
    assert envelope["execution_status"] == "failed"
    assert envelope["numeric_facts"] == []
    assert sections(envelope)["workflow_status"]["steps"][0]["status"] == "failed"


def test_pure_numeric_builder_never_fabricates_interval_method_or_level():
    envelope = build_workflow_report_evidence_envelope(run_id="r1", model_run_id="ols_1", upload_hash="a" * 64,
        primary_model_type="ols", regression_table={"models": [{"id": "ols_1", "nobs": 30}],
            "rows": [{"term": "x", "models": {"ols_1": {"estimate": 1.0, "confidence_interval": [0.1, 1.9], "p_value": 0.05}}}]})
    fact = envelope["numeric_facts"][0]
    assert fact["confidence_interval"]["status"] == "not_applicable"
    assert fact["confidence_level"]["status"] == "not_applicable"
    assert fact["test_direction"]["status"] == "not_applicable"
    assert "structured_results" not in envelope["family_evidence"]


def test_report_stage_has_no_raw_arma_family_append():
    import ast
    import inspect
    import textwrap
    from workbench.engine.stages.report import ReportStage
    tree = ast.parse(textwrap.dedent(inspect.getsource(ReportStage.run)))
    calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert "build_arma_garch_report_document" not in calls
    assert "build_report_view_model" in calls


def test_family_projection_never_embeds_whole_model(producer):
    factory, run, packet = producer
    packet.update(r_squared=0.8, _private_path="/private/not-for-consumers", prediction_rows=list(range(100)))
    write_json(run / "model_results" / "ols_1.json", packet)
    index = json.loads((run / "artifacts_index.json").read_text())
    index["artifacts"][0]["sha256"] = hashlib.sha256((run / "model_results" / "ols_1.json").read_bytes()).hexdigest()
    write_json(run / "artifacts_index.json", index)
    envelope = prepare(producer)
    family = sections(envelope)["model_family_evidence"]
    assert family["results"] == {"ols_1": {"r_squared": 0.8}}
    assert "not-for-consumers" not in json.dumps(envelope)
    assert len(envelope["numeric_facts"]) < 40


def test_non_model_section_has_independent_dependency_closure(producer):
    envelope = prepare(producer)
    section = next(s for s in envelope["family_evidence"]["structured_results"]["sections"]
                   if s["section_id"] == "descriptive_statistics")
    assert section["dependency_refs"] == ["result-input:r1"]
    (producer[1] / "model_results" / "ols_1.json").write_bytes(b"tampered")
    verify_result_dependencies(producer[0]._project_file_store, envelope["family_evidence"]["result_dependencies"],
        project_ref="project:sections", run_id="r1", dependency_ids=section["dependency_refs"])


def test_arma_family_without_coefficients_uses_declared_results(producer):
    factory, run, packet = producer
    packet.clear()
    packet.update(model_id="ols_1", model_type="time_series.arma_garch", nobs=30,
        status="passed", selected_specification={"arma": {"p": 1, "q": 0}},
        estimation_strategy="two_step", resolved_strategy="two_step", joint_likelihood=False,
        artifact_refs={"internal": "/private/model/path"})
    write_json(run / "model_results" / "ols_1.json", packet)
    index = json.loads((run / "artifacts_index.json").read_text())
    index["artifacts"][0]["sha256"] = hashlib.sha256((run / "model_results" / "ols_1.json").read_bytes()).hexdigest()
    write_json(run / "artifacts_index.json", index)
    envelope = prepare(producer, primary_model_type="time_series.arma_garch")
    family = sections(envelope)["model_family_evidence"]
    assert family["results"]["ols_1"]["selected_specification"]["arma"]["p"] == 1
    assert "artifact_refs" not in json.dumps(envelope)


def test_missing_interval_metadata_is_explicit_in_sections(producer):
    _, run, packet = producer
    for key in ("confidence_interval_method", "confidence_level", "reference_distribution"):
        packet["coefficients"]["x"].pop(key)
    write_json(run / "model_results" / "ols_1.json", packet)
    index = json.loads((run / "artifacts_index.json").read_text())
    index["artifacts"][0]["sha256"] = hashlib.sha256((run / "model_results" / "ols_1.json").read_bytes()).hexdigest()
    write_json(run / "artifacts_index.json", index)
    envelope = prepare(producer)
    cell = sections(envelope)["regression_table"]["rows"][0]["models"]["ols_1"]
    assert cell["confidence_interval"] == [0.8, 1.8]
    assert cell["confidence_interval_method"]["status"] == "unavailable"
    assert cell["confidence_level"]["status"] == "unavailable"


def test_late_issue_is_not_silently_dropped_by_numeric_builder():
    envelope = build_workflow_report_evidence_envelope(run_id="r1", model_run_id="ols_1", upload_hash="a" * 64,
        primary_model_type="ols", regression_table={"models": [{"id": "ols_1", "nobs": 30}],
            "rows": [{"term": "x", "models": {"ols_1": {"estimate": 1.0}}}]},
        issue_dicts=[{"code": f"NOTE_{i}", "message": "note", "severity": "INFO"} for i in range(16)] +
                    [{"code": "LAST_BLOCKER", "message": "must not disappear", "severity": "ERROR"}])
    assert envelope["execution_status"] == "failed"
    assert envelope["numeric_facts"] == []
    assert "LAST_BLOCKER" in {warning["code"] for warning in envelope["warnings"]}


def test_survey_section_ignores_unrelated_model_source(producer):
    _, run, packet = producer
    other = {"model_id": "other", "model_type": "ols", "nobs": 20,
             "coefficients": {"x": {"estimate": 2.0}}}
    write_json(run / "model_results" / "other.json", other)
    register_artifact(run, "other", run / "model_results" / "other.json", "model_result", "econometrics", [])
    table = build_regression_table([("ols_1", packet), ("other", other)])
    envelope = prepare(producer, regression_table=table, model_artifact_ids=["ols_1", "other"])
    section = next(s for s in envelope["family_evidence"]["structured_results"]["sections"] if s["section_id"] == "survey_design")
    assert section["dependency_refs"] == ["result-input:r1", "ols_1"]
    (run / "model_results" / "other.json").write_bytes(b"tamper")
    verify_result_dependencies(producer[0]._project_file_store, envelope["family_evidence"]["result_dependencies"],
        project_ref="project:sections", run_id="r1", dependency_ids=section["dependency_refs"])


def test_regression_model_metadata_preserved_separately_from_identity(producer):
    _, run, packet = producer
    packet.update(r_squared=0.8, adjusted_r_squared=0.75)
    write_json(run / "model_results" / "ols_1.json", packet)
    index = json.loads((run / "artifacts_index.json").read_text())
    index["artifacts"][0]["sha256"] = hashlib.sha256((run / "model_results" / "ols_1.json").read_bytes()).hexdigest()
    write_json(run / "artifacts_index.json", index)
    table = build_regression_table([("ols_1", packet)])
    envelope = prepare(producer, regression_table=table)
    decoded = sections(envelope)
    model = decoded["regression_table"]["models"][0]
    assert model["r_squared"] == 0.8
    assert model["adjusted_r_squared"] == 0.75
    assert model["survey_design"] == table["models"][0]["survey_design"]
    assert model["survey_provenance"] == table["models"][0]["survey_provenance"]
    assert "r_squared" not in decoded["model_identity"]["models"][0]


def test_versioned_lmm_source_uses_actual_artifact_binding(producer):
    from tests.test_lmm_result_adapter import _complete_payload, _envelope
    from workbench.engine.packs.linear_mixed_effects.runner import _TERMINAL_RESULT_ARTIFACT_ID, _TERMINAL_RESULT_PATH
    _, run, _ = producer
    payload = _complete_payload()
    payload["execution_binding"]["run_id"] = "r1"
    write_json(run / _TERMINAL_RESULT_PATH, _envelope(payload))
    register_artifact(run, _TERMINAL_RESULT_ARTIFACT_ID, run / _TERMINAL_RESULT_PATH, "model_result_packet", "linear_mixed_effects", [])
    envelope = prepare(producer, model_run_id=payload["model_id"], primary_model_type="linear_mixed_effects",
        model_artifact_ids=[_TERMINAL_RESULT_ARTIFACT_ID], regression_table=build_regression_table([(payload["model_id"], payload)]))
    by_id = {s["section_id"]: s for s in envelope["family_evidence"]["structured_results"]["sections"]}
    assert by_id["regression_table"]["dependency_refs"] == ["result-input:r1", _TERMINAL_RESULT_ARTIFACT_ID]
    assert sections(envelope)["regression_table"]["rows"][0]["models"][payload["model_id"]]["estimate"] == 0.8
    factory = producer[0]
    receipt = factory.issue_production_receipt(run_id="r1", model_run_id=payload["model_id"], upload_hash="a" * 64)
    owner = factory.create_for_run(run_id="r1", model_run_id=payload["model_id"], production_receipt=receipt,
        envelope=envelope, artifact_file_sha256=factory.report_evidence_file_sha256(envelope))
    cell = sections(owner._canonical_report_artifact().envelope.to_dict())["regression_table"]["rows"][0]["models"][payload["model_id"]]
    assert cell["inference_method"] == payload["coefficients"]["group_time_interaction"]["inference_method"]
    for key, value in payload["coefficients"]["group_time_interaction"].items():
        assert cell[key] == value, key


def test_real_receipt_validates_only_coefficients_after_c0_commit(producer):
    import statsmodels.api as sm
    from workbench.report_view_model import build_server_owned_ols_validation_receipt
    factory, run, _ = producer
    fitted = sm.OLS([1.0, 2.1, 3.2, 3.8, 5.3, 6.0], sm.add_constant(list(range(6)))).fit()
    packet = {"model_id": "ols_1", "model_type": "ols", "model": "ols", "engine": "statsmodels",
        "contract_version": "ols_result_contract_v1", "nobs": 6, "coefficients": {
            term: {"estimate": float(fitted.params[i]), "p_value": float(fitted.pvalues[i]), "std_error": float(fitted.bse[i])}
            for i, term in enumerate(fitted.model.exog_names)}}
    write_json(run / "model_results" / "ols_1.json", packet)
    index = json.loads((run / "artifacts_index.json").read_text())
    index["artifacts"][0]["sha256"] = hashlib.sha256((run / "model_results" / "ols_1.json").read_bytes()).hexdigest()
    write_json(run / "artifacts_index.json", index)
    receipt = build_server_owned_ols_validation_receipt(run_id="r1", model_id="ols_1", model_result=packet,
        fitted=fitted, input_digest="a" * 64)
    assert receipt is not None
    table = build_regression_table([("ols_1", packet)], validation_receipts={"ols_1": receipt})
    envelope = prepare(producer, regression_table=table)
    coeffs = [fact for fact in envelope["numeric_facts"] if fact["statistic_id"] == "model_coefficient"]
    assert len(coeffs) == 2
    assert all(fact["validation_level"] == "same_library_regression" for fact in coeffs)
    assert all(fact["validation_level"] == "none" and not fact["oracle_checks"]
               for fact in envelope["numeric_facts"] if fact["statistic_id"] != "model_coefficient")
    production = factory.issue_production_receipt(run_id="r1", model_run_id="ols_1", upload_hash="a" * 64)
    owner = factory.create_for_run(run_id="r1", model_run_id="ols_1", production_receipt=production,
        envelope=envelope, artifact_file_sha256=factory.report_evidence_file_sha256(envelope))
    assert owner._canonical_report_artifact().envelope.to_dict() == envelope


def _persist_producer_packet(producer):
    _, run, packet = producer
    write_json(run / "model_results" / "ols_1.json", packet)
    index = json.loads((run / "artifacts_index.json").read_text())
    index["artifacts"][0]["sha256"] = hashlib.sha256((run / "model_results" / "ols_1.json").read_bytes()).hexdigest()
    write_json(run / "artifacts_index.json", index)


@pytest.mark.parametrize("location", ["coefficient", "interval", "distribution", "fit", "fit_coefficient", "bootstrap"])
def test_private_fields_never_reach_committed_sections(producer, location):
    factory, _, packet = producer
    coefficient = packet["coefficients"]["x"]
    # A legitimate term resembling a private field must remain a dynamic key.
    packet["coefficients"]["_private_path"] = {"estimate": 2.5, "p_value": 1e-22}
    packet["model_type"] = "quantile_regression"
    packet["quantiles"] = [0.5]
    packet["fits"] = {"0.5": {"quantile": 0.5, "coefficients": copy.deepcopy(packet["coefficients"])}}
    packet["bootstrap"] = {"repetitions": 20, "intervals": {"0.5": {"_private_path": [1.0, 3.0]}}}
    targets = {
        "coefficient": coefficient,
        "distribution": packet["fits"]["0.5"]["coefficients"]["x"]["reference_distribution"],
        "fit": packet["fits"]["0.5"],
        "fit_coefficient": packet["fits"]["0.5"]["coefficients"]["x"],
        "bootstrap": packet["bootstrap"],
    }
    if location == "interval":
        packet["fits"]["0.5"]["coefficients"]["x"]["confidence_interval"] = {"lower": 0.8, "upper": 1.8, "method": "percentile_bootstrap",
                                               "_private_path": "PRIVATE_SENTINEL"}
    else:
        targets[location]["_private_path"] = "PRIVATE_SENTINEL"
    _persist_producer_packet(producer)
    envelope = prepare(producer, primary_model_type="quantile_regression")
    receipt = factory.issue_production_receipt(run_id="r1", model_run_id="ols_1", upload_hash="a" * 64)
    owner = factory.create_for_run(run_id="r1", model_run_id="ols_1", production_receipt=receipt,
        envelope=envelope, artifact_file_sha256=factory.report_evidence_file_sha256(envelope))
    committed = owner._canonical_report_artifact().envelope.to_dict()
    assert "PRIVATE_SENTINEL" not in json.dumps(committed)
    decoded = sections(committed)
    rows = {row["term"]: row for row in decoded["regression_table"]["rows"]}
    assert rows["_private_path"]["models"]["ols_1"]["estimate"] == 2.5
    fit = decoded["model_family_evidence"]["results"]["ols_1"]["fits"]["0.5"]
    assert fit["coefficients"]["_private_path"]["p_value"] == 1e-22


@pytest.mark.parametrize("field,value", [
    ("survey_design", {"degf": 999, "variance_method": "FORGED_METHOD"}),
    ("survey_provenance", {"degf": 999, "variance_method": "FORGED_METHOD"}),
    ("r_squared", 0.999), ("nobs", 999),
])
def test_contradictory_table_metadata_rejected_before_snapshot(producer, field, value):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    table = build_regression_table([("ols_1", producer[2])])
    table["models"][0][field] = value
    with pytest.raises(EvidenceProjectionError) as error:
        prepare(producer, regression_table=table)
    assert error.value.code == "REPORT_RESULT_INPUT_INVALID"
    assert not (producer[1] / "result_input.json").exists()


def test_missing_table_metadata_reconstructed_from_actual_source(producer):
    table = build_regression_table([("ols_1", producer[2])])
    expected = copy.deepcopy(table["models"][0])
    del table["models"][0]["survey_design"]
    del table["models"][0]["survey_provenance"]
    decoded = sections(prepare(producer, regression_table=table))
    actual = decoded["regression_table"]["models"][0]
    assert actual["survey_design"] == expected["survey_design"]
    assert actual["survey_provenance"] == expected["survey_provenance"]


def test_recursive_schema_preserves_actual_arma_spec_and_diagnostic_display(producer):
    _, _, packet = producer
    spec = {"split_hash": "a" * 64, "mean_candidate_id": "arma-1-0", "mean_order": [1, 0],
            "mean_constant": True, "variance_candidate_id": "garch-1-1", "variance_model": "garch",
            "variance_order": [1, 1], "innovation_distribution": "normal", "resolved_strategy": "two_step",
            "hold_back": 1, "transform": "level", "refit_every": 1}
    packet.update(model_type="time_series.arma_garch", selected_specification={**spec, "_private_path": "PRIVATE_SENTINEL"})
    packet["model_label"] = "My model display name"
    _persist_producer_packet(producer)
    issue = {"message": "Measured warning", "template_key": "high_vif",
             "template_params": {"variable": "x", "vif": 12.5}, "variables": ["_private_path", "x"]}
    envelope = prepare(producer, primary_model_type="time_series.arma_garch",
        diagnostic_summary={"diagnostics": {"warnings": [issue]}, "run_status": {"report_render_status": "pending"}})
    decoded = sections(envelope)
    assert decoded["model_family_evidence"]["results"]["ols_1"]["selected_specification"] == spec
    assert decoded["diagnostics"]["warnings"] == [issue]
    assert decoded["model_identity"]["models"][0]["label"] == "My model display name"


def test_actual_poisson_coefficient_fields_survive_c0(producer):
    import numpy as np
    import pandas as pd
    from workbench.econometrics.runner import run_poisson
    factory, _, packet = producer
    rng = np.random.default_rng(42)
    x = rng.uniform(0, 5, 100)
    result, _ = run_poisson(pd.DataFrame({"x": x, "y": rng.poisson(np.exp(-0.5 + 0.3 * x))}),
                            y="y", x=["x"], model_id="ols_1")
    assert all(result["coefficients"]["x"][key] is not None for key in ("irr", "irr_ci_lower", "irr_ci_upper"))
    packet.clear()
    packet.update(result)
    _persist_producer_packet(producer)
    envelope = prepare(producer, primary_model_type=result["model_type"])
    prepared_rows = {row["term"]: row for row in sections(envelope)["regression_table"]["rows"]}
    for key in ("irr", "irr_ci_lower", "irr_ci_upper"):
        assert prepared_rows["x"]["models"]["ols_1"][key] == result["coefficients"]["x"][key]
    receipt = factory.issue_production_receipt(run_id="r1", model_run_id="ols_1", upload_hash="a" * 64)
    owner = factory.create_for_run(run_id="r1", model_run_id="ols_1", production_receipt=receipt,
        envelope=envelope, artifact_file_sha256=factory.report_evidence_file_sha256(envelope))
    committed = owner._canonical_report_artifact().envelope.to_dict()
    rows = {row["term"]: row for row in sections(committed)["regression_table"]["rows"]}
    for term, source in result["coefficients"].items():
        for key, value in source.items():
            assert rows[term]["models"]["ols_1"][key] == value, (term, key)
    irr_facts = [fact for fact in committed["numeric_facts"] if '["irr' in fact["source_selector"]["selector"]]
    assert len(irr_facts) == 3 * len(result["coefficients"])
    assert all(fact["validation_level"] == "none" and not fact["oracle_checks"] for fact in irr_facts)


def test_all_sections_have_one_public_schema_boundary():
    from workbench.services import report_result_sections as module
    assert set(module.PUBLIC_RESULT_SECTION_SCHEMAS_V1) == set(SECTION_FIELDS)


_PRIVATE_ROUTES = {
    "model_identity": ("models", 0),
    "regression_table": ("rows", 0, "models", "ols_1"),
    "descriptive_statistics": ("rows", 0),
    "statistical_tests": ("results", 0),
    "survey_design": ("design", "ols_1"),
    "marginal_effects": ("rows", 0),
    "model_family_evidence": ("results", "ols_1"),
    "diagnostics": ("warnings", 0, "template_params"),
    "interpretation_constraints": ("constraints",),
    "variable_importance": ("rows", 0),
    "workflow_status": ("steps", 0),
}


@pytest.mark.parametrize("section_id", list(_PRIVATE_ROUTES))
def test_each_section_nested_private_record_cannot_cross_public_boundary(producer, monkeypatch, section_id):
    from workbench.services import report_result_sections as module
    factory, _, packet = producer
    packet.update(r_squared=0.75, survey_provenance={"producer": "survey_runner"})
    _persist_producer_packet(producer)
    original = module.project_public_result_sections_v1
    seen = []
    def inject(raw, **kwargs):
        seen.append(set(raw))
        poisoned = copy.deepcopy(raw)
        target = poisoned[section_id]
        for key in _PRIVATE_ROUTES[section_id]:
            target = target[key]
        target["_private_path"] = "PRIVATE_SENTINEL"
        projected = original(poisoned, **kwargs)
        assert projected == original(raw, **kwargs)
        return projected
    monkeypatch.setattr(module, "project_public_result_sections_v1", inject)
    issue = {"message": "Measured warning", "template_key": "high_vif",
             "template_params": {"variable": "x", "vif": 12.5}, "variables": ["x"]}
    envelope = prepare(producer, diagnostic_summary={"diagnostics": {"warnings": [issue]},
        "narrative_contract": {"constraints": {"causal_language_allowed": False}, "required_mentions": [], "forbidden_claims": []},
        "run_status": {"model_fit_status": "success", "report_render_status": "pending"}})
    assert seen == [set(SECTION_FIELDS)]
    receipt = factory.issue_production_receipt(run_id="r1", model_run_id="ols_1", upload_hash="a" * 64)
    owner = factory.create_for_run(run_id="r1", model_run_id="ols_1", production_receipt=receipt,
        envelope=envelope, artifact_file_sha256=factory.report_evidence_file_sha256(envelope))
    committed = owner._canonical_report_artifact().envelope.to_dict()
    assert "PRIVATE_SENTINEL" not in json.dumps(committed)
    assert sections(committed)["diagnostics"]["warnings"] == [issue]


@pytest.mark.parametrize("route", ["survey_design", "survey_provenance", "marginal_effects"])
def test_actual_source_private_fields_are_not_privacy_approved_by_sealing(producer, route):
    _, _, packet = producer
    if route == "survey_provenance":
        packet[route] = {"producer": "survey_runner"}
    target = packet[route][0] if route == "marginal_effects" else packet[route]
    target["_private_path"] = "PRIVATE_SENTINEL"
    _persist_producer_packet(producer)
    assert "PRIVATE_SENTINEL" not in json.dumps(prepare(producer))


def test_actual_source_identity_y_x_preserved(producer):
    _, _, packet = producer
    packet.update(y_variable="outcome", x_variables=["_private_path", "exposure/years"])
    _persist_producer_packet(producer)
    models = sections(prepare(producer))["model_identity"]["models"]
    assert models[0]["y_variable"] == packet["y_variable"]
    assert models[0]["x_variables"] == packet["x_variables"]


def test_unknown_template_keeps_message_but_not_unapproved_parameters(producer):
    issue = {"message": "Declared diagnostic message", "template_key": "unknown_template",
             "template_params": {"any_key": "PRIVATE_SENTINEL"}}
    envelope = prepare(producer, diagnostic_summary={"diagnostics": {"warnings": [issue]}})
    decoded = sections(envelope)["diagnostics"]["warnings"][0]
    assert decoded["message"] == issue["message"]
    assert not decoded.get("template_params")
    assert decoded["unavailable_reason"] == "PRODUCER_TEMPLATE_UNDECLARED"
    assert "PRIVATE_SENTINEL" not in json.dumps(envelope)


@pytest.mark.parametrize("discriminator", ["payload_schema", "contract"])
def test_unknown_business_packet_is_not_treated_as_generic_results(producer, discriminator):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    with pytest.raises(EvidenceProjectionError, match="REPORT_RESULT_INPUT_INVALID"):
        prepare(producer, report_fields={"statistical_evidence": {
            discriminator: "workbench.unknown.results", "schema_version": 1,
            "results": [{"statistic": 3.0, "meaningful_new_field": 4.0}]}})
    assert not (producer[1] / "result_input.json").exists()


def test_real_statistical_rows_and_descriptive_fields_preserved(producer):
    import pandas as pd
    from workbench.statistical_tests import _welch_t_test, _apply_multiple_testing_correction, posthoc_anova
    from workbench.orchestrator._report_build import _build_descriptive_stats
    frame = pd.DataFrame({"outcome": [1., 2., 3., 5., 7., 8.], "group": ["_private_path"] * 3 + ["B"] * 3})
    frame.attrs["value_labels"] = {"group": {"_private_path": "Public group label", "B": "Other"}}
    descriptive = _build_descriptive_stats(frame)
    test = _welch_t_test(frame, "outcome", "group")
    posthoc = posthoc_anova({"_private_path": [1., 2., 3.], "B": [5., 7., 8.]}, correction="bonferroni")
    _apply_multiple_testing_correction({"tests": {"results": [test, posthoc]}})
    envelope = prepare(producer, report_fields={"descriptive_stats": descriptive,
        "statistical_evidence": {"results": [test, posthoc]}})
    decoded = sections(envelope)
    for actual, expected in zip(decoded["descriptive_statistics"]["rows"], descriptive, strict=True):
        assert set(actual) == set(expected)
        for key, value in expected.items():
            assert actual[key] == (value if value is not None else
                {"status": "unavailable", "reason": "PRODUCER_FIELD_UNDECLARED"})
    assert decoded["statistical_tests"]["results"] == [test, posthoc]


def test_real_ordinal_marginal_effect_category_map_preserved(producer):
    import numpy as np
    import pandas as pd
    from statsmodels.miscmodels.ordinal_model import OrderedModel
    from workbench.engine.packs.v186_model_families.runtime import _marginal_probability_effects
    rng = np.random.default_rng(12)
    x = pd.DataFrame({"x": rng.normal(size=60)})
    y = np.digitize(x["x"] + rng.normal(size=60), [-0.5, 0.5])
    model = OrderedModel(y, x, distr="logit")
    fitted = model.fit(method="bfgs", disp=False)
    rows = _marginal_probability_effects(model, fitted.params, x, ["x"], ["low", "_private_path", "high"])
    producer[2].update(model_type="ordinal_logit", marginal_effects=rows)
    _persist_producer_packet(producer)
    decoded = sections(prepare(producer, primary_model_type="ordinal_logit"))["marginal_effects"]
    assert decoded["rows"] == [{**row, "model_id": "ols_1"} for row in rows]


def test_real_family_diagnostic_pointer_keeps_its_declared_contract(producer):
    from workbench.engine.stages.diagnostics import _family_owned_diagnostic
    pointer = _family_owned_diagnostic("ordinal_logit", "ols_1")
    producer[2]["model_type"] = "ordinal_logit"
    _persist_producer_packet(producer)
    decoded = sections(prepare(producer, primary_model_type="ordinal_logit", report_fields={"diagnostics": {"ols_1": pointer}}))
    assert decoded["diagnostics"]["results"]["ols_1"] == pointer


def test_unknown_diagnostic_contract_fails_instead_of_silently_losing_fields(producer):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    with pytest.raises(EvidenceProjectionError, match="REPORT_RESULT_INPUT_INVALID"):
        prepare(producer, report_fields={"diagnostics": {"ols_1": {
            "contract": "workbench.new_diagnostic.v9", "new_public_measure": 2.0}}})


@pytest.mark.parametrize("field,value", [("diagnostics", {"ols_1": "not-a-record"}),
                                         ("statistical_evidence", {"results": [None]})])
def test_public_record_shape_errors_are_typed_and_preseal(producer, field, value):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    with pytest.raises(EvidenceProjectionError, match="REPORT_RESULT_INPUT_INVALID"):
        prepare(producer, report_fields={field: value})
    assert not (producer[1] / "result_input.json").exists()


@pytest.mark.parametrize("section_id,content", [
    ("diagnostics", {"results": {"ols_1": "contract"}}),
    ("statistical_tests", []),
    ("diagnostics", {"results": {"ols_1": {"vif": 3}}}),
], ids=["diagnostic-string-discriminator", "statistics-list", "vif-number"])
def test_callable_shape_guards_are_typed_and_preseal(producer, monkeypatch, section_id, content):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    from workbench.services import report_result_sections as module

    original = module.project_public_result_sections_v1

    def malformed_section(sections, **kwargs):
        sections = {**sections, section_id: content}
        return original(sections, **kwargs)

    monkeypatch.setattr(module, "project_public_result_sections_v1", malformed_section)
    index_path = producer[1] / "artifacts_index.json"
    before = index_path.read_bytes()
    with pytest.raises(EvidenceProjectionError) as caught:
        prepare(producer)
    assert caught.value.code == "REPORT_RESULT_INPUT_INVALID"
    assert not (producer[1] / "result_input.json").exists()
    assert not (producer[1] / "report_evidence.json").exists()
    assert index_path.read_bytes() == before


@pytest.mark.parametrize("vif", [{"error": "insufficient observations"}, {"x": 2.5}])
def test_callable_shape_guards_preserve_declared_vif_records(producer, vif):
    envelope = prepare(producer, report_fields={"diagnostics": {"ols_1": {"vif": vif}}})
    assert sections(envelope)["diagnostics"]["results"]["ols_1"]["vif"] == vif


def _commit_schema_probe(producer, **overrides):
    factory = producer[0]
    envelope = prepare(producer, **overrides)
    receipt = factory.issue_production_receipt(run_id="r1", model_run_id="ols_1", upload_hash="a" * 64)
    owner = factory.create_for_run(run_id="r1", model_run_id="ols_1", production_receipt=receipt,
        envelope=envelope, artifact_file_sha256=factory.report_evidence_file_sha256(envelope))
    return sections(owner._canonical_report_artifact().envelope.to_dict())


@pytest.mark.parametrize("value", [[], None, "invalid", 0, False])
def test_statistical_packet_present_invalid_rejected_prebuilder(producer, value):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    index = producer[1] / "artifacts_index.json"
    before = index.read_bytes()
    with pytest.raises(EvidenceProjectionError) as caught:
        prepare(producer, report_fields={"statistical_evidence": value})
    assert caught.value.code == "REPORT_RESULT_INPUT_INVALID"
    assert not (producer[1] / "result_input.json").exists()
    assert not (producer[1] / "report_evidence.json").exists()
    assert index.read_bytes() == before


def test_statistical_packet_absent_remains_undeclared_through_owner(producer):
    decoded = _commit_schema_probe(producer, report_fields={})
    assert decoded["statistical_tests"] is None


def test_correction_scope_exact_text_preserved_through_owner(producer):
    scope = "  All planned contrasts: café / β[x]  "
    decoded = _commit_schema_probe(producer, report_fields={"statistical_evidence": {
        "results": [{"test": "t", "p_value": 1e-30}], "correction_scope": scope}})
    assert decoded["statistical_tests"]["correction_scope"] == scope
    snapshot = json.loads((producer[1] / "result_input.json").read_bytes())
    assert snapshot["sections"]["statistical_tests"]["correction_scope"] == scope


@pytest.mark.parametrize("scope", [None, [], {}, True, 2, "bad\x00scope"])
def test_correction_scope_malformed_rejected_preseal(producer, scope):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    before = (producer[1] / "artifacts_index.json").read_bytes()
    with pytest.raises(EvidenceProjectionError) as caught:
        prepare(producer, report_fields={"statistical_evidence": {
            "results": [], "correction_scope": scope}})
    assert caught.value.code == "REPORT_RESULT_INPUT_INVALID"
    assert not (producer[1] / "result_input.json").exists()
    assert (producer[1] / "artifacts_index.json").read_bytes() == before


@pytest.mark.parametrize("parameters", [{"debug_context": "PRIVATE_SENTINEL"}, {"undeclared": 3.5}])
def test_distribution_undeclared_parameters_rejected_before_owner_commit(producer, parameters):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    producer[2]["coefficients"]["x"]["reference_distribution"]["parameters"] = parameters
    _persist_producer_packet(producer)
    with pytest.raises(EvidenceProjectionError, match="REPORT_RESULT_INPUT_INVALID"):
        _commit_schema_probe(producer)


def test_distribution_declared_t_degrees_of_freedom_preserved_through_owner(producer):
    distribution = {"name": "t", "degrees_of_freedom": 12.5, "parameters": {}}
    producer[2]["coefficients"]["x"]["reference_distribution"] = distribution
    _persist_producer_packet(producer)
    decoded = _commit_schema_probe(producer)
    assert decoded["regression_table"]["rows"][0]["models"]["ols_1"]["reference_distribution"] == distribution


@pytest.mark.parametrize("route", ["statistical_row", "family_diagnostics"])
def test_unknown_nested_producer_contract_rejected_before_owner_commit(producer, route):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    if route == "statistical_row":
        fields = {"statistical_evidence": {"results": [{"contract": "workbench.unknown.v9",
            "test": "new", "statistic": 3.5, "new_measure": 4.0}]}}
        family = "ols"
    else:
        family = "ordinal_logit"
        producer[2]["model_type"] = family
        _persist_producer_packet(producer)
        fields = {"model_family_evidence": {"contract": "workbench.unknown.v9",
            "parallel_lines": {"status": "computed", "slope_ranges": {"x": 0.5}}}}
    with pytest.raises(EvidenceProjectionError, match="REPORT_RESULT_INPUT_INVALID"):
        _commit_schema_probe(producer, primary_model_type=family, report_fields=fields)


@pytest.mark.parametrize("route", ["hazard_ratios", "slope_ranges", "coefficients", "successful_repetitions"])
@pytest.mark.parametrize("value", ["PRIVATE_SENTINEL", 3.5], ids=["reject-text", "preserve-number"])
def test_data_keyed_numeric_map_semantics_through_owner(producer, route, value):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    # A data label is not a fixed record field; preserve it without key heuristics.
    key = "_private_path/β[x]"
    fields = {}
    if route == "hazard_ratios":
        family = "survival_cox"
        producer[2][route] = {key: value}
    elif route == "successful_repetitions":
        family = "quantile_regression"
        producer[2]["bootstrap"] = {route: {key: value}}
    else:
        family = "ordinal_logit"
        parallel = {"slope_ranges": {key: value}} if route == "slope_ranges" else {
            "comparisons": [{"threshold": 1, "coefficients": {key: value}}]}
        fields = {"model_family_evidence": {"contract": "workbench.ordinal_logit.diagnostics.v1",
            "model_type": family, "parallel_lines": parallel}}
    producer[2]["model_type"] = family
    _persist_producer_packet(producer)
    if isinstance(value, str):
        with pytest.raises(EvidenceProjectionError, match="REPORT_RESULT_INPUT_INVALID"):
            _commit_schema_probe(producer, primary_model_type=family, report_fields=fields)
    else:
        decoded = _commit_schema_probe(producer, primary_model_type=family, report_fields=fields)["model_family_evidence"]
        if route == "hazard_ratios":
            actual = decoded["results"]["ols_1"][route]
        elif route == "successful_repetitions":
            actual = decoded["results"]["ols_1"]["bootstrap"][route]
        elif route == "slope_ranges":
            actual = decoded["diagnostics"]["parallel_lines"][route]
        else:
            actual = decoded["diagnostics"]["parallel_lines"]["comparisons"][0][route]
        assert actual == {key: value}
