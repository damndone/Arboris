"""HTTP pages retain real host admission, not client-supplied identity."""
from contextlib import contextmanager
import copy
import json

import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.app import configure_report_evidence_owner
from workbench.canonical import sha256_canonical
from workbench.contracts.evidence.result_pages import ResultPageAccumulatorV1, ResultPageV1
from workbench.evidence.consumer_adapters import parse_result_section_bundle
from tests.test_v189_structured_consumer_projection import committed, owner_for


def _read_facts(**kwargs):
    from workbench.services import results_service
    read = getattr(results_service, "read_persisted_consumer_result_facts_for_run", None)
    assert callable(read), "bounded owner-bound numeric fact query is missing"
    return read(**kwargs)


def _assert_no_fact_delivery(wire, reason=None):
    assert wire["status"] in {"unavailable", "blocked"}, wire
    assert wire["facts"] == [] and wire["receipt"] is None
    assert not wire.get("sections") and "fact_selection" not in wire
    if reason:
        assert wire["reason_code"] == reason


def test_numeric_fact_pages_preserve_fit_and_interval_values_and_signed_scope(tmp_path, monkeypatch):
    from tests.test_v189_evidence_report_boundary import _produced_report
    from workbench.services import results_service as service
    monkeypatch.setattr(service, "_REPORT_EVIDENCE_OWNER_CATALOG", {})
    monkeypatch.setattr(service, "_REPORT_EVIDENCE_PERSISTENCE", service.UnavailableReportEvidenceCapabilityV1())
    monkeypatch.setattr(service, "_REPORT_EVIDENCE_OWNER_REHYDRATOR", None)
    run = tmp_path / "project" / "runs" / "fit-page"
    packet = {"model_id": "ols_1", "model_type": "ols", "nobs": 100,
        "r_squared": 0.42, "adjusted_r_squared": 0.41,
        "coefficients": {"share": {"estimate": 1.2, "ci_lower": 0.61, "ci_upper": 1.79}}}
    with _produced_report(run, model_results={"ols_1": packet}, diagnostic_summary={}) as case:
        service.register_report_evidence_owner(case.owner)
        query = dict(consumer_id="agent", project_root=run.parent.parent, run_id=run.name,
                     section_id="regression_table", offset=0, limit=1)
        source, artifact = case.owner._canonical_report_source_and_artifact()
        from workbench.evidence.consumer_adapters import default_projection_registry
        admitted, _, _, _, _ = default_projection_registry()._prepare_selection(source,
            consumer_id="agent", destination="local", requested_section_ids=("regression_table",))
        section = admitted["sections"][0]
        expected = {fact.fact_id: fact.to_dict() for fact in artifact.envelope.numeric_facts
                    if fact.fact_id in section.fact_refs}
        observed = {}
        offset, digest = 0, None
        while offset is not None:
            wire = _read_facts(**{**query, "offset": offset, "expected_envelope_digest": digest})
            assert wire["status"] in {"available", "degraded"}, wire
            selection = wire["fact_selection"]
            assert selection["read_completeness"] == "PARTIAL"
            assert selection["scope"] == "section_numeric_facts"
            assert selection["numeric_only"] is True and selection["full_section_read"] is False
            assert "warnings" in selection["warning"] and "not" in selection["warning"]
            assert selection["section_id"] == "regression_table"
            assert selection["section_digest"] == sha256_canonical(section.to_dict())
            assert selection["total_facts"] == len(expected)
            assert selection["offset"] == offset and selection["limit"] == 1
            assert [fact["fact_id"] for fact in wire["facts"]] == list(section.fact_refs[offset:offset + 1])
            assert not wire["sections"]
            assert wire["receipt"]["identity"] == wire["identity"]
            assert wire["receipt"]["wire_digest"] == sha256_canonical({k: v for k, v in wire.items() if k != "receipt"})
            assert wire["projection_digest"] == service._central_consumer_projection_digest(wire)
            for key in selection:
                mutated = copy.deepcopy(wire)
                mutated["fact_selection"][key] = "changed selection metadata"
                assert service._central_consumer_projection_digest(mutated) != wire["projection_digest"]
                assert sha256_canonical({k: v for k, v in mutated.items() if k != "receipt"}) != wire["receipt"]["wire_digest"]
            assert len(json.dumps({"persisted_evidence": wire}, ensure_ascii=False, sort_keys=True).encode()) <= 8192
            assert {row["artifact_id"] for row in wire["result_dependencies"]["records"]} >= set(section.dependency_refs)
            assert wire["audit"]["row_budget"] == len(wire["facts"]) + len(wire["result_dependencies"]["records"]) + 1
            observed.update({fact["fact_id"]: fact for fact in wire["facts"]})
            digest, offset = wire["envelope_digest"], selection["next_offset"]
        assert observed == expected
        values = {fact["statistic_id"]: fact["value"] for fact in observed.values()}
        assert values == {"nobs": 100, "r_squared": 0.42, "adjusted_r_squared": 0.41,
                          "model_coefficient": 1.2, "ci_lower": 0.61, "ci_upper": 1.79,
                          "schema_version": 1}
        # Exact requested pages fail atomically; the service must not reduce
        # limit until some prefix happens to fit.
        _assert_no_fact_delivery(_read_facts(**{**query, "limit": 64}))
        _assert_no_fact_delivery(_read_facts(**{**query, "offset": 1}), "RESULT_FACT_SNAPSHOT_REQUIRED")
        _assert_no_fact_delivery(_read_facts(**{**query, "expected_envelope_digest": "0" * 64}),
                                 "RESULT_FACT_SNAPSHOT_MISMATCH")
        for offset, limit in ((True, 1), (-1, 1), (0.5, 1), (0, True), (0, 0), (0, 65)):
            _assert_no_fact_delivery(_read_facts(**{**query, "offset": offset, "limit": limit}),
                                     "RESULT_FACT_SELECTOR_INVALID")
        _assert_no_fact_delivery(_read_facts(**{**query, "section_id": "unknown"}), "unknown_section_identity")
        _assert_no_fact_delivery(_read_facts(**{**query, "offset": len(expected), "expected_envelope_digest": digest}),
                                 "RESULT_FACT_OFFSET_INVALID")
        (run / "model_results" / "ols_1.json").write_text("changed after page", encoding="utf-8")
        _assert_no_fact_delivery(_read_facts(**{**query, "offset": 1, "expected_envelope_digest": digest}),
                                 "EVIDENCE_DEPENDENCY_MISMATCH")


