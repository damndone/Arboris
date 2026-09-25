from __future__ import annotations

import hashlib
import importlib
import json
import copy
from concurrent.futures import ThreadPoolExecutor
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_FIXTURE = Path(__file__).parent / "fixtures" / "contracts" / "v189" / "evidence_envelope.json"


def _envelope(*, artifact_id: str) -> dict[str, object]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    run_id = artifact_id.removeprefix("report:")
    payload["result_identity"] = {
        "result_ref": f"report-result:{run_id}",
        "run_id": run_id,
        "model_run_id": "ols_1",
        "schema_version": "1.0",
    }
    for fact in payload["numeric_facts"]:
        fact["source_selector"]["artifact_ref"] = artifact_id
    return payload


def _factory_type():
    try:
        module = importlib.import_module("workbench.services.report_evidence_owner_factory")
    except ModuleNotFoundError as exc:
        pytest.fail(f"report owner factory module is missing: {exc.name}")
    return getattr(module, "ServerOwnedReportEvidenceOwnerFactoryV1")


@pytest.mark.parametrize("path", ["initial", "canonical", "read_bound"])
def test_report_owner_without_host_classification_is_unknown(tmp_path, path):
    from tests.test_v189_structured_consumer_projection import committed, owner_for
    from workbench.contracts.agent.context_egress import SensitivityClassV1
    with committed(tmp_path) as (_, _, _, _, kwargs, args):
        owner = owner_for(kwargs, args)
        if path == "initial":
            source = owner._canonical_record
        elif path == "canonical":
            source = owner._canonical_report_source_and_artifact()[0]
        else:
            artifact = args[1].get(owner.artifact_id, scope_ref=owner.scope_ref)
            source = owner.read_bound(owner.commit_id, actor_ref=owner.actor_ref,
                project_ref=owner.project_ref, session_ref=owner.session_ref, scope_ref=owner.scope_ref,
                artifact_id=owner.artifact_id, run_id=owner.run_id, model_run_id=owner.model_run_id,
                content_hash=artifact.content_hash, admission_ref=owner.artifact_id,
                confirmation_ref=owner.confirmation_ref, artifact_file_sha256=owner.artifact_file_sha256)
        assert source._sensitivity_policy.sensitivity is SensitivityClassV1.UNKNOWN


@pytest.mark.parametrize("consumer", ["agent", "notebook", "report", "results"])
def test_unknown_owner_local_reads_keep_numeric_sections_and_pages(tmp_path, consumer):
    from tests.test_v189_structured_consumer_projection import committed, owner_for
    from workbench.evidence.consumer_adapters import default_projection_registry, parse_result_section_bundle
    from workbench.services import results_service as service
    from workbench.contracts.common.envelope import thaw_json
    import base64
    with committed(tmp_path) as (_, run, _, sections, kwargs, args):
        owner = owner_for(kwargs, args)
        source = owner._canonical_report_source_and_artifact()[0]
        service.configure_report_evidence_persistence(owner)
        try:
            for selection in ({"requested_fact_ids": ["fact-mean"]},
                              {"requested_section_ids": ["a"], "requested_fact_ids": []}):
                wire = service.read_persisted_consumer_evidence_for_run(consumer_id=consumer,
                    project_root=run.parent.parent, run_id="r1", **selection)
                assert wire["status"] == "available", wire
                assert [f["fact_id"] for f in wire["facts"]] == ["fact-mean"]
                assert wire["facts"][0]["value"] == _envelope(artifact_id="report:r1")["numeric_facts"][0]["value"]
                assert wire["receipt"] and wire["authority"] == "server-owned"
                assert "local_unknown" in wire["audit"]["policy_ref"]["logical_id"]
                assert wire["sections"] == ([sections[0]] if "requested_section_ids" in selection else [])
            admission = default_projection_registry().prepare_local_result_page_admission(
                source, consumer_id=consumer, section_id="a")
            chunks, offset = [], 0
            while offset is not None:
                page = admission.page(offset=offset)["page"]
                chunks.append(base64.b64decode(page["payload_base64"]))
                offset = page["next_offset"]
            bundle = parse_result_section_bundle(b"".join(chunks))
            assert thaw_json(bundle["section"]) == sections[0]
        finally:
            service.configure_report_evidence_persistence(None)


def test_run_result_page_service_binds_owner_and_fails_without_content(tmp_path, monkeypatch):
    from tests.test_v189_evidence_report_boundary import _produced_report
    from workbench.canonical import canonical_json_v1, sha256_canonical
    from workbench.services import results_service as api

    read = getattr(api, "read_persisted_consumer_result_page_for_run", None)
    assert callable(read), "run-bound local page service is missing"
    monkeypatch.setattr(api, "_REPORT_EVIDENCE_OWNER_CATALOG", {})
    monkeypatch.setattr(api, "_REPORT_EVIDENCE_PERSISTENCE", api.UnavailableReportEvidenceCapabilityV1())
    monkeypatch.setattr(api, "_REPORT_EVIDENCE_OWNER_REHYDRATOR", None)
    run = tmp_path / "project" / "runs" / "page-service"
    packet = {"model_id": "ols_1", "model_type": "ols", "nobs": 20,
              "coefficients": {"统计🧪": {"estimate": 1.25, "std_error": .2, "p_value": 1e-20}}}
    query = dict(consumer_id="report", project_root=run.parent.parent, run_id=run.name,
                 section_id="regression_table", offset=0, max_wire_bytes=8192)

    def unavailable(result, reason=None):
        assert result["status"] == result["availability"] == "unavailable", result
        assert result["facts"] == [] and result["receipt"] is None
        assert not {"delivery", "page", "sections", "payload_base64"} & result.keys()
        if reason is not None:
            assert result["reason_code"] == reason

    with _produced_report(run, model_results={"ols_1": packet}, diagnostic_summary={}) as case:
        api.register_report_evidence_owner(case.owner)
        wire = read(**query)
        assert wire["read_completeness"] == "PARTIAL", wire
        assert wire["completion_scope"] == "section" and wire["destination"] == "local"
        identity = case.owner._require_report_request_identity(None)
        assert wire["identity"] == {key: getattr(identity, key) for key in (
            "actor_ref", "project_ref", "session_ref", "scope_ref", "run_id", "model_run_id", "confirmation_ref")}
        assert wire["receipt"]["identity"] == wire["identity"]
        assert wire["receipt"]["kind"] == "evidence.report.page-receipt.v1"
        assert wire["receipt"]["wire_digest"] == sha256_canonical({k: v for k, v in wire.items() if k != "receipt"})
        assert len(canonical_json_v1(wire).encode("utf-8")) <= 8192
        next_offset = wire["delivery"]["page"]["next_offset"]
        assert type(next_offset) is int and next_offset > 0
        for consumer in ("agent", "notebook"):
            consumer_page = read(**{**query, "consumer_id": consumer})
            assert consumer_page["read_completeness"] == "PARTIAL", consumer_page
            assert consumer_page["identity"] == wire["identity"]
            assert consumer_page["consumer_id"] == consumer
            assert consumer_page["destination"] == consumer_page["delivery"]["destination"] == "local"
            assert consumer_page["receipt"]["kind"] == f"evidence.{consumer}.page-receipt.v1"
            assert len(canonical_json_v1(consumer_page).encode("utf-8")) <= 8192
        for change, reason in (
            ({"consumer_id": "unknown-consumer"}, "PROJECTION_CONSUMER_UNKNOWN"),
            ({"consumer_id": []}, "EVIDENCE_CONSUMER_REQUIRED"),
            ({"project_root": tmp_path / "foreign"}, "EVIDENCE_OWNER_CONTEXT_CONFLICT"),
            ({"project_root": None}, "EVIDENCE_OWNER_CONTEXT_CONFLICT"),
            ({"run_id": "foreign-run"}, None),
            ({"run_id": "../page-service"}, None),
            ({"run_id": str(run)}, None),
            ({"run_id": "../runs/page-service"}, None),
            ({"run_id": ""}, "EVIDENCE_RUN_ID_REQUIRED"),
            ({"section_id": "foreign-section"}, None),
            ({"offset": -1}, None),
            ({"max_wire_bytes": 100}, "RESULT_PAGE_BUDGET_EXCEEDED"),
            ({"max_wire_bytes": 10**9}, "RESULT_PAGE_BUDGET_EXCEEDED"),
        ):
            unavailable(read(**{**query, **change}), reason)
        for forbidden in ("owner", "request_identity", "destination"):
            with pytest.raises(TypeError):
                read(**query, **{forbidden: "remote"})
        (run / "model_results" / "ols_1.json").write_text("changed source", encoding="utf-8")
        unavailable(read(**{**query, "offset": next_offset}))
    unavailable(read(**query), "EVIDENCE_OWNER_CONTEXT_CONFLICT")


