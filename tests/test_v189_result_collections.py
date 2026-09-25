"""Real owner assembly: transport completeness is not statistical validation."""
import base64
import copy
import json
import pickle

import pytest

from tests.test_v189_evidence_report_boundary import _produced_report
from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.evidence.consumer_adapters import EvidenceProjectionError


def packet():
    return {"model_id": "ols_1", "model_type": "ols", "nobs": 20,
            "coefficients": {"统计🧪": {"estimate": 1.25, "std_error": .2, "p_value": 1e-20}}}


def test_real_writers_release_complete_collection_after_use(tmp_path):
    import gc
    import weakref
    run = tmp_path / "project" / "runs" / "writer-lifetime"
    with _produced_report(run, model_results={"ols_1": packet()}, diagnostic_summary={},
                          complete_collection=True) as case:
        table_writer = case.owner.issue_report_evidence_writer(case.projection, sections=("regression_table",))
        case.writer._assert_server_owned()
        table_writer._assert_server_owned()
        for issued in (case.writer, table_writer):
            forged = object.__new__(type(issued))
            for name in issued.__dataclass_fields__:
                object.__setattr__(forged, name, getattr(issued, name))
            with pytest.raises(TypeError, match="exact issuer identity"):
                forged._assert_server_owned()
        del issued, forged
        collection_ref = weakref.ref(case.projection)
        central_ref = weakref.ref(case.projection._collection)
        assert collection_ref() is case.projection
    del table_writer, case
    gc.collect()
    assert collection_ref() is None, "writer admission registry retains the complete Report collection"
    assert central_ref() is None, "writer admission registry retains the central evidence collection"


def test_owner_issues_distinct_complete_report_collection(tmp_path):
    from workbench.report_export import LocalReportCollectionV1, _validate_owner_bound_projection
    run = tmp_path / "project" / "runs" / "report-collection"
    with _produced_report(run, model_results={"ols_1": packet()}, diagnostic_summary={}) as case:
        result = case.owner.issue_complete_report_collection()
        assert type(result) is LocalReportCollectionV1
        assert result.wire["readCompleteness"] == "COMPLETE"
        assert result.wire["deliveryKind"] == "local_complete_collection"
        _validate_owner_bound_projection(result, case.owner)
        assert result.wire["regression_table"]["rows"][0]["term"] == "统计🧪"


def test_writer_issuance_rejects_equality_colliding_subclasses(tmp_path):
    from workbench.reporting import ReportDocumentWriterV1
    from workbench.report_export import ReportEvidenceWriterV1
    run = tmp_path / "project" / "runs" / "writer-subclass"
    accepted = []
    with _produced_report(run, model_results={"ols_1": packet()}, diagnostic_summary={},
                          complete_collection=True) as case:
        for base in (ReportDocumentWriterV1, ReportEvidenceWriterV1):
            forged = object.__new__(base)
            class CollidingWriter(base):
                def __hash__(self):
                    return hash(forged)
                def __eq__(self, other):
                    return other is forged
            try:
                if base is ReportDocumentWriterV1:
                    issued = CollidingWriter._from_server_view_model(case.view, case.projection,
                        owner=case.owner, canonical_run_root=run)
                else:
                    issued = CollidingWriter._from_server_projection(case.projection,
                        owner=case.owner, sections=("regression_table",))
            except TypeError:
                continue
            for name in issued.__dataclass_fields__:
                object.__setattr__(forged, name, getattr(issued, name))
            # The RED anchor proves the equality collision admitted a never-issued
            # exact base instance, not merely that subclass creation was possible.
            assert type(forged) is base
            forged._assert_server_owned()
            accepted.append(base.__name__)
        assert not accepted, f"subclass-issued equality collision admitted forged writers: {accepted}"