def test_numeric_fact_query_rejects_foreign_authority_and_closed_sections(tmp_path):
    with live(tmp_path, section_status="unavailable") as (_, owner, root):
        query = dict(consumer_id="agent", project_root=root, run_id="r1", section_id="a", offset=0, limit=1)
        _assert_no_fact_delivery(_read_facts(**query), "RESULT_FACT_SECTION_UNAVAILABLE")
        for change in ({"project_root": tmp_path / "foreign"}, {"run_id": "foreign"},
                       {"consumer_id": "unknown"}, {"run_id": "../r1"}):
            _assert_no_fact_delivery(_read_facts(**{**query, **change}))
        for forbidden in ("owner", "request_identity", "destination", "requested_fact_ids"):
            with pytest.raises(TypeError):
                _read_facts(**query, **{forbidden: "client-authority"})


def test_numeric_fact_query_rejects_a_different_real_snapshot(tmp_path):
    with live(tmp_path / "first") as (_, _, root):
        first = _read_facts(consumer_id="agent", project_root=root, run_id="r1", section_id="a")
        assert first["status"] == "available"
    with live(tmp_path / "second", label="new committed snapshot") as (_, _, root):
        query = dict(consumer_id="agent", project_root=root, run_id="r1", section_id="a")
        second = _read_facts(**query)
        assert second["status"] == "available"
        assert second["envelope_digest"] != first["envelope_digest"]
        _assert_no_fact_delivery(_read_facts(**query, expected_envelope_digest=first["envelope_digest"]),
                                 "RESULT_FACT_SNAPSHOT_MISMATCH")


def test_numeric_fact_query_rechecks_parent_dependencies_before_receipt(tmp_path, monkeypatch):
    from workbench.evidence.consumer_adapters import ConsumerProjectionRegistryV1
    with live(tmp_path, regression=True) as (_, _, root):
        query = dict(consumer_id="agent", project_root=root, run_id="r1", section_id="coefficients", limit=1)
        first = _read_facts(**query)
        assert first["status"] == "available", first
        assert first["facts"][0]["source_selector"]["artifact_ref"] == "a"
        original = ConsumerProjectionRegistryV1.project

        def mutate_parent_after_numeric_projection(registry, *args, **kwargs):
            projection = original(registry, *args, **kwargs)
            # This is not the selected fact's direct source. Its inclusion in
            # the parent's dependency closure must still protect delivery.
            (root / "runs" / "r1" / "b.json").write_bytes(b"changed during query")
            return projection

        monkeypatch.setattr(ConsumerProjectionRegistryV1, "project", mutate_parent_after_numeric_projection)
        _assert_no_fact_delivery(_read_facts(**query), "EVIDENCE_DEPENDENCY_MISMATCH")


@contextmanager
def live(tmp_path, *, actor_ref=None, **kwargs):
    with committed(tmp_path, **kwargs) as (_, _, _, _, options, args):
        if actor_ref is None:
            owner = owner_for(options, args)
        else:
            from workbench.services.results_service import ServerOwnedReportEvidencePersistenceV1
            owner = ServerOwnedReportEvidencePersistenceV1._from_host(*args,
                actor_ref=actor_ref, project_ref=options["project_ref"], session_ref="session:structured",
                scope_ref=options["scope_ref"], run_id="r1", model_run_id="r1",
                artifact_id=options["artifact_id"], commit_id=options["commit_id"], confirmation_ref="confirmation:r1",
                artifact_file_sha256="a" * 64, canonical_project_root=options["canonical_project_root"],
                project_file_store=options["project_file_store"], authority_handle=options["authority_handle"])
        configure_report_evidence_owner(owner)
        try:
            with TestClient(app) as client:
                yield client, owner, tmp_path / "project"
        finally:
            configure_report_evidence_owner(None)