def test_run_result_page_service_rehydrates_only_without_catalog_conflict(tmp_path, monkeypatch):
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from tests.test_v189_evidence_report_boundary import _produced_report
    from workbench.services import results_service as api

    read = getattr(api, "read_persisted_consumer_result_page_for_run", None)
    assert callable(read), "run-bound local page service is missing"
    monkeypatch.setattr(api, "_REPORT_EVIDENCE_OWNER_CATALOG", {})
    monkeypatch.setattr(api, "_REPORT_EVIDENCE_PERSISTENCE", api.UnavailableReportEvidenceCapabilityV1())
    monkeypatch.setattr(api, "_REPORT_EVIDENCE_OWNER_REHYDRATOR", None)
    packet = {"model_id": "ols_1", "model_type": "ols", "nobs": 20,
              "coefficients": {"x": {"estimate": 1.25}}}
    run = tmp_path / "project" / "runs" / "rehydrated-page"
    query = dict(consumer_id="report", project_root=run.parent.parent,
                 run_id=run.name, section_id="model_identity", offset=0)
    with _produced_report(run, model_results={"ols_1": packet}, diagnostic_summary={}) as case:
        calls = []
        def rehydrate(**kwargs):
            calls.append(kwargs)
            return case.owner

        api.configure_report_evidence_persistence(None)
        api.configure_report_evidence_owner_rehydrator(rehydrate)
        page = read(**query)
        assert page["read_completeness"] == "PARTIAL", page
        assert calls == [{"project_root": run.parent.parent, "run_id": run.name}]
        for change in ({"project_root": tmp_path / "foreign"}, {"run_id": "foreign"}):
            result = read(**{**query, **change})
            assert result["status"] == "unavailable" and "delivery" not in result
            assert result["reason_code"] == "EVIDENCE_OWNER_CONTEXT_MISMATCH"
        api.configure_report_evidence_persistence(case.owner)
        calls.clear()
        for change in ({"project_root": tmp_path / "foreign"}, {"run_id": "foreign"}):
            result = read(**{**query, **change})
            assert result["reason_code"] == "EVIDENCE_OWNER_CONTEXT_MISMATCH"
            assert result["facts"] == [] and result["receipt"] is None and "delivery" not in result
        assert calls == [], "mismatched global owner must not fall through to rehydration"
        api.register_report_evidence_owner(case.owner)
        # A distinct real host identity creates a run-level ambiguity, rather
        # than failing earlier at exact-identity duplicate registration.
        registry, host = _authorized_registry("scope:page-conflict")
        other_root = tmp_path / "other-project"
        other_root.mkdir()
        store_root = tmp_path / "other-evidence"
        store_root.mkdir()
        with _admit_store(store_root, registry) as store:
            factory = _factory_type().from_host(store, registry,
                actor_ref="actor:page-conflict", project_ref="project:page-conflict",
                session_ref="session:page-conflict", scope_ref="scope:page-conflict",
                canonical_project_root=other_root, authority_handle=host.channel)
            try:
                other = factory.create_for_run(run_id=run.name, model_run_id="ols_1",
                    production_receipt=_production_receipt(factory, run_id=run.name),
                    envelope=_envelope(artifact_id=f"report:{run.name}"), artifact_file_sha256="a" * 64)
                api.register_report_evidence_owner(other)
                api.configure_report_evidence_persistence(case.owner)
                calls.clear()
                result = read(**query)
                assert result["reason_code"] == "EVIDENCE_OWNER_CONTEXT_CONFLICT", result
                assert result["facts"] == [] and result["receipt"] is None and "delivery" not in result
                assert calls == [], "catalog conflict must not invoke rehydration or global fallback"
            finally:
                factory.close()


def test_owner_section_pages_bind_full_identity_and_final_wire_budget(tmp_path):
    from dataclasses import replace
    from tests.test_v189_evidence_report_boundary import _produced_report
    from workbench.canonical import canonical_json_v1, sha256_canonical
    from workbench.contracts.evidence.result_pages import ResultPageV1, ResultPageAccumulatorV1
    from workbench.evidence.consumer_adapters import parse_result_section_bundle, EvidenceProjectionError
    run = tmp_path / "project" / "runs" / "paged-owner"
    packet = {"model_id": "ols_1", "model_type": "ols", "nobs": 20,
              "coefficients": {"统计🧪": {"estimate": 1.25, "std_error": .2, "p_value": 1e-20}}}
    with _produced_report(run, model_results={"ols_1": packet}, diagnostic_summary={}) as case:
        envelope = json.loads((run / "report_evidence.json").read_text())
        section = next(s for s in envelope["family_evidence"]["structured_results"]["sections"]
                       if s["section_type"] == "regression_table")
        identity = case.owner._require_report_request_identity(None)
        offset, acc, count = 0, None, 0
        while offset is not None:
            wire = case.owner.read_result_section_page(consumer_id="report", section_id=section["section_id"],
                offset=offset, request_identity=identity, max_wire_bytes=8192)
            assert len(canonical_json_v1(wire).encode()) <= 8192
            assert wire["identity"] == {k: getattr(identity, k) for k in
                ("actor_ref", "project_ref", "session_ref", "scope_ref", "run_id", "model_run_id", "confirmation_ref")}
            assert wire["receipt"]["wire_digest"] == sha256_canonical({k: v for k, v in wire.items() if k != "receipt"})
            assert wire["receipt"]["kind"] == "evidence.report.page-receipt.v1"
            assert wire["read_completeness"] == "PARTIAL"
            page = ResultPageV1.from_dict(wire["delivery"]["page"])
            if acc is None:
                acc = ResultPageAccumulatorV1(page.binding, max_total_bytes=1_000_000)
            acc.add(page)
            offset = page.next_offset
            count += 1
        assert count > 1
        assert acc.transport_complete
        bundle = parse_result_section_bundle(acc.finish())
        assert canonical_json_v1(bundle["section"]) == canonical_json_v1(section)
        assert set(bundle["section"]["fact_refs"]) == {f["fact_id"] for f in bundle["facts"]}
        with pytest.raises(EvidenceProjectionError):
            case.owner.read_result_section_page(consumer_id="report", section_id=section["section_id"], offset=0,
                request_identity=replace(identity, session_ref="session:foreign"), max_wire_bytes=8192)
        with pytest.raises(EvidenceProjectionError):
            case.owner.read_result_section_page(consumer_id="report", section_id=section["section_id"], offset=0,
                request_identity=identity, max_wire_bytes=100)
        for invalid_consumer in ([], {}, None, True, ""):
            with pytest.raises(EvidenceProjectionError) as error:
                case.owner.read_result_section_page(consumer_id=invalid_consumer,
                    section_id=section["section_id"], offset=0, request_identity=identity, max_wire_bytes=8192)
            assert error.value.code == "PROJECTION_CONSUMER_INVALID"