def test_complete_collection_preserves_every_section_and_original_fact(tmp_path):
    from workbench.evidence.result_collections import (
        collect_server_owned_local_results, validate_server_owned_local_result_collection,
    )
    run = tmp_path / "project" / "runs" / "complete"
    with _produced_report(run, model_results={"ols_1": packet()}, diagnostic_summary={}) as case:
        result = collect_server_owned_local_results(case.owner, max_wire_bytes=8192)
        validate_server_owned_local_result_collection(result, owner=case.owner)
        original = json.loads((run / "report_evidence.json").read_text())
        assert result.read_completeness == "COMPLETE"
        assert [s.to_dict() for s in result.sections] == original["family_evidence"]["structured_results"]["sections"]
        assert canonical_json_v1([f.to_dict() for f in result.facts]) == canonical_json_v1(original["numeric_facts"])
        assert len(result.section_directory) == len(result.sections)
        assert any(s["page_count"] > 1 for s in result.section_directory)
        assert all(s["received_bytes"] == s["total_bytes"] for s in result.section_directory)
        assert result.to_dict()["delivery_kind"] == "local_complete_collection"
        assert {f.validation_level.value for f in result.facts} == {"none"}
        wire = result.to_dict(); wire["facts"][0]["value"] = 0
        assert result.to_dict() != wire
        for attack in (lambda: copy.copy(result), lambda: pickle.dumps(result)):
            with pytest.raises(TypeError): attack()
        with pytest.raises(EvidenceProjectionError): validate_server_owned_local_result_collection(wire, owner=case.owner)
        with pytest.raises(EvidenceProjectionError):
            validate_server_owned_local_result_collection(object.__new__(type(result)), owner=case.owner)
        with pytest.raises(EvidenceProjectionError):
            validate_server_owned_local_result_collection(result, owner=object())
        (run / "model_results" / "ols_1.json").write_text("changed source")
        with pytest.raises(EvidenceProjectionError): validate_server_owned_local_result_collection(result, owner=case.owner)


def test_collection_refuses_missing_or_mixed_owner_page(tmp_path, monkeypatch):
    from workbench.evidence.result_collections import collect_server_owned_local_results
    from workbench.services.results_service import ServerOwnedReportEvidencePersistenceV1
    run = tmp_path / "project" / "runs" / "interrupted"
    with _produced_report(run, model_results={"ols_1": packet()}, diagnostic_summary={}) as case:
        original = ServerOwnedReportEvidencePersistenceV1.read_result_section_page
        calls = []
        def changed(self, **kwargs):
            wire = original(self, **kwargs)
            calls.append(kwargs["offset"])
            if len(calls) > 1:
                wire["identity"]["session_ref"] = "foreign-session"
            return wire
        monkeypatch.setattr(ServerOwnedReportEvidencePersistenceV1, "read_result_section_page", changed)
        with pytest.raises(EvidenceProjectionError): collect_server_owned_local_results(case.owner, max_wire_bytes=8192)
        assert len(calls) > 1


def test_collection_resource_ceiling_and_closed_owner(tmp_path, monkeypatch):
    from workbench.evidence import result_collections as api
    run = tmp_path / "project" / "runs" / "bounded"
    with _produced_report(run, model_results={"ols_1": packet()}, diagnostic_summary={}) as case:
        result = api.collect_server_owned_local_results(case.owner)
        with monkeypatch.context() as changes:
            changes.setattr(api, "MAX_COLLECTION_BYTES", 1)
            with pytest.raises(EvidenceProjectionError, match="resource ceiling"):
                api.collect_server_owned_local_results(case.owner)
        for limit in (0, True, 100):
            with pytest.raises(EvidenceProjectionError):
                api.collect_server_owned_local_results(case.owner, max_wire_bytes=limit)
    with pytest.raises(EvidenceProjectionError):
        api.validate_server_owned_local_result_collection(result, owner=case.owner)