def test_http_directory_and_pages_preserve_actual_owner_sections(tmp_path):
    with live(tmp_path, label="统计🧪" * 100) as (client, owner, root):
        params = {"project_root": str(root)}
        response = client.get("/runs/r1/results/directory", params=params)
        assert response.status_code == 200, response.text
        directory = response.json()
        assert directory["read_completeness"] == "PARTIAL"
        assert [s["section_id"] for s in directory["sections"]] == ["a", "b"]
        assert directory["identity"]["session_ref"] == owner.session_ref
        assert directory["directory_digest"] == sha256_canonical(directory["sections"])
        assert directory["receipt"]["wire_digest"] == sha256_canonical({k: v for k, v in directory.items() if k != "receipt"})
        for section in directory["sections"]:
            offset = 0
            accumulator = None
            page_count = 0
            while offset is not None:
                response = client.get("/runs/r1/results/page", params={**params,
                    "section_id": section["section_id"], "offset": offset, "max_wire_bytes": 4500})
                assert response.status_code == 200, response.text
                wire = response.json()
                assert wire["read_completeness"] == "PARTIAL"
                assert wire["identity"] == directory["identity"]
                assert wire["receipt"]["wire_digest"] == sha256_canonical({k: v for k, v in wire.items() if k != "receipt"})
                page = wire["delivery"]["page"]
                if accumulator is None:
                    accumulator = ResultPageAccumulatorV1(page["binding"], max_total_bytes=100000)
                accumulator.add(ResultPageV1.from_dict(page))
                page_count += 1
                offset = page["next_offset"]
            bundle = parse_result_section_bundle(accumulator.finish())
            assert bundle["section"]["section_id"] == section["section_id"]
            assert bundle["source_digest"] == directory["envelope_digest"]
            assert page_count > 1


@pytest.mark.parametrize("change", ["source", "foreign_project", "foreign_run", "resolver_denied"])
def test_http_page_cannot_bypass_owner_or_changed_source(tmp_path, monkeypatch, change):
    with live(tmp_path) as (client, owner, root):
        params = {"project_root": str(root), "section_id": "a", "offset": 0}
        run_id = "r1"
        if change == "source":
            (root / "runs" / "r1" / "a.json").write_bytes(b"changed")
        elif change == "foreign_project":
            params["project_root"] = str(tmp_path / "foreign")
        elif change == "foreign_run":
            run_id = "foreign"
        else:
            monkeypatch.setattr(app.state, "report_evidence_identity_resolver", lambda *_: None, raising=False)
        response = client.get(f"/runs/{run_id}/results/page", params=params)
        assert response.status_code in {403, 409}, response.text
        assert "delivery" not in response.json()


def test_http_page_unknown_selector_and_invalid_offset_fail(tmp_path):
    with live(tmp_path) as (client, owner, root):
        base = {"project_root": str(root), "section_id": "a"}
        assert client.get("/runs/r1/results/page", params={**base, "offset": -1}).status_code == 422
        assert client.get("/runs/r1/results/page", params={**base, "section_id": "unknown", "offset": 0}).status_code == 409


def test_owner_directory_rechecks_dependencies_and_budget(tmp_path):
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    with live(tmp_path) as (_, owner, root):
        with pytest.raises(EvidenceProjectionError):
            owner.read_result_section_directory(consumer_id="report", max_wire_bytes=100)
        (root / "runs" / "r1" / "b.json").write_bytes(b"changed")
        with pytest.raises(EvidenceProjectionError):
            owner.read_result_section_directory(consumer_id="report")


def test_actual_http_wire_budget_preserves_decomposed_owner_identity(tmp_path):
    import json
    from workbench.evidence.consumer_adapters import EvidenceProjectionError
    actor = "actor:" + "e\u0301" * 30
    with live(tmp_path, actor_ref=actor) as (client, owner, root):
        response = client.get("/runs/r1/results/page", params={"project_root": str(root),
            "section_id": "a", "offset": 0, "max_wire_bytes": 4500})
        assert response.status_code == 200, response.text
        assert response.json()["identity"]["actor_ref"] == actor
        assert len(response.content) <= 4500
        directory = owner.read_result_section_directory(consumer_id="report")
        size = len(json.dumps(directory, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode())
        with pytest.raises(EvidenceProjectionError, match="RESULT_PAGE_BUDGET_EXCEEDED"):
            owner.read_result_section_directory(consumer_id="report", max_wire_bytes=size - 1)