@pytest.mark.parametrize("estimate", [True, False, float("nan"), float("inf"), -float("inf")])
def test_missing_estimate_does_not_admit_invalid_numbers(estimate):
    from workbench.services.report_evidence_owner_factory import build_workflow_report_evidence_envelope

    with pytest.raises(ValueError, match="coefficient estimate is unavailable"):
        build_workflow_report_evidence_envelope(
            run_id="missing", model_run_id="ols_1", upload_hash="a" * 64,
            primary_model_type="ols", allow_empty_facts=True,
            regression_table={"models": [{"id": "ols_1"}],
                "rows": [{"term": "x", "models": {"ols_1": {"estimate": estimate}}}]})


@pytest.mark.parametrize("include_valid", [False, True])
def test_missing_estimate_real_owner_preserves_row_and_semantic_unavailability(tmp_path, include_valid):
    from tests.test_v189_evidence_report_boundary import _produced_report
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1, default_projection_registry

    coefficients = {"missing": {"estimate": None}}
    if include_valid:
        coefficients["valid"] = {"estimate": 1.25, "std_error": 0.2, "p_value": 0.125}
    run = tmp_path / "project" / "runs" / "missing"
    with _produced_report(run, model_results={"ols_1": {
        "model_id": "ols_1", "model_type": "ols", "nobs": 20,
        "coefficients": coefficients}}, diagnostic_summary={}) as case:
        assert case.view["status"] == "available"
        table = case.view["regression_table"]
        assert {row["term"] for row in table["rows"]} == set(coefficients)
        missing = next(row for row in table["rows"] if row["term"] == "missing")
        assert missing["models"]["ols_1"]["estimate"] == {
            "status": "unavailable", "reason": "PRODUCER_FIELD_UNDECLARED"}
        envelope = json.loads((run / "report_evidence.json").read_text())
        estimates = [fact for fact in envelope["numeric_facts"] if fact["statistic_id"] == "model_coefficient"]
        assert [fact["value"] for fact in estimates] == ([1.25] if include_valid else [])
        assert all(fact["validation_level"] == "none" and fact["oracle_checks"] == [] for fact in envelope["numeric_facts"])
        source, _ = case.owner._canonical_report_source_and_artifact()
        for consumer in ("agent", "notebook"):
            selected = default_projection_registry().project(source, consumer_id=consumer,
                destination="local", coefficient_selection=ModelCoefficientSelectionV1("ols_1", terms=("missing",)))
            assert selected.status.value == "unavailable"
            assert selected.audit.restriction_reason == "semantic_role_unavailable"
            assert not selected.facts and selected.semantic_selection is None
            if include_valid:
                selected = default_projection_registry().project(source, consumer_id=consumer,
                    destination="local", coefficient_selection=ModelCoefficientSelectionV1("ols_1", terms=("valid",)))
                assert selected.status.value == "available"
                assert [fact.value for fact in selected.facts] == [1.25]


@pytest.mark.parametrize("estimate", [True, False])
def test_missing_estimate_real_owner_rejects_normalized_boolean(tmp_path, estimate):
    from tests.test_v189_evidence_report_boundary import _produced_report

    run = tmp_path / "project" / "runs" / "invalid"
    with pytest.raises(ValueError, match="Table coefficient is not the actual model source value"):
        with _produced_report(run, model_results={"ols_1": {
            "model_id": "ols_1", "model_type": "ols", "nobs": 20,
            "coefficients": {"x": {"estimate": estimate}}}}, diagnostic_summary={}):
            pytest.fail("Boolean estimate reached owner admission as missing")
    assert not (run / "result_input.json").exists()
    assert not (run / "report_evidence.json").exists()


def _results_api():
    try:
        module = importlib.import_module("workbench.services.results_service")
    except ModuleNotFoundError as exc:
        pytest.fail(f"results service module is missing: {exc.name}")
    try:
        return (
            getattr(module, "current_report_evidence_persistence"),
            getattr(module, "register_report_evidence_owner"),
            getattr(module, "read_persisted_consumer_evidence_for_run"),
            getattr(module, "configure_report_evidence_persistence"),
        )
    except AttributeError as exc:
        pytest.fail(f"report owner catalog API is missing: {exc}")


def _production_receipt(
    factory: object,
    *,
    run_id: str,
    model_run_id: str = "ols_1",
    upload_hash: str = "a" * 64,
):
    return factory.issue_production_receipt(
        run_id=run_id,
        model_run_id=model_run_id,
        upload_hash=upload_hash,
    )


def test_report_factory_requires_a_live_exact_run_bound_production_receipt(
    tmp_path: Path,
) -> None:
    """A confirmation-shaped string or copied receipt is not production authority."""

    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry

    registry, host = _authorized_registry("scope:project:production-receipt")
    project_root = tmp_path / "project"
    project_root.mkdir()
    (tmp_path / "evidence").mkdir()
    run_id = "run-production-receipt"
    envelope = _envelope(artifact_id=f"report:{run_id}")

    with _admit_store(tmp_path / "evidence", registry) as store:
        factory = _factory_type().from_host(
            store,
            registry,
            actor_ref="actor:production-receipt",
            project_ref="project:production-receipt",
            session_ref="session:production-receipt",
            scope_ref="scope:project:production-receipt",
            canonical_project_root=project_root,
            authority_handle=host.channel,
        )
        with pytest.raises(Exception) as fabricated:
            factory.create_for_run(
                run_id=run_id,
                model_run_id="ols_1",
                confirmation_ref=f"confirmation:{run_id}",
                envelope=envelope,
                artifact_file_sha256="a" * 64,
            )
        assert getattr(fabricated.value, "code", None) in {
            "EVIDENCE_PRODUCTION_RECEIPT_REQUIRED",
            "EVIDENCE_PRODUCTION_RECEIPT_INVALID",
        }

        receipt = factory.issue_production_receipt(
            run_id=run_id,
            model_run_id="ols_1",
            upload_hash="a" * 64,
        )
        owner = factory.create_for_run(
            run_id=run_id,
            model_run_id="ols_1",
            production_receipt=receipt,
            envelope=envelope,
            artifact_file_sha256="a" * 64,
        )
        assert owner.run_id == run_id

        copied = copy.copy(receipt)
        with pytest.raises(Exception) as copied_error:
            factory.create_for_run(
                run_id=run_id,
                model_run_id="ols_1",
                production_receipt=copied,
                envelope=envelope,
                artifact_file_sha256="a" * 64,
            )
        assert getattr(copied_error.value, "code", None) in {
            "EVIDENCE_PRODUCTION_RECEIPT_INVALID",
            "EVIDENCE_PRODUCTION_RECEIPT_NOT_LIVE",
        }