@pytest.mark.parametrize("mutation", [
    "bundle_commit", "bundle_identity", "bundle_dependency", "nonfinal_row_zero",
    "inner_identity", "inner_destination",
])
def test_collection_rejects_rehashed_page_mutation_regression(tmp_path, monkeypatch, mutation):
    """Valid transport hashes/schema must not hide noncanonical owner content."""
    from workbench.contracts.evidence.result_pages import MAX_PAGE_BYTES, pack_result_page
    from workbench.evidence.consumer_adapters import parse_result_section_bundle
    from workbench.evidence.result_collections import collect_server_owned_local_results
    from workbench.services.results_service import ServerOwnedReportEvidencePersistenceV1

    run = tmp_path / "project" / "runs" / "mutation-regression"
    with _produced_report(run, model_results={"ols_1": packet()}, diagnostic_summary={}) as case:
        original = ServerOwnedReportEvidencePersistenceV1.read_result_section_page
        mutations = []
        limit = 8192 if mutation == "nonfinal_row_zero" else MAX_PAGE_BYTES

        def changed(self, **kwargs):
            wire = original(self, **kwargs)
            delivery = wire["delivery"]
            page = delivery["page"]
            if mutation in {"inner_identity", "inner_destination"}:
                original_page = copy.deepcopy(page)
                if mutation == "inner_identity":
                    before = delivery["identity"]["project_ref"]
                    assert before == case.owner.project_ref and before != "project:foreign"
                    delivery["identity"]["project_ref"] = "project:foreign"
                    assert delivery["identity"]["project_ref"] != before
                    assert wire["identity"]["project_ref"] == before
                else:
                    assert delivery["destination"] == wire["destination"] == "local"
                    delivery["destination"] = "remote"
                    assert delivery["destination"] != wire["destination"]
                # Only the inner wrapper changes; the admitted page/bundle stays intact.
                assert delivery["page"] == original_page
                for _ in range(8):
                    delivery["wire_digest"] = sha256_canonical(
                        {key: value for key, value in delivery.items() if key != "wire_digest"}
                    )
                    inner_size = (len(canonical_json_v1(delivery).encode("utf-8"))
                                  + delivery["audit"]["envelope_reserve_bytes"])
                    inner_charge = (inner_size + 3) // 4
                    if delivery["audit"]["token_budget"] == inner_charge:
                        break
                    delivery["audit"]["token_budget"] = inner_charge
                else:
                    pytest.fail("mutated inner wrapper charge did not converge")
                assert inner_size <= limit
                wire["receipt"]["payload_digest"] = delivery["wire_digest"]
            elif mutation == "nonfinal_row_zero":
                if page["next_offset"] is None or wire["audit"]["row_budget"] == 0:
                    return wire
                before = wire["audit"]["row_budget"]
                assert before > 0 and page["next_offset"] is not None
                wire["audit"]["row_budget"] = 0
                assert wire["audit"]["row_budget"] != before
            else:
                # The small real fixture fits each bundle in one default-size page.
                assert page["offset"] == 0 and page["next_offset"] is None
                before = base64.b64decode(page["payload_base64"], validate=True)
                bundle = json.loads(before)
                if mutation == "bundle_commit":
                    assert bundle["commit_id"] != "foreign-commit"
                    bundle["commit_id"] = "foreign-commit"
                elif mutation == "bundle_identity":
                    assert "model_run_id" in bundle["result_identity"]
                    assert bundle["result_identity"]["model_run_id"] != "foreign-model"
                    bundle["result_identity"]["model_run_id"] = "foreign-model"
                else:
                    records = bundle["result_dependencies"]["records"]
                    if not records:
                        return wire
                    assert records[0]["index_record"]["step"] != "foreign-step"
                    records[0]["index_record"]["step"] = "foreign-step"
                raw = canonical_json_v1(bundle).encode("utf-8")
                assert raw != before
                # This positive anchor excludes rejection by the ordinary schema.
                parse_result_section_bundle(raw)
                delivery["page"] = pack_result_page(
                    raw, binding=page["binding"], offset=0, max_wire_bytes=limit,
                ).to_dict()
                assert delivery["page"]["next_offset"] is None
                delivery["wire_digest"] = sha256_canonical(
                    {key: value for key, value in delivery.items() if key != "wire_digest"}
                )
                wire["receipt"]["payload_digest"] = delivery["wire_digest"]

            # Settle the final wrapper charge and receipt after the actual mutation.
            for _ in range(8):
                wire["receipt"]["wire_digest"] = sha256_canonical(
                    {key: value for key, value in wire.items() if key != "receipt"}
                )
                size = len(canonical_json_v1(wire).encode("utf-8"))
                charge = (size + 3) // 4
                if wire["audit"]["token_budget"] == charge:
                    break
                wire["audit"]["token_budget"] = charge
            else:
                pytest.fail("mutated wrapper charge did not converge")
            assert size <= limit
            assert wire["receipt"]["payload_digest"] == delivery["wire_digest"]
            assert delivery["wire_digest"] == sha256_canonical(
                {key: value for key, value in delivery.items() if key != "wire_digest"}
            )
            assert wire["receipt"]["wire_digest"] == sha256_canonical(
                {key: value for key, value in wire.items() if key != "receipt"}
            )
            mutations.append((kwargs["section_id"], kwargs["offset"]))
            return wire

        monkeypatch.setattr(ServerOwnedReportEvidencePersistenceV1, "read_result_section_page", changed)
        with pytest.raises(EvidenceProjectionError):
            try:
                collect_server_owned_local_results(case.owner, max_wire_bytes=limit)
            finally:
                # Runs even on early rejection: an unrelated pre-page error cannot pass.
                assert len(mutations) > 0, f"{mutation}: no anchored mutation was delivered"
                print(f"{mutation}: actual mutation count={len(mutations)}; pages={mutations}")