def test_report_factory_rejects_packet_store_from_another_bootstrapped_project(
    tmp_path: Path,
) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry

    registry, host = _authorized_registry("scope:project:root-binding")
    project_root = tmp_path / "project"
    expected_evidence_root = project_root / "workbench" / "evidence"
    expected_evidence_root.mkdir(parents=True)
    foreign_evidence_root = tmp_path / "foreign-evidence"
    foreign_evidence_root.mkdir()

    with _admit_store(foreign_evidence_root, registry) as store:
        with pytest.raises(ValueError, match="canonical project evidence root"):
            _factory_type().from_host(
                store,
                registry,
                actor_ref="actor:root-binding",
                project_ref="project:root-binding",
                session_ref="session:root-binding",
                scope_ref="scope:project:root-binding",
                canonical_project_root=project_root,
                authority_handle=host.channel,
            )


def test_report_evidence_status_reflects_blocked_source_without_invented_facts() -> None:
    from workbench.services.report_evidence_owner_factory import (
        build_workflow_report_evidence_envelope,
    )

    envelope = build_workflow_report_evidence_envelope(
        run_id="run-blocked-envelope",
        model_run_id="ols_1",
        upload_hash="a" * 64,
        primary_model_type="ols",
        regression_table={
            "models": [{"id": "ols_1", "nobs": 10}],
            "rows": [{"term": "x", "models": {"ols_1": {"estimate": 999.0}}}],
        },
        issue_dicts=[
            {
                "severity": "BLOCKER",
                "code": "MODEL_FAILED",
                "message": "The admitted model source failed.",
            }
        ],
    )

    assert envelope["execution_status"] == "failed"
    assert envelope["availability"] == "not_available"
    assert envelope["completeness_status"] == "insufficient"
    assert envelope["numeric_facts"] == []
    assert [reason["code"] for reason in envelope["execution_reasons"]] == [
        "MODEL_FAILED"
    ]
    assert [reason["code"] for reason in envelope["availability_reasons"]] == [
        "MODEL_FAILED"
    ]


@pytest.mark.parametrize("severity", ["INFO", "WARNING"])
def test_report_evidence_method_warning_keeps_completed_model_complete(
    severity: str,
) -> None:
    from workbench.services.report_evidence_owner_factory import (
        build_workflow_report_evidence_envelope,
    )

    envelope = build_workflow_report_evidence_envelope(
        run_id="run-categorical-warning",
        model_run_id="ols_1",
        upload_hash="a" * 64,
        primary_model_type="ols",
        regression_table={
            "models": [{"id": "ols_1", "nobs": 10}],
            "rows": [{"term": "x", "models": {"ols_1": {"estimate": 1.5}}}],
        },
        issue_dicts=[
            {
                "severity": severity,
                "code": "CATEGORICAL_AUTO_DUMMY_CODED",
                "message": "Categorical predictors were dummy coded automatically.",
            }
        ],
    )

    assert envelope["execution_status"] == "completed"
    assert envelope["availability"] == "available"
    assert envelope["completeness_status"] == "complete"
    assert envelope["numeric_facts"]
    assert envelope["execution_reasons"] == []
    assert envelope["availability_reasons"] == []
    assert envelope["warnings"] == [
        {
            "code": "CATEGORICAL_AUTO_DUMMY_CODED",
            "message": "Categorical predictors were dummy coded automatically.",
        }
    ]
    assert envelope["degradation_reasons"] == []


def test_report_evidence_explicit_missing_evidence_remains_degraded() -> None:
    from workbench.services.report_evidence_owner_factory import (
        build_workflow_report_evidence_envelope,
    )

    envelope = build_workflow_report_evidence_envelope(
        run_id="run-missing-evidence",
        model_run_id="ols_1",
        upload_hash="a" * 64,
        primary_model_type="ols",
        regression_table={
            "models": [{"id": "ols_1", "nobs": 10}],
            "rows": [{"term": "x", "models": {"ols_1": {"estimate": 1.5}}}],
        },
        issue_dicts=[
            {
                "severity": "WARNING",
                "code": "MISSING_DIAGNOSTIC_EVIDENCE",
                "message": "The declared diagnostic evidence is missing.",
                "evidence_impact": "completeness",
            }
        ],
    )

    assert envelope["execution_status"] == "completed"
    assert envelope["availability"] == "available"
    assert envelope["completeness_status"] == "degraded"
    assert [reason["code"] for reason in envelope["degradation_reasons"]] == [
        "MISSING_DIAGNOSTIC_EVIDENCE"
    ]


def test_report_evidence_rejects_forged_validation_metadata() -> None:
    from workbench.services.report_evidence_owner_factory import (
        build_workflow_report_evidence_envelope,
    )

    with pytest.raises(ValueError, match="server-owned validation receipt"):
        build_workflow_report_evidence_envelope(
            run_id="run-forged-validation",
            model_run_id="ols_1",
            upload_hash="a" * 64,
            primary_model_type="ols",
            regression_table={
                "models": [{"id": "ols_1", "nobs": 10}],
                "rows": [{
                    "term": "x",
                    "models": {"ols_1": {
                        "estimate": 1.5,
                        "validation": {
                            "server_produced": True,
                            "input_digest": "a" * 64,
                            "result_digest": "b" * 64,
                            "oracle_checks": [{
                                "check_id": "forged",
                                "status": "pass",
                                "basis": "same_library_regression",
                            }],
                            "validation_level": "same_library_regression",
                        },
                    }},
                }],
            },
        )


def test_report_evidence_rejects_server_receipt_result_identity_mismatch() -> None:
    import pandas as pd

    from workbench.econometrics.runner import run_ols
    from workbench.report_view_model import (
        build_regression_table,
        build_server_owned_ols_validation_receipt,
    )
    from workbench.services.report_evidence_owner_factory import (
        build_workflow_report_evidence_envelope,
    )

    frame = pd.DataFrame({"y": [1.0, 3.0, 5.0, 7.0], "x": [0.0, 1.0, 2.0, 3.0]})
    result, fitted = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=True,
        model_id="ols_1",
        dataset_snapshot={"upload_sha256": "a" * 64, "model_input_artifact": "test"},
        row_ids=[str(value) for value in frame.index],
    )
    receipt = build_server_owned_ols_validation_receipt(
        run_id="run-receipt-mismatch",
        model_id="ols_1",
        model_result=result,
        fitted=fitted,
        input_digest="a" * 64,
    )
    assert receipt is not None
    table = build_regression_table(
        [("ols_1", result)],
        validation_receipts={"ols_1": receipt},
    )
    table["models"][0]["result_digest"] = "b" * 64  # type: ignore[index]

    with pytest.raises(ValueError, match="server-owned validation receipt identity"):
        build_workflow_report_evidence_envelope(
            run_id="run-receipt-mismatch",
            model_run_id="ols_1",
            upload_hash="a" * 64,
            primary_model_type="ols_robust",
            regression_table=table,
        )


def test_host_factory_exposes_public_typed_construction_path(tmp_path: Path) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry

    registry, host = _authorized_registry("scope:project:public-factory")
    project_root = tmp_path / "project"
    project_root.mkdir()
    (tmp_path / "evidence").mkdir()

    with _admit_store(tmp_path / "evidence", registry) as store:
        factory = _factory_type().from_host(
            store,
            registry,
            actor_ref="actor:public-factory",
            project_ref="project:public-factory",
            session_ref="session:public-factory",
            scope_ref="scope:project:public-factory",
            canonical_project_root=project_root,
            authority_handle=host.channel,
        )

    assert type(factory) is _factory_type()


def test_catalog_identity_mismatch_does_not_fallback_to_global_owner(tmp_path: Path) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.services.results_service import (
        configure_report_evidence_persistence,
        current_report_evidence_persistence,
        register_report_evidence_owner,
    )

    run_id = "run-catalog-fallback"
    project_root = tmp_path / "project"
    project_root.mkdir()
    (tmp_path / "catalog-evidence").mkdir()
    (tmp_path / "global-evidence").mkdir()
    envelope = _envelope(artifact_id=f"report:{run_id}")
    catalog_registry, catalog_host = _authorized_registry("scope:catalog-fallback")
    global_registry, global_host = _authorized_registry("scope:global-fallback")

    try:
        with _admit_store(tmp_path / "catalog-evidence", catalog_registry) as catalog_store:
            catalog_factory = _factory_type().from_host(
                catalog_store,
                catalog_registry,
                actor_ref="actor:catalog",
                project_ref="project:catalog",
                session_ref="session:catalog",
                scope_ref="scope:catalog-fallback",
                canonical_project_root=project_root,
                authority_handle=catalog_host.channel,
            )
            catalog_owner = catalog_factory.create_for_run(
                run_id=run_id,
                model_run_id="ols_1",
                production_receipt=_production_receipt(catalog_factory, run_id=run_id),
                envelope=envelope,
                artifact_file_sha256="a" * 64,
            )
            register_report_evidence_owner(catalog_owner)

            with _admit_store(tmp_path / "global-evidence", global_registry) as global_store:
                global_factory = _factory_type().from_host(
                    global_store,
                    global_registry,
                    actor_ref="actor:global",
                    project_ref="project:global",
                    session_ref="session:global",
                    scope_ref="scope:global-fallback",
                    canonical_project_root=project_root,
                    authority_handle=global_host.channel,
                )
                global_owner = global_factory.create_for_run(
                    run_id=run_id,
                    model_run_id="ols_1",
                    production_receipt=_production_receipt(global_factory, run_id=run_id),
                    envelope=envelope,
                    artifact_file_sha256="a" * 64,
                )
                configure_report_evidence_persistence(global_owner)
                global_receipt_id = global_owner.confirmation_ref
                assert current_report_evidence_persistence(
                    actor_ref="actor:global",
                    run_id=run_id,
                    project_ref="project:global",
                    session_ref="session:global",
                    scope_ref="scope:global-fallback",
                    model_run_id="ols_1",
                    artifact_id=None,
                    commit_id=None,
                    confirmation_ref=global_receipt_id,
                    artifact_file_sha256=None,
                    project_root=project_root,
                ) is None
    finally:
        configure_report_evidence_persistence(None)


def test_stale_catalog_owner_does_not_fallback_to_global_consumer_owner(tmp_path: Path) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.services.results_service import (
        configure_report_evidence_persistence,
        read_persisted_consumer_evidence_for_run,
        register_report_evidence_owner,
    )

    run_id = "run-stale-catalog"
    project_root = tmp_path / "project"
    project_root.mkdir()
    (tmp_path / "catalog-evidence").mkdir()
    (tmp_path / "global-evidence").mkdir()
    envelope = _envelope(artifact_id=f"report:{run_id}")
    catalog_registry, catalog_host = _authorized_registry("scope:stale-catalog")
    global_registry, global_host = _authorized_registry("scope:stale-global")

    try:
        with _admit_store(tmp_path / "catalog-evidence", catalog_registry) as catalog_store:
            catalog_factory = _factory_type().from_host(
                catalog_store,
                catalog_registry,
                actor_ref="actor:catalog-stale",
                project_ref="project:catalog-stale",
                session_ref="session:catalog-stale",
                scope_ref="scope:stale-catalog",
                canonical_project_root=project_root,
                authority_handle=catalog_host.channel,
            )
            catalog_owner = catalog_factory.create_for_run(
                run_id=run_id,
                model_run_id="ols_1",
                production_receipt=_production_receipt(catalog_factory, run_id=run_id),
                envelope=envelope,
                artifact_file_sha256="a" * 64,
            )
            register_report_evidence_owner(catalog_owner)
            catalog_host.channel.close()

            with _admit_store(tmp_path / "global-evidence", global_registry) as global_store:
                global_factory = _factory_type().from_host(
                    global_store,
                    global_registry,
                    actor_ref="actor:global-stale",
                    project_ref="project:global-stale",
                    session_ref="session:global-stale",
                    scope_ref="scope:stale-global",
                    canonical_project_root=project_root,
                    authority_handle=global_host.channel,
                )
                global_owner = global_factory.create_for_run(
                    run_id=run_id,
                    model_run_id="ols_1",
                    production_receipt=_production_receipt(global_factory, run_id=run_id),
                    envelope=envelope,
                    artifact_file_sha256="b" * 64,
                )
                configure_report_evidence_persistence(global_owner)
                global_receipt_id = global_owner.confirmation_ref
                evidence = read_persisted_consumer_evidence_for_run(
                    consumer_id="agent",
                    project_root=project_root,
                    run_id=run_id,
                )
                assert evidence["status"] == "unavailable"
                assert evidence["reason_code"] == "EVIDENCE_OWNER_CONTEXT_CONFLICT"
                assert evidence["facts"] == []
    finally:
        configure_report_evidence_persistence(None)


def test_host_factory_admits_and_catalogs_one_owner_by_exact_run_identity(tmp_path: Path) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    factory_type = _factory_type()
    current_owner, register_owner, _read_consumer, clear_persistence = _results_api()

    registry, host = _authorized_registry("scope:project:factory")
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-factory-1"
    run_root.mkdir(parents=True)
    (tmp_path / "evidence").mkdir()
    artifact_path = run_root / "diagnostic_summary.json"
    artifact_path.write_text('{"status":"completed"}', encoding="utf-8")
    store_context = _admit_store(tmp_path / "evidence", registry)
    try:
        with store_context as store:
            factory = factory_type._from_host(
                store,
                registry,
                actor_ref="actor:factory",
                project_ref="project:factory",
                session_ref="session:factory",
                scope_ref="scope:project:factory",
                canonical_project_root=project_root,
                authority_handle=host.channel,
            )
            factory.validate_runtime_binding(
                project_ref="project:factory",
                session_ref="session:factory",
                data_project_root=project_root,
            )
            with pytest.raises(ValueError, match="project/session scope"):
                factory.validate_runtime_binding(
                    project_ref="project:other",
                    session_ref="session:factory",
                    data_project_root=project_root,
                )
            receipt = _production_receipt(factory, run_id="run-factory-1")
            owner = factory.create_for_run(
                run_id="run-factory-1",
                model_run_id="ols_1",
                production_receipt=receipt,
                envelope=_envelope(artifact_id="report:run-factory-1"),
                artifact_file_sha256=hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            )
            register_owner(owner)

            assert current_owner(
                actor_ref="actor:factory",
                run_id="run-factory-1",
                project_ref="project:factory",
                session_ref="session:factory",
                scope_ref="scope:project:factory",
                model_run_id="ols_1",
                artifact_id=None,
                commit_id=None,
                confirmation_ref=receipt.receipt_id,
                artifact_file_sha256=None,
                project_root=project_root,
            ) is owner
            assert current_owner(
                actor_ref="actor:factory",
                run_id="foreign-run",
                project_ref="project:factory",
                session_ref="session:factory",
                scope_ref="scope:project:factory",
                model_run_id="ols_1",
                artifact_id=None,
                commit_id=None,
                confirmation_ref="foreign-production-receipt",
                artifact_file_sha256=None,
                project_root=project_root,
            ) is None

            evidence = _read_consumer(
                consumer_id="agent",
                project_root=project_root,
                run_id="run-factory-1",
            )
            assert evidence["status"] == "available", evidence
            assert evidence["facts"]
    finally:
        clear_persistence(None)


def test_factory_rejects_envelope_identity_that_does_not_match_run_owner(tmp_path: Path) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.services.report_evidence_owner_factory import (
        build_workflow_report_evidence_envelope,
    )

    registry, host = _authorized_registry("scope:project:identity-binding")
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-identity-binding"
    run_root.mkdir(parents=True)
    (tmp_path / "evidence").mkdir()
    evidence_path = run_root / "report_evidence.json"
    evidence_path.write_text('{"evidence":"immutable"}', encoding="utf-8")
    with _admit_store(tmp_path / "evidence", registry) as store:
        factory = _factory_type()._from_host(
            store,
            registry,
            actor_ref="actor:identity-binding",
            project_ref="project:identity-binding",
            session_ref="session:identity-binding",
            scope_ref="scope:project:identity-binding",
            canonical_project_root=project_root,
            authority_handle=host.channel,
        )
        local_envelope = build_workflow_report_evidence_envelope(
            run_id="run-identity-binding",
            model_run_id="ols_1",
            upload_hash="a" * 64,
            primary_model_type="ols",
            regression_table={
                "models": [{"id": "ols_1", "nobs": 2}],
                "rows": [{"term": "x", "models": {"ols_1": {"estimate": 1.0}}}],
            },
        )
        local_envelope["result_identity"]["result_ref"] = "report-result:foreign-run"
        identity_receipt = _production_receipt(
            factory,
            run_id="run-identity-binding",
            model_run_id="ols_1",
        )
        with pytest.raises(Exception) as result_ref_error:
            factory.create_for_run(
                run_id="run-identity-binding",
                model_run_id="ols_1",
                production_receipt=identity_receipt,
                envelope=local_envelope,
                artifact_file_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            )
        assert getattr(result_ref_error.value, "code", None) == "EVIDENCE_OWNER_CONTEXT_MISMATCH"
        foreign_envelope = build_workflow_report_evidence_envelope(
            run_id="foreign-run",
            model_run_id="foreign-model",
            upload_hash="a" * 64,
            primary_model_type="ols",
            regression_table={
                "models": [{"id": "foreign-model", "nobs": 2}],
                "rows": [{"term": "x", "models": {"foreign-model": {"estimate": 1.0}}}],
            },
        )
        foreign_envelope["result_identity"]["result_ref"] = "report-result:foreign-run"
        with pytest.raises(Exception) as error:
            factory.create_for_run(
                run_id="run-identity-binding",
                model_run_id="ols_1",
                production_receipt=identity_receipt,
                envelope=foreign_envelope,
                artifact_file_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            )
        assert getattr(error.value, "code", None) == "EVIDENCE_OWNER_CONTEXT_MISMATCH"


def test_factory_rejects_different_envelope_for_same_run_and_tampered_index_file(
    tmp_path: Path,
) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.artifacts import initialize_artifact_index
    from workbench.services.report_evidence_owner_factory import (
        build_workflow_report_evidence_envelope,
        register_report_evidence_artifact,
    )

    registry, host = _authorized_registry("scope:project:immutability")
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-immutability"
    run_root.mkdir(parents=True)
    (tmp_path / "evidence").mkdir()
    initialize_artifact_index(run_root)
    evidence_path = run_root / "report_evidence.json"
    with _admit_store(tmp_path / "evidence", registry) as store:
        factory = _factory_type()._from_host(
            store,
            registry,
            actor_ref="actor:immutability",
            project_ref="project:immutability",
            session_ref="session:immutability",
            scope_ref="scope:project:immutability",
            canonical_project_root=project_root,
            authority_handle=host.channel,
        )
        envelope = build_workflow_report_evidence_envelope(
            run_id="run-immutability",
            model_run_id="ols_1",
            upload_hash="a" * 64,
            primary_model_type="ols",
            regression_table={
                "models": [{"id": "ols_1", "nobs": 2}],
                "rows": [{"term": "x", "models": {"ols_1": {"estimate": 1.0}}}],
            },
        )
        evidence_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
        file_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        receipt = _production_receipt(factory, run_id="run-immutability")
        owner = factory.create_for_run(
            run_id="run-immutability",
            model_run_id="ols_1",
            production_receipt=receipt,
            envelope=envelope,
            artifact_file_sha256=file_hash,
        )
        different_envelope = dict(envelope)
        different_envelope["warnings"] = [{"code": "DIFFERENT", "message": "different"}]
        with pytest.raises(Exception) as error:
            factory.create_for_run(
                run_id="run-immutability",
                model_run_id="ols_1",
                production_receipt=receipt,
                envelope=different_envelope,
                artifact_file_sha256=file_hash,
            )
        assert getattr(error.value, "code", None) == "EVIDENCE_OWNER_CONTEXT_MISMATCH"

        evidence_path.write_text('{"evidence":"tampered"}', encoding="utf-8")
        with pytest.raises(Exception) as tampered:
            register_report_evidence_artifact(
                owner,
                run_root=run_root,
                path=evidence_path,
                inputs=["model_results/ols_1.json"],
            )
        assert getattr(tampered.value, "code", None) == "EVIDENCE_ARTIFACT_FILE_HASH_MISMATCH"


def test_factory_registers_a_c0_bound_report_artifact_index_row(tmp_path: Path) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.artifacts import initialize_artifact_index
    from workbench.services.report_evidence_owner_factory import (
        register_report_evidence_artifact,
    )

    registry, host = _authorized_registry("scope:project:index")
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-index-1"
    run_root.mkdir(parents=True)
    (tmp_path / "evidence").mkdir()
    initialize_artifact_index(run_root)
    evidence_path = run_root / "report_evidence.json"
    evidence_path.write_text('{"evidence":"immutable"}', encoding="utf-8")
    with _admit_store(tmp_path / "evidence", registry) as store:
        factory = _factory_type()._from_host(
            store,
            registry,
            actor_ref="actor:index",
            project_ref="project:index",
            session_ref="session:index",
            scope_ref="scope:project:index",
            canonical_project_root=project_root,
            authority_handle=host.channel,
        )
        envelope = _envelope(artifact_id="report:run-index-1")
        evidence_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
        receipt = _production_receipt(factory, run_id="run-index-1")
        owner = factory.create_for_run(
            run_id="run-index-1",
            model_run_id="ols_1",
            production_receipt=receipt,
            envelope=envelope,
            artifact_file_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        )
        record = register_report_evidence_artifact(
            owner,
            run_root=run_root,
            path=evidence_path,
            inputs=["model_results/ols_1.json"],
        )

    assert record["artifact_id"] == "report:run-index-1"
    assert record["evidence_commit_ref"] == owner.commit_id
    assert record["evidence_content_hash"]
    assert json.loads((run_root / "artifacts_index.json").read_text())[ 
        "artifacts"
    ][0]["source_ref"] == "source:run:run-index-1"


def test_project_file_store_serializes_index_read_modify_write_transactions(
    tmp_path: Path,
) -> None:
    """Two workers must not lose an artifact-index update between read and replace."""

    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.artifacts import initialize_artifact_index

    registry, host = _authorized_registry("scope:project:index-transaction")
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-index-transaction"
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    (tmp_path / "evidence").mkdir()

    with _admit_store(tmp_path / "evidence", registry) as store:
        factory = _factory_type()._from_host(
            store,
            registry,
            actor_ref="actor:index-transaction",
            project_ref="project:index-transaction",
            session_ref="session:index-transaction",
            scope_ref="scope:project:index-transaction",
            canonical_project_root=project_root,
            authority_handle=host.channel,
        )
        file_store = factory._project_file_store

        def add_record(artifact_id: str) -> None:
            def mutate(index: dict[str, object]) -> dict[str, object]:
                # Make a lost-update implementation fail deterministically:
                # both callbacks overlap while holding the transaction's lock.
                time.sleep(0.02)
                records = index.get("artifacts")
                assert isinstance(records, list)
                index["artifacts"] = [*records, {"artifact_id": artifact_id}]
                return index

            file_store.mutate_json(
                ("runs", run_root.name, "artifacts_index.json"),
                mutate,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(add_record, ("report:a", "report:b")))

    index = json.loads((run_root / "artifacts_index.json").read_text(encoding="utf-8"))
    assert {item["artifact_id"] for item in index["artifacts"]} == {
        "report:a",
        "report:b",
    }


def test_factory_rejects_file_content_that_is_not_the_admitted_envelope(tmp_path: Path) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.artifacts import initialize_artifact_index
    from workbench.services.report_evidence_owner_factory import register_report_evidence_artifact

    registry, host = _authorized_registry("scope:project:file-content")
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-file-content"
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    (tmp_path / "evidence").mkdir()
    envelope = _envelope(artifact_id="report:run-file-content")
    evidence_path = run_root / "report_evidence.json"
    evidence_path.write_text('{"evidence":"different-content"}', encoding="utf-8")
    with _admit_store(tmp_path / "evidence", registry) as store:
        factory = _factory_type()._from_host(
            store,
            registry,
            actor_ref="actor:file-content",
            project_ref="project:file-content",
            session_ref="session:file-content",
            scope_ref="scope:project:file-content",
            canonical_project_root=project_root,
            authority_handle=host.channel,
        )
        receipt = _production_receipt(factory, run_id="run-file-content")
        owner = factory.create_for_run(
            run_id="run-file-content",
            model_run_id="ols_1",
            production_receipt=receipt,
            envelope=envelope,
            artifact_file_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        )
        with pytest.raises(Exception) as error:
            register_report_evidence_artifact(
                owner,
                run_root=run_root,
                path=evidence_path,
                inputs=["model_results/ols_1.json"],
            )
        assert getattr(error.value, "code", None) == "EVIDENCE_ARTIFACT_CONTENT_MISMATCH"


def test_report_stage_factory_admission_writes_immutable_evidence_and_projection(
    tmp_path: Path,
) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.app import (
        configure_report_evidence_owner_factory,
    )
    from workbench.artifacts import initialize_artifact_index, read_json
    from workbench.engine.stages.report import _admit_report_evidence_from_factory
    from workbench.report_export import EvidenceProjectionV1
    from workbench.services.results_service import (
        configure_report_evidence_persistence,
        report_evidence_request_identity_for_run,
    )

    registry, host = _authorized_registry("scope:project:stage")
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-stage-1"
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    (tmp_path / "evidence").mkdir()
    with _admit_store(tmp_path / "evidence", registry) as store:
        factory = _factory_type()._from_host(
            store,
            registry,
            actor_ref="actor:stage",
            project_ref="project:stage",
            session_ref="session:stage",
            scope_ref="scope:project:stage",
            canonical_project_root=project_root,
            authority_handle=host.channel,
        )
        configure_report_evidence_owner_factory(factory)
        try:
            ctx = SimpleNamespace(artifacts={"_upload_hash": "b" * 64})
            admitted = _admit_report_evidence_from_factory(
                ctx,
                run_root=run_root,
                run_id="run-stage-1",
                model_run_id="ols_1",
                primary_model_type="ols",
                regression_table={
                    "models": [{"id": "ols_1", "nobs": 10}],
                    "rows": [
                        {
                            "term": "x",
                            "models": {"ols_1": {"estimate": 2.0}},
                        }
                    ],
                },
                issue_dicts=[],
            )
            identity = report_evidence_request_identity_for_run(
                project_root=project_root,
                run_id="run-stage-1",
            )
            assert identity is not None
            assert identity.model_run_id == "ols_1"
        finally:
            configure_report_evidence_owner_factory(None)
            configure_report_evidence_persistence(None)

    assert admitted is not None
    owner, projection = admitted
    assert type(projection) is EvidenceProjectionV1
    assert projection._owner is owner
    evidence_path = run_root / "report_evidence.json"
    assert evidence_path.is_file()
    index = read_json(run_root / "artifacts_index.json")
    record = next(
        item for item in index["artifacts"] if item["artifact_id"] == owner.artifact_id
    )
    assert record["path"] == "report_evidence.json"
    assert record["evidence_commit_ref"] == owner.commit_id


def test_workflow_report_envelope_uses_only_bounded_table_facts() -> None:
    from workbench.services.report_evidence_owner_factory import (
        build_workflow_report_evidence_envelope,
    )

    envelope = build_workflow_report_evidence_envelope(
        run_id="run-envelope",
        model_run_id="ols_1",
        upload_hash="a" * 64,
        primary_model_type="ols",
        regression_table={
            "models": [{"id": "ols_1", "nobs": 10}],
            "rows": [
                {
                    "term": "x",
                    "models": {
                        "ols_1": {
                            "estimate": 1.25,
                            "std_error": 0.1,
                            "confidence_interval": [1.0, 1.5],
                            "p_value": 0.01,
                        }
                    },
                }
            ],
        },
    )

    assert envelope["input_provenance"] == {
        "artifact_ref": "dataset:" + "a" * 64,
        "artifact_digest": "a" * 64,
    }
    assert envelope["numeric_facts"][0]["value"] == 1.25
    assert envelope["numeric_facts"][0]["source_selector"]["artifact_ref"] == "report:run-envelope"
    assert envelope["numeric_facts"][0]["oracle_checks"] == []
    assert envelope["numeric_facts"][0]["validation_level"] == "none"
    assert envelope["validation_summary"] == {
        "levels_present": ["none"],
        "minimum_required": "none",
        "requirement_status": "not_applicable",
    }


def test_real_ols_workflow_factory_reaches_http_report_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pandas as pd
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.api import app
    from workbench.app import configure_report_evidence_owner_factory
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    from workbench.services.results_service import (
        configure_report_evidence_persistence,
        read_persisted_consumer_evidence_for_run,
    )

    source = tmp_path / "workflow.csv"
    pd.DataFrame(
        {
            "y": [1.0 + 2.0 * index for index in range(35)],
            "x": [float(index) for index in range(35)],
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "factory-e2e")
    producer_errors = []
    from workbench.engine.stages import report as report_stage
    prepare_original = report_stage._admit_report_evidence_from_factory
    def checked_prepare(*args, **kwargs):
        try:
            return prepare_original(*args, **kwargs)
        except Exception as exc:
            producer_errors.append(repr(exc))
            bound_owner = factory._owners.get(kwargs["run_id"])
            if bound_owner is not None:
                wire = bound_owner._canonical_report_wire()
                producer_errors.append({key: wire.get(key) for key in ("status", "reasonCode", "reasonCodes")})
            raise
    monkeypatch.setattr(report_stage, "_admit_report_evidence_from_factory", checked_prepare)
    execution_app = FastAPI()
    registry, host = _authorized_registry("scope:project:e2e")
    (tmp_path / "evidence").mkdir()
    with _admit_store(tmp_path / "evidence", registry) as store:
        factory = _factory_type()._from_host(
            store,
            registry,
            actor_ref="actor:e2e",
            project_ref="project:e2e",
            session_ref="session:e2e",
            scope_ref="scope:project:e2e",
            canonical_project_root=project.root,
            authority_handle=host.channel,
        )
        configure_report_evidence_owner_factory(factory, app_instance=execution_app)
        try:
            with TestClient(app) as client:
                result = run_workflow(
                    project.root,
                    [source],
                    mode="auto",
                    y="y",
                    x=["x"],
                    model_type="ols",
                    app_instance=execution_app,
                )
                assert result["status"] == "completed", producer_errors
                run_id = result["run_id"]
                evidence = json.loads(
                    (project.root / "runs" / run_id / "report_evidence.json").read_text(encoding="utf-8")
                )
                from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
                selection = ModelCoefficientSelectionV1(evidence["result_identity"]["model_run_id"])
                for consumer_id in ("agent", "notebook"):
                    consumer_evidence = read_persisted_consumer_evidence_for_run(
                        consumer_id=consumer_id,
                        project_root=project.root,
                        run_id=run_id,
                        coefficient_selection=selection,
                    )
                    assert consumer_evidence["status"] == "available", consumer_evidence
                    assert consumer_evidence["semantic_selection"]["model_id"] == selection.model_id
                    assert consumer_evidence["facts"]
                report = client.get(
                    f"/runs/{run_id}/report",
                    params={"project_root": str(project.root)},
                )
                assert report.status_code == 200, report.text
                assert "Persisted report evidence" in report.text
                assert evidence["validation_summary"] == {
                    "levels_present": ["none", "same_library_regression"],
                    "minimum_required": "same_library_regression",
                    "requirement_status": "not_met",
                }
                assert evidence["numeric_facts"]
                coefficients = [fact for fact in evidence["numeric_facts"] if fact["statistic_id"] == "model_coefficient"]
                assert coefficients
                assert all(
                    fact["validation_level"] == "same_library_regression"
                    and fact["oracle_checks"]
                    and all(
                        check["basis"] == "same_library_regression"
                        and check["status"] == "pass"
                        for check in fact["oracle_checks"]
                    )
                    for fact in coefficients
                )
                new_facts = [fact for fact in evidence["numeric_facts"] if fact["statistic_id"] != "model_coefficient"]
                assert any(fact["statistic_id"] == "p_value" for fact in new_facts)
                assert all(fact["validation_level"] == "none" and fact["oracle_checks"] == [] for fact in new_facts)
                from workbench.evidence.result_dependencies import verify_result_dependencies
                sealed = evidence["family_evidence"]["result_dependencies"]
                assert "diagnostic_summary" not in {row["artifact_id"] for row in sealed["records"]}
                verify_result_dependencies(factory._project_file_store, sealed, project_ref="project:e2e", run_id=run_id)
                assert {section["section_id"] for section in evidence["family_evidence"]["structured_results"]["sections"]} == {
                    "model_identity", "regression_table", "descriptive_statistics", "statistical_tests", "survey_design",
                    "marginal_effects", "model_family_evidence", "diagnostics", "interpretation_constraints", "variable_importance", "workflow_status"}
                artifacts = client.get(
                    f"/runs/{run_id}/artifacts",
                    params={"project_root": str(project.root)},
                )
                assert artifacts.status_code == 200, artifacts.text
                evidence_path = project.root / "runs" / run_id / "report_evidence.json"
                evidence_path.write_text('{"tampered":true}', encoding="utf-8")
                tampered_report = client.get(
                    f"/runs/{run_id}/report",
                    params={"project_root": str(project.root)},
                )
                assert tampered_report.status_code == 409
                assert tampered_report.json()["error"]["code"] == "REPORT_EVIDENCE_UNAVAILABLE"
        finally:
            configure_report_evidence_owner_factory(None, app_instance=execution_app)
            configure_report_evidence_persistence(None)


def test_custom_app_does_not_fall_back_to_global_report_factory(tmp_path: Path) -> None:
    import pandas as pd
    from fastapi import FastAPI

    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.app import configure_report_evidence_owner_factory
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    from workbench.services.results_service import configure_report_evidence_persistence

    source = tmp_path / "workflow.csv"
    pd.DataFrame(
        {"y": [1.0 + 2.0 * index for index in range(35)], "x": [float(index) for index in range(35)]}
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "factory-isolation")
    global_registry, global_host = _authorized_registry("scope:project:global-factory")
    (tmp_path / "evidence").mkdir()
    execution_app = FastAPI()
    with _admit_store(tmp_path / "evidence", global_registry) as store:
        global_factory = _factory_type()._from_host(
            store,
            global_registry,
            actor_ref="actor:global-factory",
            project_ref="project:global-factory",
            session_ref="session:global-factory",
            scope_ref="scope:project:global-factory",
            canonical_project_root=project.root,
            authority_handle=global_host.channel,
        )
        configure_report_evidence_owner_factory(global_factory)
        try:
            result = run_workflow(
                project.root,
                [source],
                mode="auto",
                y="y",
                x=["x"],
                model_type="ols",
                app_instance=execution_app,
            )
            run_root = project.root / "runs" / result["run_id"]
            assert result["status"] == "completed"
            assert not (run_root / "report_evidence.json").exists()
        finally:
            configure_report_evidence_owner_factory(None)
            configure_report_evidence_persistence(None)


def test_configured_factory_failure_blocks_completed_workflow(tmp_path: Path) -> None:
    import pandas as pd
    from fastapi import FastAPI

    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from workbench.app import configure_report_evidence_owner_factory
    from workbench.artifacts import read_json
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    from workbench.services.results_service import configure_report_evidence_persistence

    source = tmp_path / "workflow.csv"
    pd.DataFrame(
        {
            "y": [1.0 + 2.0 * index for index in range(35)],
            "x": [float(index) for index in range(35)],
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "factory-failure")
    execution_app = FastAPI()
    wrong_root = tmp_path / "wrong-project"
    wrong_root.mkdir()
    registry, host = _authorized_registry("scope:project:failure")
    (tmp_path / "evidence").mkdir()
    with _admit_store(tmp_path / "evidence", registry) as store:
        factory = _factory_type()._from_host(
            store,
            registry,
            actor_ref="actor:failure",
            project_ref="project:failure",
            session_ref="session:failure",
            scope_ref="scope:project:failure",
            canonical_project_root=wrong_root,
            authority_handle=host.channel,
        )
        configure_report_evidence_owner_factory(factory, app_instance=execution_app)
        try:
            result = run_workflow(
                project.root,
                [source],
                mode="auto",
                y="y",
                x=["x"],
                model_type="ols",
                app_instance=execution_app,
            )
            assert result["status"] == "failed"
            run_root = project.root / "runs" / result["run_id"]
            assert read_json(run_root / "run_manifest.json")["status"] == "failed"
            issue_codes = {
                issue["code"] for issue in read_json(run_root / "errors.json")["issues"]
            }
            assert "REPORT_EVIDENCE_REQUIRED" in issue_codes
        finally:
            configure_report_evidence_owner_factory(None, app_instance=execution_app)
            configure_report_evidence_persistence(None)
