"""Central section admission against real host-issued C0 and FD capabilities."""
import copy
import hashlib
import inspect
import json
from contextlib import contextmanager
from dataclasses import replace

import pytest

from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry, _load
from workbench.contracts.evidence.result_sections import RESULT_SECTIONS_CONTRACT_DIGEST
from workbench.evidence.consumer_adapters import (
    CONSUMER_PROJECTION_EVIDENCE_CONTRACT_DIGEST, ConsumerProjectionRegistryV1,
    EvidenceProjectionError, ServerOwnedEvidenceProjectionSourceV1,
    ServerOwnedEvidenceSensitivityPolicyV1, default_projection_registry,
)
from workbench.evidence.result_dependencies import capture_result_dependencies
from workbench.services.report_evidence_owner_factory import HostBoundProjectFileStoreV1
from tests.test_v189_report_result_sections import producer


@contextmanager
def committed(tmp_path, *, extension=True, manifest=True, label="sealed label", sensitivity="public",
              section_copies=1, reference_copies=1, blocked=False, regression=False,
              model_ids=("a", "b"), term="C(group)[T.a:b]",
              artifact_paths=("a.json", "b.json"), section_status=None, provenance=None):
    registry, host = _authorized_registry("scope:structured")
    root = tmp_path / "project"
    run = root / "runs" / "r1"
    run.mkdir(parents=True)
    rows = []
    for name, path in zip(("a", "b"), artifact_paths):
        raw = name.encode()
        (run / path).parent.mkdir(parents=True, exist_ok=True)
        (run / path).write_bytes(raw)
        rows.append(dict(artifact_id=name, path=path, artifact_type="model_results",
                         step="estimation", inputs=[], sha256=hashlib.sha256(raw).hexdigest()))
    index = dict(schema_version=1, artifacts=rows)
    (run / "artifacts_index.json").write_text(json.dumps(index))
    files = HostBoundProjectFileStoreV1.from_host(root, authority_handle=host.channel,
                                               scope_ref=registry.scope_ref)
    payload = copy.deepcopy(_load())
    payload["result_identity"].update(run_id="r1", project_ref="project:structured")
    payload["dependencies"] += [{"artifact_ref": name} for name in ("a", "b")]
    sections = []
    for name, fact in zip(("a", "b"), payload["numeric_facts"]):
        sections.append(dict(section_id=name, section_type="statistical_tests", schema_version=1,
            status="available", reason_codes=[], fact_refs=[fact["fact_id"]], dependency_refs=[name],
            content={"kind": "object", "fields": {"results": {"kind": "list", "items": [
                {"kind": "object", "fields": {
                    "label": {"kind": "text", "value": label},
                    "statistic": {"kind": "fact", "fact_id": fact["fact_id"], "representation": "number"},
                }}]}}}))
    for section in sections:
        items = section["content"]["fields"]["results"]["items"]
        section["content"]["fields"]["results"]["items"] = items * reference_copies
    if section_copies > 1:
        sections = [{**section, "section_id": f"{section['section_id']}:{i}"}
                    for section in sections for i in range(section_copies)]
    if regression:
        sections = [dict(section_id="coefficients", section_type="regression_table", schema_version=1,
            status="available", reason_codes=[], dependency_refs=["a", "b"],
            fact_refs=[f["fact_id"] for f in payload["numeric_facts"]],
            content={"kind": "object", "fields": {
                "models": {"kind": "list", "items": [{"kind": "object", "fields": {
                    "id": {"kind": "text", "value": m}}} for m in model_ids]},
                "rows": {"kind": "list", "items": [{"kind": "object", "fields": {
                    "term": {"kind": "text", "value": term},
                    "models": {"kind": "object", "fields": {m: {"kind": "object", "fields": {
                        "estimate": {"kind": "fact", "fact_id": f["fact_id"], "representation": "number"}}}
                        for m, f in zip(model_ids, payload["numeric_facts"])}}}}
                    ] * (2 if regression == "ambiguous" else 1)}}})]
        if regression in ("two_terms", "many_terms", "long_term", "delivery_edge"):
            rows_node = sections[0]["content"]["fields"]["rows"]
            template = rows_node["items"][0]
            rows_node["items"] = []
            for i in range(70 if regression == "many_terms" else 2):
                row = copy.deepcopy(template)
                row["fields"]["term"]["value"] = (
                    label if regression == "delivery_edge" else "T" * 3900 if regression == "long_term" else "C(x)[T.a:b]") + str(i)
                rows_node["items"].append(row)
        if regression == "roles":
            cells = sections[0]["content"]["fields"]["rows"]["items"][0]["fields"]["models"]["fields"]
            cells["a"]["fields"]["std_error"] = copy.deepcopy(cells["b"]["fields"]["estimate"])
            cells["a"]["fields"]["confidence_interval"] = {"kind": "list", "items": [
                copy.deepcopy(cells["a"]["fields"]["estimate"]), copy.deepcopy(cells["b"]["fields"]["estimate"])]}
    if provenance is not None:
        text = lambda value: {"kind": "text", "value": value}
        warnings = {"kind": "list", "items": [text("keep every warning")] * provenance.get("warning_count", 1)}
        cell = sections[0]["content"]["fields"]["rows"]["items"][0]["fields"]["models"]["fields"]["a"]["fields"]
        cell.update(variance_source=text("survey_design"), source_id=text("model_results.a.coefficients.x"), warnings=warnings)
        design = {"variance_method": text("provided_replicates"), "degf": {"kind": "fact", "fact_id": "fact-mean", "representation": "number"}, "warnings": warnings}
        for key in ("design_effect", "effective_sample_size", "replicates_attempted", "replicates_succeeded", "replicates_failed"):
            design[key] = {"kind": "fact", "fact_id": "fact-mean", "representation": "number"}
        design["replicate_failure_reasons"] = {"kind": "object", "fields": {
            "singular design": {"kind": "fact", "fact_id": "fact-coefficient", "representation": "number"}}}
        if provenance.get("missing"):
            design.pop("degf")
        sections.append(dict(section_id="survey", section_type="survey_design", schema_version=1,
            status="available", reason_codes=[], fact_refs=["fact-mean", "fact-coefficient"], dependency_refs=["a", "b"],
            content={"kind": "object", "fields": {"models": {"kind": "list", "items": [text("a")]},
                "design": {"kind": "object", "fields": {"a": {"kind": "object", "fields": design}}},
                "provenance": {"kind": "object", "fields": {}}}}))
        if provenance.get("ambiguous"):
            sections.append({**sections[-1], "section_id": "survey-duplicate"})
    if section_status is not None:
        sections[0].update(status=section_status, reason_codes=["PRODUCER_FIELD_UNDECLARED"],
                           fact_refs=[], dependency_refs=[], content={"kind": "null"})
    if extension:
        payload["family_evidence"]["structured_results"] = dict(schema_version=1,
            contract_digest=RESULT_SECTIONS_CONTRACT_DIGEST, sections=sections)
    if manifest:
        payload["family_evidence"]["result_dependencies"] = capture_result_dependencies(
            files, project_ref="project:structured", run_id="r1", artifact_ids=["a", "b"]).to_dict()
        for fact, row in zip(payload["numeric_facts"], rows):
            fact["source_selector"].update(artifact_ref=row["artifact_id"], artifact_digest=row["sha256"])
    if blocked:
        from tests.test_v189_evidence_envelope import _blocked_payload
        blocked_wire = _blocked_payload()
        for key in ("execution_status", "availability", "completeness_status", "execution_reasons",
                    "availability_reasons", "degradation_reasons", "numeric_facts", "figures", "validation_summary"):
            payload[key] = blocked_wire[key]
        for section in sections:
            section["fact_refs"] = []
            section["content"]["fields"]["results"]["items"][0]["fields"].pop("statistic")
    artifact = registry.admit_artifact(artifact_id="artifact-1", artifact_type="post_estimation",
        scope_ref=registry.scope_ref, content=payload, source_ref="source:dataset:1",
        validator_ref="validator:evidence-envelope:1", execution_ref="execution:r1",
        contract_digest=CONSUMER_PROJECTION_EVIDENCE_CONTRACT_DIGEST)
    packet_root = tmp_path / "packets"
    packet_root.mkdir()
    with _admit_store(packet_root, registry) as packets:
        receipt = registry.persistence_receipt(artifact)
        binding = packets.commit(artifact, receipt=receipt)
        policy = ServerOwnedEvidenceSensitivityPolicyV1._from_host(scope_ref=registry.scope_ref,
            artifact_id=artifact.artifact_id, commit_id=binding.commit_id,
            envelope_digest=binding.envelope_digest, sensitivity=sensitivity, authority_handle=host.channel)
        kwargs = dict(scope_ref=registry.scope_ref, artifact_id=artifact.artifact_id,
            commit_id=binding.commit_id, envelope_digest=binding.envelope_digest,
            sensitivity_policy=policy, authority_handle=host.channel)
        # Before implementation this still exercises the live old source and
        # fails on missing delivery, not an unexpected-keyword setup error.
        if "project_file_store" in inspect.signature(ServerOwnedEvidenceProjectionSourceV1).parameters:
            kwargs.update(project_file_store=files, project_ref="project:structured", run_id="r1",
                          canonical_project_root=root)
        source = ServerOwnedEvidenceProjectionSourceV1(packets, registry, receipt, **kwargs)
        try:
            yield source, run, index, sections, kwargs, (packets, registry, receipt)
        finally:
            files._admission.close()


def project(source, **kwargs):
    return default_projection_registry().project(source, consumer_id="results", destination="local", **kwargs)


@pytest.mark.parametrize("consumer", ["agent", "notebook", "report", "results"])
@pytest.mark.parametrize("extension", [False, True])
def test_unknown_local_profile_is_digest_bound_without_budget_changes(tmp_path, consumer, extension):
    with committed(tmp_path, sensitivity="unknown", extension=extension, manifest=extension) as (source, *_):
        registry = default_projection_registry()
        base = registry.resolve(consumer)
        result = registry.project(source, consumer_id=consumer, destination="local",
                                  requested_fact_ids=["fact-mean"])
        assert result.status.value == "available", result.audit.to_dict()
        assert [f.fact_id for f in result.facts] == ["fact-mean"]
        assert result.facts[0].value == _load()["numeric_facts"][0]["value"]
        assert "local_unknown" in result.audit.policy_ref.logical_id
        from workbench.evidence.consumer_adapters import _local_read_spec, _local_structured_spec
        declared = _local_structured_spec(base, "local") if extension else base
        local = _local_read_spec(declared, "local")
        assert (local.max_token_budget, local.max_row_budget) == (declared.max_token_budget, declared.max_row_budget)
        assert result.audit.policy_ref == local.policy_ref
        assert len(result.audit.policy_ref.contract_digest) == 64
        assert result.audit.policy_ref.contract_digest != base.policy_ref.contract_digest
        assert _local_read_spec(base, "remote") == base
        from workbench.evidence.consumer_adapters import _spec_for_audit_policy
        with pytest.raises(EvidenceProjectionError, match="delivery policy is not declared"):
            _spec_for_audit_policy(base, "local", replace(local.policy_ref, contract_digest="0" * 64))
        with pytest.raises(EvidenceProjectionError, match="delivery policy is not declared"):
            _spec_for_audit_policy(base, "remote", local.policy_ref)


@pytest.mark.parametrize("consumer", ["agent", "notebook", "report", "results"])
def test_unknown_remote_denied_even_with_permissive_custom_sensitivity(tmp_path, consumer):
    from workbench.contracts.agent.context_egress import SensitivityClassV1, ContextMaterializationStoreV1, EgressContractError
    from tests.test_v189_consumer_projection import _ref
    with committed(tmp_path, sensitivity="unknown") as (source, *_):
        registry = default_projection_registry()
        spec = registry.resolve(consumer)
        permissive = ConsumerProjectionRegistryV1([replace(spec,
            allowed_sensitivity=(*spec.allowed_sensitivity, SensitivityClassV1.UNKNOWN))])
        for selected in (registry, permissive):
            denied = selected.project(source, consumer_id=consumer, destination="remote")
            assert not denied.facts and not denied.sections and denied.result_dependencies is None
            assert denied.audit.restriction_reason == "sensitivity_not_allowed"
        with pytest.raises(EvidenceProjectionError, match="sensitivity_not_allowed"):
            registry.prepare_structured_projection_admission(source, consumer_id=consumer,
                destination="remote", requested_section_ids=("a",))
        with pytest.raises(EvidenceProjectionError, match="sensitivity_not_allowed"):
            registry.prepare_structured_projection_admission(source, consumer_id=consumer,
                destination="remote", page_selection=("a", 0, 8192))
        local = registry.project(source, consumer_id=consumer, destination="local", requested_section_ids=("a",))
        assert local.status.value == "available"
        store = ContextMaterializationStoreV1(materializer_ref=_ref("materializer", "materializer:unknown"),
            redaction_policy_ref=_ref("redaction-policy", "redaction:unknown"))
        with pytest.raises(EgressContractError):
            store.materialize({"evidence:projection": local.egress_payload()}, selected_refs=("evidence:projection",))
        with pytest.raises(EgressContractError):
            store.materialize_structured_projection(local)


@pytest.mark.parametrize("consumer", ["agent", "notebook", "report", "results"])
def test_unknown_local_profile_does_not_override_narrow_custom_spec(tmp_path, consumer):
    with committed(tmp_path, sensitivity="unknown") as (source, *_):
        spec = replace(default_projection_registry().resolve(consumer), max_row_budget=1)
        result = ConsumerProjectionRegistryV1([spec]).project(source,
            consumer_id=consumer, destination="local", requested_section_ids=("a",))
        assert not result.facts and not result.sections
        assert result.audit.policy_ref == spec.policy_ref
        assert result.audit.restriction_reason == "sensitivity_not_allowed"
        from workbench.evidence.consumer_adapters import _local_read_spec
        base = default_projection_registry().resolve(consumer)
        admitted = replace(_local_read_spec(base, "local"), max_row_budget=1)
        bounded = ConsumerProjectionRegistryV1([admitted]).project(source,
            consumer_id=consumer, destination="local", requested_section_ids=("a",))
        assert not bounded.facts and not bounded.sections
        assert bounded.audit.restriction_reason == "structured_projection_budget_exceeded"


@pytest.mark.parametrize("sensitivity", ["public", "unknown"])
@pytest.mark.parametrize("attack", ["consumer", "version", "projection", "renderer", "policy", "redacted_section", "omitted_section", "omitted_fact"])
def test_local_pages_bundle_rejects_inconsistent_declarations_and_audit(tmp_path, attack, sensitivity):
    import base64
    from workbench.canonical import canonical_json_v1
    from workbench.evidence.consumer_adapters import parse_result_section_bundle
    with committed(tmp_path, sensitivity=sensitivity) as (source, *_):
        admission = default_projection_registry().prepare_local_result_page_admission(
            source, consumer_id="agent", section_id="a")
        page = admission.page(offset=0)["page"]
        assert page["next_offset"] is None
        raw = base64.b64decode(page["payload_base64"])
        original = parse_result_section_bundle(raw)
        assert "b" in original["projection_metadata"]["audit"]["omitted_section_ids"]
        changed = json.loads(raw)
        meta = changed["projection_metadata"]
        audit = meta["audit"]
        if attack == "consumer": meta["consumer_id"] = "undeclared-consumer"
        elif attack == "version": meta["consumer_version"] = "999.0"
        elif attack == "projection": meta["projection_ref"]["contract_digest"] = "b" * 64
        elif attack == "renderer": meta["renderer_key"] = "undeclared.renderer"
        elif attack == "policy": audit["policy_ref"]["contract_digest"] = "b" * 64
        elif attack == "redacted_section": audit["redacted_section_ids"] = ["a"]
        elif attack == "omitted_section": audit["omitted_section_ids"].append("a")
        elif attack == "omitted_fact": audit["omitted_fact_ids"] = list(audit["selected_fact_ids"])
        with pytest.raises(EvidenceProjectionError):
            parse_result_section_bundle(canonical_json_v1(changed).encode())


def test_local_pages_large_section_lossless_real_source(tmp_path):
    from workbench.canonical import canonical_json_v1
    from workbench.contracts.evidence.result_pages import ResultPageV1, ResultPageAccumulatorV1
    from workbench.contracts.evidence.result_sections import ResultSectionV1
    from workbench.contracts.evidence.envelope import NumericFactV1
    with committed(tmp_path, label="β" * 1000, reference_copies=15) as (source, _, _, original, *_):
        registry = default_projection_registry()
        normal = registry.project(source, consumer_id="agent", destination="local", requested_section_ids=("a",))
        assert normal.audit.restriction_reason == "structured_projection_budget_exceeded"
        admission = registry.prepare_local_result_page_admission(source, consumer_id="agent", section_id="a")
        offset, accumulator, count = 0, None, 0
        while True:
            wire = admission.page(offset=offset, max_wire_bytes=4096, envelope_reserve_bytes=700)
            assert len(canonical_json_v1(wire).encode("utf-8")) + 700 <= 4096
            page = ResultPageV1.from_dict(wire["page"])
            if accumulator is None:
                accumulator = ResultPageAccumulatorV1(page.binding, max_total_bytes=1_000_000)
            accumulator.add(page)
            count += 1
            if page.next_offset is None:
                break
            offset = page.next_offset
        assert count > 1
        bundle = json.loads(accumulator.finish())
        from workbench.evidence.consumer_adapters import parse_result_section_bundle
        assert parse_result_section_bundle(accumulator.finish())["source_ref"] == source.artifact_id
        for attack in ("extra", "fact", "dependency", "metadata", "audit"):
            changed = copy.deepcopy(bundle)
            if attack == "extra":
                changed["unknown"] = True
            elif attack == "fact":
                changed["facts"] = []
            elif attack == "dependency":
                changed["result_dependencies"]["records"] = []
            elif attack == "metadata":
                changed["projection_metadata"]["status"] = "invented"
            else:
                changed["projection_metadata"]["audit"]["unsafe_extra"] = "untrusted"
            with pytest.raises(EvidenceProjectionError):
                parse_result_section_bundle(canonical_json_v1(changed).encode("utf-8"))
        assert bundle["section"] == original[0]
        assert {r["artifact_id"] for r in bundle["result_dependencies"]["records"]} == {"a"}
        facts = {f["fact_id"]: NumericFactV1.from_dict(f) for f in bundle["facts"]}
        parsed = ResultSectionV1.from_dict(bundle["section"], facts=facts, dependency_ids={"a"})
        assert set(facts) == set(parsed.fact_refs)
        assert bundle["commit_id"] == source.commit_id


@pytest.mark.parametrize("attack", ["bytes_a", "bytes_b", "index", "context"])
def test_local_pages_recheck_entire_selected_closure(tmp_path, attack):
    with committed(tmp_path, regression=True) as (source, run, index, *_):
        admission = default_projection_registry().prepare_local_result_page_admission(
            source, consumer_id="agent", section_id="coefficients")
        first = admission.page(offset=0, max_wire_bytes=2000)
        assert first["page"]["next_offset"] is not None
        if attack.startswith("bytes_"):
            (run / (attack[-1] + ".json")).write_bytes(b"tampered")
        elif attack == "index":
            index["artifacts"][1]["step"] = "foreign"
            (run / "artifacts_index.json").write_text(json.dumps(index))
        else:
            object.__setattr__(source, "_run_id", "foreign")
        with pytest.raises(EvidenceProjectionError):
            admission.page(offset=first["page"]["next_offset"], max_wire_bytes=2000)


@pytest.mark.parametrize("case", ["remote", "missing", "blocked", "sensitivity", "dict_source", "budget", "offset", "reserve"])
def test_local_pages_fail_closed(tmp_path, case):
    with committed(tmp_path, blocked=case == "blocked", sensitivity="restricted" if case == "sensitivity" else "public") as (source, *_):
        registry = default_projection_registry()
        with pytest.raises(EvidenceProjectionError):
            admission = registry.prepare_local_result_page_admission(
                {} if case == "dict_source" else source, consumer_id="agent",
                section_id="missing" if case == "missing" else "a",
                destination="remote" if case == "remote" else "local")
            admission.page(offset=-1 if case == "offset" else 0,
                max_wire_bytes=1 if case == "budget" else 4096,
                envelope_reserve_bytes=4096 if case == "reserve" else 0)


def test_local_pages_full_section_rows_not_base64_row(tmp_path):
    with committed(tmp_path, reference_copies=40) as (source, *_):
        registry = default_projection_registry()
        with pytest.raises(EvidenceProjectionError) as caught:
            registry.prepare_local_result_page_admission(source, consumer_id="agent", section_id="a")
        assert caught.value.code == "RESULT_PAGE_ROW_BUDGET_EXCEEDED"
        local = registry.prepare_local_result_page_admission(source, consumer_id="results", section_id="a")
        assert local.page(offset=0)["audit"]["row_budget"] == 83


def test_local_pages_unrelated_dependency_and_original_fact_values(tmp_path):
    from workbench.contracts.common.envelope import thaw_json
    with committed(tmp_path) as (source, run, *_):
        registry = default_projection_registry()
        admission = registry.prepare_local_result_page_admission(source, consumer_id="agent", section_id="a")
        before = thaw_json(admission.page(offset=0))
        (run / "b.json").write_bytes(b"unrelated change")
        assert thaw_json(admission.page(offset=0)) == before


def test_local_pages_exact_issuer_and_declared_policy(tmp_path):
    from workbench.evidence.consumer_adapters import ServerOwnedLocalResultPageAdmissionV1
    with committed(tmp_path) as (source, *_):
        registry = default_projection_registry()
        admission = registry.prepare_local_result_page_admission(source, consumer_id="agent", section_id="a")
        with pytest.raises(TypeError):
            copy.copy(admission)
        forged = object.__new__(ServerOwnedLocalResultPageAdmissionV1)
        with pytest.raises(EvidenceProjectionError, match="RESULT_PAGE_AUTHORITY_REQUIRED"):
            forged.page(offset=0)
        custom = ConsumerProjectionRegistryV1([replace(registry.resolve("agent"), max_token_budget=999999)])
        with pytest.raises(EvidenceProjectionError, match="RESULT_PAGE_POLICY_NOT_DECLARED"):
            custom.prepare_local_result_page_admission(source, consumer_id="agent", section_id="a")
        with pytest.raises(EvidenceProjectionError, match="RESULT_PAGE_BUDGET_EXCEEDED"):
            admission.page(offset=0, max_wire_bytes=4096 * 4 + 1)


@pytest.mark.parametrize("section_status", ["unavailable", "not_applicable"])
def test_local_pages_preserve_closed_section_status(tmp_path, section_status):
    from workbench.contracts.evidence.result_pages import ResultPageV1, ResultPageAccumulatorV1
    from workbench.evidence.consumer_adapters import parse_result_section_bundle
    with committed(tmp_path, section_status=section_status) as (source, _, _, original, *_):
        admission = default_projection_registry().prepare_local_result_page_admission(
            source, consumer_id="agent", section_id="a")
        wire = admission.page(offset=0)
        page = ResultPageV1.from_dict(wire["page"])
        accumulator = ResultPageAccumulatorV1(page.binding, max_total_bytes=100000)
        accumulator.add(page)
        bundle = parse_result_section_bundle(accumulator.finish())
        from workbench.contracts.common.envelope import thaw_json
        assert thaw_json(bundle["section"]) == original[0]
        assert bundle["facts"] == ()
        assert bundle["result_dependencies"]["records"] == ()
        assert bundle["section"]["status"] == section_status
        assert wire["audit"]["row_budget"] == 1


@pytest.mark.parametrize("consumer_id", [[], {}])
def test_local_pages_consumer_id_type_checked_before_lookup(tmp_path, consumer_id):
    with committed(tmp_path) as (source, *_):
        with pytest.raises(EvidenceProjectionError) as caught:
            default_projection_registry().prepare_local_result_page_admission(
                source, consumer_id=consumer_id, section_id="a")
        assert caught.value.code == "PROJECTION_TEXT_INVALID"


def _structured_transport(admission, *, allowed=("public", "internal")):
    from datetime import datetime
    from tests.test_v189_consumer_projection import _ref
    from workbench.contracts.agent.context_egress import (
        ContextMaterializationStoreV1, ContextEgressPolicyV1, ContextEgressGatewayV1,
        ContextEgressReceiptIssuerV1, SensitivityClassV1,
    )
    store = ContextMaterializationStoreV1(materializer_ref=_ref("materializer", "structured-test"),
        redaction_policy_ref=_ref("redaction-policy", "structured-test"))
    materialized = store.materialize_structured_projection(admission)
    policy = ContextEgressPolicyV1(policy_ref=_ref("egress-policy", "structured-test"), destination="remote",
        provider_ref="provider:structured-test", allowed_sensitivity=tuple(SensitivityClassV1(s) for s in allowed),
        max_token_budget=4096, max_row_budget=64, max_time_budget_ms=5000)
    gateway = ContextEgressGatewayV1.from_materialization_result(materialized, request_id="structured-request",
        destination="remote", provider_ref="provider:structured-test", sensitivity_policy_ref=policy.policy_ref,
        sensitivity=materialized.observed_sensitivity, token_budget=4096, row_budget=64, time_budget_ms=1000,
        purpose_ref="purpose:structured-test", requested_at="2026-09-14T10:00:00+00:00", expires_at="2026-09-14T11:00:00+00:00")
    now = [datetime.fromisoformat("2026-09-14T10:30:00+00:00")]
    issuer = ContextEgressReceiptIssuerV1(policy, materializer_store=store, clock=lambda: now[0])
    return store, materialized, gateway, issuer, now


def test_remote_page_requires_exact_materialized_receipt_and_current_source(tmp_path):
    from workbench.contracts.evidence.result_pages import ResultPageAccumulatorV1, ResultPageV1
    from workbench.evidence.consumer_adapters import parse_result_section_bundle
    from workbench.canonical import canonical_json_v1
    with committed(tmp_path, label="统计🧪" * 200) as (source, run, *_):
        registry = default_projection_registry()
        offset, accumulator, count = 0, None, 0
        while offset is not None:
            admission = registry.prepare_remote_result_page_admission(source, consumer_id="agent",
                section_id="a", offset=offset, max_wire_bytes=4500)
            with pytest.raises(EvidenceProjectionError):
                registry.deliver_remote_result_page(admission)
            _, _, gateway, issuer, _ = _structured_transport(admission)
            result = registry.deliver_remote_result_page(admission, gateway=gateway,
                issuer=issuer, receipt=issuer.issue(gateway))
            assert len(canonical_json_v1(result).encode()) <= 4500
            assert result["read_completeness"] == "PARTIAL"
            page = ResultPageV1.from_dict(result["payload"]["page"])
            assert page.binding["destination"] == "remote"
            if accumulator is None:
                accumulator = ResultPageAccumulatorV1(page.binding, max_total_bytes=100000)
            accumulator.add(page)
            offset, count = page.next_offset, count + 1
        bundle = parse_result_section_bundle(accumulator.finish())
        assert bundle["section"]["section_id"] == "a" and count > 1
        (run / "a.json").write_bytes(b"changed")
        with pytest.raises(EvidenceProjectionError):
            registry.deliver_remote_result_page(admission, gateway=gateway, issuer=issuer, receipt=issuer.issue(gateway))


@pytest.mark.parametrize("attack", ["wrong_page", "wrong_provider", "expired", "forged_admission", "over_rows"])
def test_remote_page_rejects_egress_and_budget_substitution(tmp_path, attack):
    from datetime import timedelta
    with committed(tmp_path, reference_copies=80 if attack == "over_rows" else 1) as (source, *_):
        registry = default_projection_registry()
        if attack == "over_rows":
            with pytest.raises(EvidenceProjectionError):
                registry.prepare_remote_result_page_admission(source, consumer_id="agent", section_id="a", offset=0)
            return
        admission = registry.prepare_remote_result_page_admission(source, consumer_id="agent", section_id="a", offset=0)
        _, _, gateway, issuer, now = _structured_transport(admission)
        receipt = issuer.issue(gateway)
        if attack == "wrong_page":
            admission = registry.prepare_remote_result_page_admission(source, consumer_id="agent", section_id="b", offset=0)
        elif attack == "wrong_provider":
            gateway = replace(gateway, provider_ref="other:provider")
        elif attack == "expired":
            now[0] += timedelta(hours=2)
        else:
            admission = object.__new__(type(admission))
        with pytest.raises(EvidenceProjectionError):
            registry.deliver_remote_result_page(admission, gateway=gateway, issuer=issuer, receipt=receipt)


def test_admission_real_materializer_receipt_roundtrip_and_source_sensitivity(tmp_path):
    from workbench.evidence.consumer_adapters import validate_server_owned_structured_projection_admission
    from workbench.canonical import canonical_json_v1, sha256_canonical
    with committed(tmp_path, sensitivity="internal") as (source, *_):
        registry = default_projection_registry()
        selection = dict(requested_section_ids=("a",))
        admission = registry.prepare_structured_projection_admission(source, consumer_id="agent", destination="remote", **selection)
        context, observed = validate_server_owned_structured_projection_admission(admission)
        assert observed.value == "internal"
        assert context["evidence:projection"]["sections"][0]["section_id"] == "a"
        with pytest.raises(TypeError): context["evidence:projection"]["sections"][0]["section_id"] = "forged"
        _, materialized, gateway, issuer, _ = _structured_transport(admission)
        assert materialized.observed_sensitivity is observed
        assert materialized.materialized_payload_digest == sha256_canonical(context)
        assert registry.project(source, consumer_id="agent", destination="remote", **selection).audit.restriction_reason == "egress_receipt_required"
        receipt = issuer.issue(gateway)
        result = registry.project(source, consumer_id="agent", destination="remote", gateway=gateway, issuer=issuer,
                                  receipt=receipt, **selection)
        assert result.status.value == "available", result.audit
        assert canonical_json_v1(result.egress_payload()) == canonical_json_v1(context["evidence:projection"])
        assert result.audit.token_budget <= 4096 and result.audit.row_budget <= 64


@pytest.mark.parametrize("attack", ["dict", "tuple", "constructor", "forged_exact", "copy", "pickle"])
def test_admission_exact_private_issuer_not_value_authority(tmp_path, attack):
    import pickle
    from workbench.evidence.consumer_adapters import (
        ServerOwnedStructuredProjectionAdmissionV1, validate_server_owned_structured_projection_admission,
    )
    with committed(tmp_path) as (source, *_):
        admission = default_projection_registry().prepare_structured_projection_admission(source, consumer_id="agent",
            destination="remote", requested_section_ids=("a",))
        if attack in {"constructor", "copy", "pickle"}:
            with pytest.raises((TypeError, EvidenceProjectionError)):
                {"constructor": lambda: ServerOwnedStructuredProjectionAdmissionV1(),
                 "copy": lambda: copy.copy(admission), "pickle": lambda: pickle.dumps(admission)}[attack]()
        else:
            fake = {} if attack == "dict" else (validate_server_owned_structured_projection_admission(admission)
                if attack == "tuple" else object.__new__(ServerOwnedStructuredProjectionAdmissionV1))
            with pytest.raises(EvidenceProjectionError): validate_server_owned_structured_projection_admission(fake)


@pytest.mark.parametrize("attack", ["bytes", "index", "host_context", "closed_store"])
def test_admission_revalidates_live_source_and_dependency_proof(tmp_path, attack):
    from workbench.evidence.consumer_adapters import validate_server_owned_structured_projection_admission
    with committed(tmp_path) as (source, run, index, _, kwargs, _):
        admission = default_projection_registry().prepare_structured_projection_admission(source, consumer_id="agent",
            destination="remote", requested_section_ids=("a",))
        validate_server_owned_structured_projection_admission(admission)
        if attack == "bytes": (run / "a.json").write_bytes(b"tampered")
        elif attack == "index":
            index["artifacts"][0]["path"] = "b.json"
            (run / "artifacts_index.json").write_text(json.dumps(index))
        elif attack == "host_context": object.__setattr__(source, "_run_id", "foreign")
        else: kwargs["project_file_store"]._admission.close()
        with pytest.raises(EvidenceProjectionError): validate_server_owned_structured_projection_admission(admission)


def test_admission_does_not_upgrade_local_profile_or_accept_caller_policy(tmp_path):
    with committed(tmp_path, label="T" * 3000, reference_copies=2) as (source, *_):
        registry = default_projection_registry()
        assert project(source).status.value == "available"
        with pytest.raises(EvidenceProjectionError):
            registry.prepare_structured_projection_admission(source, consumer_id="results", destination="remote")
        with pytest.raises(EvidenceProjectionError):
            registry.prepare_structured_projection_admission(source, consumer_id="results", destination="local")
        spec = replace(registry.resolve("results"), max_token_budget=100000, max_row_budget=10000)
        with pytest.raises(EvidenceProjectionError):
            ConsumerProjectionRegistryV1([spec]).prepare_structured_projection_admission(source,
                consumer_id="results", destination="remote")


def test_admission_is_not_egress_policy_permission(tmp_path):
    from workbench.contracts.agent.context_egress import EgressContractError
    with committed(tmp_path, sensitivity="internal") as (source, *_):
        admission = default_projection_registry().prepare_structured_projection_admission(source, consumer_id="agent",
            destination="remote", requested_section_ids=("a",))
        _, _, gateway, issuer, _ = _structured_transport(admission, allowed=("public",))
        with pytest.raises(EgressContractError): issuer.issue(gateway)


@pytest.mark.parametrize("attack", ["selection", "source", "expiry", "provider", "purpose", "sensitivity"])
def test_admission_final_remote_rechecks_payload_source_and_receipt(tmp_path, attack):
    from datetime import datetime
    from workbench.contracts.agent.context_egress import SensitivityClassV1
    with committed(tmp_path) as (source, run, *_):
        registry = default_projection_registry()
        admission = registry.prepare_structured_projection_admission(source, consumer_id="agent", destination="remote",
            requested_section_ids=("a",))
        _, _, gateway, issuer, now = _structured_transport(admission)
        receipt = issuer.issue(gateway)
        selection = ("a",)
        if attack == "selection": selection = ("b",)
        elif attack == "source": (run / "a.json").write_bytes(b"changed after receipt")
        elif attack == "expiry": now[0] = datetime.fromisoformat("2026-09-14T11:00:00+00:00")
        elif attack == "provider": gateway = replace(gateway, provider_ref="provider:other")
        elif attack == "purpose": gateway = replace(gateway, purpose_ref="purpose:other")
        else: gateway = replace(gateway, sensitivity=SensitivityClassV1.INTERNAL)
        result = registry.project(source, consumer_id="agent", destination="remote", requested_section_ids=selection,
            gateway=gateway, receipt=receipt, issuer=issuer)
        assert result.status.value in {"blocked", "unavailable"}, result.audit
        assert not result.facts and not result.sections and result.result_dependencies is None


def test_admission_semantic_full_parent_closure_and_selector_snapshot(tmp_path):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1, validate_server_owned_structured_projection_admission
    with committed(tmp_path, regression=True, model_ids=("logical-model", "other-model")) as (source, run, *_):
        selector = ModelCoefficientSelectionV1("logical-model")
        admission = default_projection_registry().prepare_structured_projection_admission(source, consumer_id="agent",
            destination="remote", coefficient_selection=selector)
        object.__setattr__(selector, "model_id", "other-model")
        context, _ = validate_server_owned_structured_projection_admission(admission)
        payload = context["evidence:projection"]
        assert payload["semantic_selection"]["model_id"] == "logical-model"
        assert [f["fact_id"] for f in payload["facts"]] == ["fact-mean"] and not payload["sections"]
        assert {r["artifact_id"] for r in payload["result_dependencies"]["records"]} == {"a", "b"}
        store, *_ = _structured_transport(admission)
        (run / "b.json").write_bytes(b"parent dependency changed")
        from workbench.contracts.agent.context_egress import EgressContractError
        with pytest.raises(EgressContractError) as rejected:
            store.materialize_structured_projection(admission)
        assert rejected.value.code == "EGRESS_STRUCTURED_ADMISSION_INVALID"


def test_admission_does_not_replace_generic_materialization_rules(tmp_path):
    from workbench.contracts.agent.context_egress import EgressContractError
    from workbench.evidence.consumer_adapters import validate_server_owned_structured_projection_admission
    with committed(tmp_path) as (source, *_):
        admission = default_projection_registry().prepare_structured_projection_admission(source, consumer_id="agent",
            destination="remote", requested_section_ids=("a",))
        store, *_ = _structured_transport(admission)
        context, observed = validate_server_owned_structured_projection_admission(admission)
        with pytest.raises(EgressContractError): store.materialize(context, selected_refs=("evidence:projection",))
        with pytest.raises(EgressContractError): store.materialize_structured_projection((context, observed))


def test_admission_final_receipt_metadata_remains_budgeted(tmp_path):
    witnessed = False
    for size in range(2500, 2701, 20):
        with committed(tmp_path / str(size), label="T" * size, reference_copies=2) as (source, *_):
            registry = default_projection_registry()
            try:
                admission = registry.prepare_structured_projection_admission(source, consumer_id="agent", destination="remote")
            except EvidenceProjectionError as exc:
                assert exc.code == "structured_projection_budget_exceeded"
                continue
            _, _, gateway, issuer, _ = _structured_transport(admission)
            result = registry.project(source, consumer_id="agent", destination="remote", gateway=gateway,
                issuer=issuer, receipt=issuer.issue(gateway))
            if result.status.value == "unavailable":
                assert result.audit.restriction_reason == "structured_projection_budget_exceeded"
                assert not result.facts and not result.sections
                print(f"REMOTE_FINAL_BUDGET_BOUNDARY label_chars={size}")
                witnessed = True
                break
            assert result.status.value == "available" and result.audit.token_budget <= 4096
    assert witnessed, "must exercise final receipt metadata crossing the central cap"


def test_provenance_real_owner_selected_bindings_and_parent_closure(tmp_path):
    from workbench.evidence import consumer_adapters as adapters
    selector = getattr(adapters, "ModelProvenanceSelectionV1", None)
    assert selector is not None, "bounded typed provenance selector is required"
    with committed(tmp_path, regression=True, provenance={}) as (source, run, *_):
        query = selector("a", terms=("C(group)[T.a:b]",), roles=("survey_variance_method", "survey_degf", "survey_warnings", "coefficient_variance_source", "coefficient_source_id", "coefficient_warnings"))
        result = project(source, provenance_selection=query)
        assert result.status.value == "available", result.audit
        wire = result.to_dict()
        selection = wire["semantic_selection"]
        assert selection["scope"] == "selected_only" and selection["whole_result_read"] is False
        bindings = {b["role"]: b for b in selection["bindings"]}
        assert bindings["survey_variance_method"]["value"] == {"kind": "text", "value": "provided_replicates"}
        assert bindings["survey_degf"]["fact_id"] == "fact-mean"
        assert bindings["coefficient_variance_source"]["value"]["value"] == "survey_design"
        assert bindings["coefficient_source_id"]["value"]["value"] == "model_results.a.coefficients.x"
        for role in ("survey_warnings", "coefficient_warnings"):
            assert bindings[role]["value"]["items"] == [{"kind": "text", "value": "keep every warning"}]
        assert all(b["model_id"] == "a" for b in bindings.values())
        assert bindings["survey_degf"]["term"] is None
        assert bindings["coefficient_source_id"]["term"] == "C(group)[T.a:b]"
        assert result.fact_ids == ("fact-mean",) and not result.sections
        assert [r["artifact_id"] for r in wire["result_dependencies"]["records"]] == ["a", "b"]
        assert result.audit.row_budget <= 64
        (run / "b.json").write_bytes(b"changed parent dependency")
        denied = project(source, provenance_selection=query)
        assert denied.status.value == "unavailable" and denied.semantic_selection is None and not denied.facts


@pytest.mark.parametrize("case,reason", [("missing", "semantic_role_unavailable"), ("ambiguous", "semantic_selection_ambiguous"), ("warnings", "structured_projection_budget_exceeded")])
def test_provenance_real_owner_fail_closed(tmp_path, case, reason):
    from workbench.evidence import consumer_adapters as adapters
    selector = getattr(adapters, "ModelProvenanceSelectionV1", None)
    assert selector is not None
    options = {case: True} if case != "warnings" else {"warning_count": 65}
    with committed(tmp_path, regression=True, provenance=options) as (source, *_):
        result = default_projection_registry().project(source, consumer_id="agent", destination="local",
            provenance_selection=selector("a", roles=("survey_degf", "survey_warnings")))
        assert result.status.value == "unavailable" and result.audit.restriction_reason == reason
        assert not result.facts and result.semantic_selection is None


def test_semantic_exact_model_term_and_closure(tmp_path):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with committed(tmp_path, regression=True) as (source, run, *_):
        selection = ModelCoefficientSelectionV1("a", terms=("C(group)[T.a:b]",))
        result = project(source, coefficient_selection=selection)
        assert result.status.value == "available"
        assert result.fact_ids == ("fact-mean",) and result.sections == ()
        binding = result.to_dict()["semantic_selection"]["bindings"]
        assert binding == [{"section_id": "coefficients", "model_id": "a",
            "term": "C(group)[T.a:b]", "role": "estimate", "fact_id": "fact-mean"}]
        assert [r["artifact_id"] for r in result.to_dict()["result_dependencies"]["records"]] == ["a", "b"]
        (run / "b.json").write_bytes(b"parent table dependency tamper")
        assert project(source, coefficient_selection=selection).status.value == "unavailable"
        assert project(source, coefficient_selection=ModelCoefficientSelectionV1("b")).status.value == "unavailable"


def test_provenance_all_declared_roles_keep_nested_facts_and_defensive_values(tmp_path):
    from workbench.evidence.consumer_adapters import ModelProvenanceSelectionV1, PROVENANCE_ROLE_PATHS_V1
    with committed(tmp_path, regression=True, provenance={}) as (source, *_):
        selection = ModelProvenanceSelectionV1("a", terms=("C(group)[T.a:b]",), roles=tuple(PROVENANCE_ROLE_PATHS_V1))
        result = default_projection_registry().project(source, consumer_id="agent", destination="local", provenance_selection=selection)
        assert result.status.value == "available", result.audit
        wire = result.to_dict()
        bindings = {b["role"]: b for b in wire["semantic_selection"]["bindings"]}
        assert set(bindings) == set(PROVENANCE_ROLE_PATHS_V1)
        assert result.fact_ids == ("fact-mean", "fact-coefficient")
        for role in ("survey_design_effect", "survey_effective_sample_size", "survey_replicates_attempted", "survey_replicates_succeeded", "survey_replicates_failed"):
            assert bindings[role]["fact_id"] == "fact-mean"
        assert bindings["survey_replicate_failure_reasons"]["value"]["fields"]["singular design"]["fact_id"] == "fact-coefficient"
        assert result.audit.row_budget == 25
        bindings["coefficient_warnings"]["value"]["items"].clear()
        assert len(next(b for b in result.to_dict()["semantic_selection"]["bindings"] if b["role"] == "coefficient_warnings")["value"]["items"]) == 1


@pytest.mark.parametrize("other", ["coefficient_selection", "requested_fact_ids", "requested_section_ids", "requested_section_types", "wrong_type", "wrong_slot", "foreign", "term"])
def test_provenance_public_query_is_exact_and_exclusive(tmp_path, other):
    from workbench.evidence.consumer_adapters import ModelProvenanceSelectionV1, ModelCoefficientSelectionV1
    with committed(tmp_path, regression=True, provenance={}) as (source, *_):
        selector = ModelProvenanceSelectionV1("a", roles=("survey_degf",))
        query = {"provenance_selection": selector}
        reason = "semantic_selection_mixed"
        if other == "coefficient_selection": query[other] = ModelCoefficientSelectionV1("a")
        elif other.startswith("requested_"): query[other] = ()
        elif other == "wrong_type":
            query["provenance_selection"] = ModelCoefficientSelectionV1("a")
            reason = "semantic_selector_invalid"
        elif other == "wrong_slot":
            query = {"coefficient_selection": selector}
            reason = "semantic_selector_invalid"
        elif other == "foreign":
            query["provenance_selection"] = ModelProvenanceSelectionV1("foreign", roles=("survey_degf",))
            reason = "semantic_model_unavailable"
        else:
            query["provenance_selection"] = ModelProvenanceSelectionV1("a", terms=("missing",), roles=("coefficient_source_id",))
            reason = "semantic_term_unavailable"
        result = project(source, **query)
        assert result.status.value == "unavailable" and result.audit.restriction_reason == reason
        assert not result.facts and not result.sections and result.semantic_selection is None


def test_provenance_remote_exact_receipt_and_snapshot(tmp_path):
    from workbench.evidence.consumer_adapters import ModelProvenanceSelectionV1, validate_server_owned_structured_projection_admission
    with committed(tmp_path, regression=True, provenance={}) as (source, run, *_):
        registry = default_projection_registry()
        selector = ModelProvenanceSelectionV1("a", roles=("survey_variance_method", "survey_degf"))
        admission = registry.prepare_structured_projection_admission(source, consumer_id="agent", destination="remote", provenance_selection=selector)
        object.__setattr__(selector, "roles", ("survey_warnings",))
        context, _ = validate_server_owned_structured_projection_admission(admission)
        assert tuple(context["evidence:projection"]["semantic_selection"]["roles"]) == ("survey_degf", "survey_variance_method")
        _, _, gateway, issuer, _ = _structured_transport(admission)
        receipt = issuer.issue(gateway)
        original = ModelProvenanceSelectionV1("a", roles=("survey_variance_method", "survey_degf"))
        delivered = registry.project(source, consumer_id="agent", destination="remote", provenance_selection=original,
            gateway=gateway, issuer=issuer, receipt=receipt)
        assert delivered.status.value == "available", delivered.audit
        from workbench.contracts.common.envelope import thaw_json
        assert delivered.egress_payload() == thaw_json(context["evidence:projection"])
        changed = registry.project(source, consumer_id="agent", destination="remote", provenance_selection=selector,
            gateway=gateway, issuer=issuer, receipt=receipt)
        assert changed.status.value == "unavailable" and changed.semantic_selection is None
        (run / "b.json").write_bytes(b"changed parent")
        denied = registry.project(source, consumer_id="agent", destination="remote", provenance_selection=original,
            gateway=gateway, issuer=issuer, receipt=receipt)
        assert denied.status.value in {"unavailable", "blocked"} and not denied.facts and denied.semantic_selection is None


@pytest.mark.parametrize("options", [
    {"roles": ("arbitrary.path",)}, {"roles": ()},
    {"roles": ("coefficient_warnings",)},
    {"roles": ("survey_degf",), "terms": ("x",)},
    {"roles": ("coefficient_source_id",), "terms": ("x", "x")},
])
def test_provenance_selector_rejects_undeclared_or_ambiguous_requests(options):
    from workbench.evidence.consumer_adapters import ModelProvenanceSelectionV1
    with pytest.raises(EvidenceProjectionError):
        ModelProvenanceSelectionV1("a", **options)


def test_provenance_text_only_is_available_and_still_dependency_bound(tmp_path):
    from workbench.evidence.consumer_adapters import ModelProvenanceSelectionV1
    with committed(tmp_path, regression=True, provenance={}) as (source, run, *_):
        selection = ModelProvenanceSelectionV1("a", terms=("C(group)[T.a:b]",),
            roles=("coefficient_source_id", "coefficient_variance_source", "coefficient_warnings"))
        result = default_projection_registry().project(source, consumer_id="agent", destination="local", provenance_selection=selection)
        assert result.status.value == "available" and not result.facts and not result.sections
        assert len(result.semantic_selection["bindings"]) == 3
        assert result.audit.row_budget == 6
        assert len(json.dumps(result.to_dict()).encode()) < 8192
        (run / "b.json").write_bytes(b"changed text-only source closure")
        denied = project(source, provenance_selection=selection)
        assert denied.status.value == "unavailable" and denied.semantic_selection is None


@pytest.mark.parametrize("attack", ["bytes", "index"])
def test_spec3_semantic_retains_all_parent_dependencies(tmp_path, attack):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with committed(tmp_path, regression=True) as (source, run, index, *_):
        selection = ModelCoefficientSelectionV1("a")
        assert project(source, coefficient_selection=selection).status.value == "available"
        if attack == "bytes":
            assert (run / "b.json").read_bytes() == b"b"
            (run / "b.json").write_bytes(b"tampered parent dependency")
        else:
            assert index["artifacts"][1]["artifact_id"] == "b"
            index["artifacts"].pop(1)
            (run / "artifacts_index.json").write_text(json.dumps(index))
        assert project(source, requested_section_ids=("coefficients",)).status.value == "unavailable"
        result = project(source, coefficient_selection=selection)
        assert result.status.value == "unavailable"
        assert result.audit.restriction_reason == "EVIDENCE_DEPENDENCY_MISMATCH"
        assert not result.facts and not result.sections and result.semantic_selection is None


def test_spec3_logical_model_is_not_an_artifact_identity(tmp_path):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with committed(tmp_path, regression=True, model_ids=("linear_mixed_effects_1", "logical.other")) as (source, run, *_):
        selection = ModelCoefficientSelectionV1("linear_mixed_effects_1")
        result = project(source, coefficient_selection=selection)
        assert result.status.value == "available", result.audit
        assert result.fact_ids == ("fact-mean",)
        assert result.semantic_selection["model_id"] == "linear_mixed_effects_1"
        assert {r["artifact_id"] for r in result.result_dependencies["records"]} == {"a", "b"}
        (run / "a.json").write_bytes(b"selected source tamper")
        assert project(source, coefficient_selection=selection).status.value == "unavailable"


@pytest.mark.parametrize("term", [" x ", "\tC(x)[T.a:b]\n", " C(cafe\u0301)[T.a:b] ", "", " "])
def test_spec3_exact_display_terms_default_and_explicit_agree(tmp_path, term):
    import unicodedata
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with committed(tmp_path, regression=True, term=term) as (source, *_):
        default = project(source, coefficient_selection=ModelCoefficientSelectionV1("a"))
        assert default.status.value == "available"
        explicit = project(source, coefficient_selection=ModelCoefficientSelectionV1("a", terms=(term,)))
        assert explicit.status.value == "available"
        assert explicit.to_dict() == default.to_dict()
        assert explicit.semantic_selection["terms"] == (unicodedata.normalize("NFC", term),)
        if term != term.strip():
            wrong = project(source, coefficient_selection=ModelCoefficientSelectionV1("a", terms=(term.strip(),)))
            assert wrong.status.value == "unavailable"
            assert wrong.audit.restriction_reason == "semantic_term_unavailable"


@pytest.mark.parametrize("terms", [("x\x00",), ("\ud800",), ("汉" * 1366,), ("x" * 4097,),
                                   ("é", "e\u0301"), ("x", "x"), (), "x", (1,)])
def test_spec3_exact_terms_reject_invalid_or_ambiguous_display_input(terms):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with pytest.raises(EvidenceProjectionError, match="semantic_selector_invalid"):
        ModelCoefficientSelectionV1("a", terms=terms)


def test_semantic_two_models_are_distinct_and_binding_wire_is_defensive(tmp_path):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with committed(tmp_path, regression=True) as (source, *_):
        for model, fact_id in (("a", "fact-mean"), ("b", "fact-coefficient")):
            result = project(source, coefficient_selection=ModelCoefficientSelectionV1(model))
            assert result.status.value == "available" and result.fact_ids == (fact_id,)
            assert result.egress_payload()["semantic_selection"] == result.to_dict()["semantic_selection"]
            wire = result.to_dict()
            wire["semantic_selection"]["bindings"][0]["model_id"] = "foreign"
            assert result.semantic_selection["bindings"][0]["model_id"] == model


@pytest.mark.parametrize("attack,reason", [
    ("ambiguous", "semantic_selection_ambiguous"), ("foreign", "semantic_model_unavailable"),
    ("missing", "semantic_term_unavailable"), ("role", "semantic_role_unavailable"),
    ("mixed", "semantic_selection_mixed"), ("tamper", "EVIDENCE_DEPENDENCY_MISMATCH"),
])
def test_semantic_failures_atomic(tmp_path, attack, reason):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with committed(tmp_path, regression="ambiguous" if attack == "ambiguous" else True) as (source, run, *_):
        if attack == "tamper": (run / "a.json").write_bytes(b"tampered")
        selection = ModelCoefficientSelectionV1("foreign" if attack == "foreign" else "a",
            terms=("absent",) if attack == "missing" else None,
            roles=("std_error",) if attack == "role" else ("estimate",))
        kwargs = {"requested_fact_ids": []} if attack == "mixed" else {}
        result = project(source, coefficient_selection=selection, **kwargs)
        assert result.status.value == "unavailable"
        assert not result.facts and not result.sections
        assert result.to_dict().get("semantic_selection") is None
        assert result.audit.restriction_reason == reason


def test_semantic_unknown_role_is_not_guessed():
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with pytest.raises(EvidenceProjectionError, match="semantic_role_unknown"):
        ModelCoefficientSelectionV1("a", roles=("coefficient_magic",))


def test_semantic_roles_resolve_only_exact_declared_tree_references(tmp_path):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with committed(tmp_path, regression="roles") as (source, *_):
        result = project(source, coefficient_selection=ModelCoefficientSelectionV1("a", roles=("std_error", "upper")))
        assert result.status.value == "available", result.audit
        assert result.fact_ids == ("fact-coefficient",)
        assert [(b["role"], b["fact_id"]) for b in result.semantic_selection["bindings"]] == [
            ("std_error", "fact-coefficient"), ("upper", "fact-coefficient")]
        assert {r["artifact_id"] for r in result.result_dependencies["records"]} == {"a", "b"}


@pytest.mark.parametrize("consumer", ["agent", "notebook", "report", "results"])
def test_semantic_public_delivery_whole_wire_bound_and_no_profile_bypass(tmp_path, consumer):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    from workbench.canonical import canonical_json_v1, sha256_canonical
    from workbench.services import results_service as service
    with committed(tmp_path, regression=True) as (source, run, _, _, kwargs, args):
        selection = ModelCoefficientSelectionV1("a")
        core = default_projection_registry().project(source, consumer_id=consumer, destination="local",
            coefficient_selection=selection)
        assert core.audit.policy_ref == default_projection_registry().resolve(consumer).policy_ref
        service.configure_report_evidence_persistence(owner_for(kwargs, args))
        try:
            wire = service.read_persisted_consumer_evidence_for_run(consumer_id=consumer,
                project_root=run.parent.parent, run_id="r1", coefficient_selection=selection)
        finally:
            service.configure_report_evidence_persistence(None)
        assert wire["status"] == "available", wire
        assert wire["semantic_selection"]["bindings"][0]["fact_id"] == "fact-mean"
        assert wire["audit"]["token_budget"] == (len(canonical_json_v1(wire).encode()) + 3) // 4 <= 4096
        assert wire["receipt"]["wire_digest"] == sha256_canonical({k:v for k,v in wire.items() if k != "receipt"})
        changed = copy.deepcopy(wire)
        changed["semantic_selection"]["bindings"][0]["term"] = "foreign"
        assert service._central_consumer_projection_digest(changed) != service._central_consumer_projection_digest(wire)
        spec = replace(default_projection_registry().resolve(consumer), max_row_budget=1)
        denied = ConsumerProjectionRegistryV1([spec]).project(source, consumer_id=consumer, destination="local",
            coefficient_selection=selection)
        assert denied.status.value == "unavailable" and not denied.facts and denied.semantic_selection is None


def test_declared_section_type_selection(tmp_path):
    with committed(tmp_path) as (source, *_):
        result = project(source, requested_section_types=("statistical_tests",))
        assert result.status.value == "available" and len(result.sections) == 2
        assert project(source, requested_section_types=("diagnostics",)).audit.restriction_reason == "section_type_unavailable"
        assert project(source, requested_section_types=("invented",)).audit.restriction_reason == "section_type_unknown"


@pytest.mark.parametrize("shape", ["two_terms", "many_terms", "long_term"])
def test_semantic_terms_none_never_truncates_and_metadata_is_charged(tmp_path, shape):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with committed(tmp_path, regression=shape) as (source, *_):
        result = project(source, coefficient_selection=ModelCoefficientSelectionV1("a"))
        if shape == "two_terms":
            assert result.status.value == "available"
            assert len(result.semantic_selection["bindings"]) == 2
            assert result.fact_ids == ("fact-mean",)
        else:
            assert result.status.value == "unavailable"
            assert result.audit.restriction_reason == "structured_projection_budget_exceeded"
            assert not result.facts and result.semantic_selection is None


@pytest.mark.parametrize("attack", ["remote", "sensitivity", "index", "packet"])
def test_semantic_privacy_and_live_source_mutation(tmp_path, attack):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    with committed(tmp_path, regression=True, sensitivity="restricted" if attack == "sensitivity" else "public") as (source, run, index, _, kwargs, args):
        if attack == "index":
            index["artifacts"][0]["path"] = "b.json"
            (run / "artifacts_index.json").write_text(json.dumps(index))
        if attack == "packet":
            # Mutation of the actual committed packet must invalidate its proof.
            artifact = args[1].get(kwargs["artifact_id"], scope_ref=kwargs["scope_ref"])
            packet_path = tmp_path / "packets" / "packets" / f"{artifact.content_hash}.json"
            assert packet_path.is_file() and packet_path.read_bytes() != b"{}"
            packet_path.write_text("{}")
        try:
            result = default_projection_registry().project(source, consumer_id="agent",
                destination="remote" if attack == "remote" else "local", coefficient_selection=ModelCoefficientSelectionV1("a"))
        except (ValueError, EvidenceProjectionError):
            assert attack == "packet"
        else:
            assert result.status.value in {"blocked", "unavailable"}
            assert not result.facts and not result.sections and result.semantic_selection is None


def test_semantic_final_receipt_overhead_cannot_bypass_budget(tmp_path):
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    from workbench.services import results_service as service
    witnessed = False
    for size in range(1200, 3001, 100):
        with committed(tmp_path / str(size), regression="delivery_edge", label="T" * size) as (source, run, _, _, kwargs, args):
            selection = ModelCoefficientSelectionV1("a")
            core = default_projection_registry().project(source, consumer_id="agent", destination="local", coefficient_selection=selection)
            if core.status.value != "available":
                continue
            service.configure_report_evidence_persistence(owner_for(kwargs, args))
            try:
                wire = service.read_persisted_consumer_evidence_for_run(consumer_id="agent", project_root=run.parent.parent,
                    run_id="r1", coefficient_selection=selection)
            finally:
                service.configure_report_evidence_persistence(None)
            if wire["status"] == "unavailable":
                assert wire["reason_code"] == "consumer_delivery_budget_exceeded"
                assert not wire["facts"] and not wire.get("semantic_selection") and not wire.get("receipt")
                assert core.audit.token_budget <= 4096
                print(f"SEMANTIC_FINAL_BOUNDARY term_chars={size} core_tokens={core.audit.token_budget}")
                witnessed = True
                break
            assert wire["audit"]["token_budget"] <= 4096
    assert witnessed, "fixture must exercise receipt overhead beyond the core budget"


def test_default_sections_and_exact_fact_closure(tmp_path):
    with committed(tmp_path) as (source, _, _, sections, *_):
        result = project(source)
        assert hasattr(result, "sections"), "central projection drops sealed sections"
        assert [section.to_dict() for section in result.sections] == sections
        assert result.to_dict()["audit"]["selected_section_ids"] == ["a", "b"]
        assert len(result.to_dict()["result_dependencies"]["records"]) == 2


@pytest.mark.parametrize("attack", ["bytes", "bytes_index", "missing_record", "missing_file", "symlink"])
def test_dependency_attacks_fail_closed_before_any_delivery(tmp_path, attack):
    with committed(tmp_path) as (source, run, index, *_):
        if attack in ("bytes", "bytes_index"):
            (run / "a.json").write_bytes(b"mutated")
            if attack == "bytes_index": index["artifacts"][0]["sha256"] = hashlib.sha256(b"mutated").hexdigest()
        elif attack == "missing_record": index["artifacts"].pop(0)
        else:
            (run / "a.json").unlink()
            if attack == "symlink": (run / "a.json").symlink_to(run / "b.json")
        (run / "artifacts_index.json").write_text(json.dumps(index))
        result = project(source)
        assert result.status.value == "unavailable", "tampered dependencies still release numeric evidence"
        assert not result.facts and not result.sections


def test_selected_good_section_survives_unrelated_tamper_and_facts_only_checks_closure(tmp_path):
    with committed(tmp_path) as (source, run, *_):
        (run / "b.json").write_bytes(b"tampered")
        result = project(source, requested_section_ids=["a"], requested_fact_ids=[])
        assert result.status.value == "available"
        assert result.fact_ids == ("fact-mean",)
        assert [s.section_id for s in result.sections] == ["a"]
        assert result.audit.omitted_section_ids == ("b",)
        assert project(source).status.value == "unavailable"
        assert project(source, requested_section_ids=[], requested_fact_ids=["fact-coefficient"]).status.value == "unavailable"


@pytest.mark.parametrize("kind", ["fact", "label", "section", "reference"])
def test_budget_atomic_not_partial_tree(tmp_path, kind):
    with committed(tmp_path, label="汉" * (1300 if kind == "label" else 1)) as (source, *_):
        spec = default_projection_registry().resolve("results")
        spec = replace(spec, max_token_budget=900 if kind == "label" else 1,
                       max_row_budget=1 if kind in ("section", "reference") else 64)
        result = ConsumerProjectionRegistryV1([spec]).project(source, consumer_id="results", destination="local")
        assert result.status.value == "unavailable"
        assert not result.facts and not result.sections
        assert result.audit.restriction_reason == "structured_projection_budget_exceeded"


@pytest.mark.parametrize("remote,sensitivity", [(True, "public"), (False, "restricted")])
def test_denied_delivery_has_no_section_label_or_seal_leak(tmp_path, remote, sensitivity):
    with committed(tmp_path, sensitivity=sensitivity) as (source, *_):
        result = default_projection_registry().project(source, consumer_id="agent",
            destination="remote" if remote else "local")
        assert not result.facts
        assert hasattr(result, "sections"), "section redaction audit is absent"
        assert not result.sections and result.to_dict()["result_dependencies"] is None
        assert "sealed label" not in json.dumps(result.to_dict())
        assert result.audit.redacted_section_ids == ("a", "b")


def test_missing_manifest_and_unknown_section_explicitly_unavailable(tmp_path):
    with committed(tmp_path, manifest=False) as (source, *_):
        assert project(source).status.value == "unavailable"
    with committed(tmp_path / "second") as (source, *_):
        result = project(source, requested_section_ids=["unknown"])
        assert result.status.value == "unavailable" and not result.facts and not result.sections


def test_legacy_numeric_only_unchanged_unless_sections_explicit(tmp_path):
    with committed(tmp_path, extension=False, manifest=False) as (source, *_):
        assert project(source).fact_ids == ("fact-mean", "fact-coefficient")
        result = project(source, requested_section_ids=["a"])
        assert result.status.value == "unavailable" and not result.facts


@pytest.mark.parametrize("field", ["project_ref", "run_id", "project_file_store"])
def test_wrong_bound_host_context_rejected(tmp_path, field):
    with committed(tmp_path, extension=False, manifest=False) as (source, _, _, _, kwargs, args):
        assert "project_file_store" in kwargs, "source proof lacks owner host context"
        bad = dict(kwargs)
        bad[field] = object() if field == "project_file_store" else "foreign"
        with pytest.raises(EvidenceProjectionError):
            ServerOwnedEvidenceProjectionSourceV1(*args, **bad)


def test_post_issuance_hoststore_swap_rejected_by_proof(tmp_path):
    with committed(tmp_path, extension=False, manifest=False) as (source, *_):
        assert hasattr(source, "_project_file_store"), "host store identity absent from source proof"
        object.__setattr__(source, "_project_file_store", object())
        with pytest.raises(EvidenceProjectionError):
            project(source)


def owner_for(kwargs, args):
    from workbench.services.results_service import ServerOwnedReportEvidencePersistenceV1
    return ServerOwnedReportEvidencePersistenceV1._from_host(*args,
        actor_ref="actor:structured", project_ref=kwargs["project_ref"], session_ref="session:structured",
        scope_ref=kwargs["scope_ref"], run_id=kwargs["run_id"], model_run_id=kwargs["run_id"],
        artifact_id=kwargs["artifact_id"], commit_id=kwargs["commit_id"], confirmation_ref="confirmation:r1",
        artifact_file_sha256="a" * 64, canonical_project_root=kwargs["canonical_project_root"],
        project_file_store=kwargs["project_file_store"], authority_handle=kwargs["authority_handle"])


@pytest.mark.parametrize("path", ["initial", "canonical", "read_bound"])
def test_all_owner_source_paths_bind_same_host_context(tmp_path, path):
    with committed(tmp_path) as (_, _, _, _, kwargs, args):
        owner = owner_for(kwargs, args)
        if path == "initial": source = owner._canonical_record
        elif path == "canonical": source = owner._canonical_report_source_and_artifact()[0]
        else:
            artifact = args[1].get(kwargs["artifact_id"], scope_ref=kwargs["scope_ref"])
            source = owner.read_bound(owner.commit_id, actor_ref=owner.actor_ref, project_ref=owner.project_ref,
                session_ref=owner.session_ref, scope_ref=owner.scope_ref, artifact_id=owner.artifact_id,
                run_id=owner.run_id, model_run_id=owner.model_run_id, content_hash=artifact.content_hash,
                admission_ref=owner.artifact_id, confirmation_ref=owner.confirmation_ref,
                artifact_file_sha256=owner.artifact_file_sha256)
        assert source._project_file_store is kwargs["project_file_store"]
        assert project(source).status.value == "available"


def test_owner_host_store_swap_cannot_mint_fresh_source(tmp_path):
    with committed(tmp_path) as (_, _, _, _, kwargs, args):
        owner = owner_for(kwargs, args)
        owner._project_file_store = object()
        with pytest.raises(EvidenceProjectionError):
            owner._canonical_report_source_and_artifact()


@pytest.mark.parametrize("field", ["sections", "result_dependencies", "audit"])
def test_shared_digest_covers_sections_seal_and_selection(tmp_path, field):
    from workbench.services.results_service import _central_consumer_projection_digest
    with committed(tmp_path) as (source, *_):
        wire = project(source).to_dict()
        digest = _central_consumer_projection_digest(wire)
        changed = copy.deepcopy(wire)
        if field == "sections":
            changed[field][0]["content"]["fields"]["results"]["items"][0]["fields"]["label"]["value"] = "tampered"
        elif field == "result_dependencies": changed[field]["records"][0]["sha256"] = "0" * 64
        else: changed[field]["selected_section_ids"] = []
        assert _central_consumer_projection_digest(changed) != digest


def test_valid_unrelated_egress_receipt_cannot_authorize_sections(tmp_path):
    from datetime import datetime
    from tests.test_v189_consumer_projection import _ref
    from workbench.contracts.agent.context_egress import (
        ContextEgressGatewayV1, ContextEgressPolicyV1, ContextEgressReceiptIssuerV1,
        ContextMaterializationStoreV1, SensitivityClassV1,
    )
    policy_ref = _ref("egress-policy", "policy:structured")
    policy = ContextEgressPolicyV1(policy_ref=policy_ref, destination="remote", provider_ref="provider:1",
        allowed_sensitivity=(SensitivityClassV1.PUBLIC,), max_token_budget=4096,
        max_row_budget=64, max_time_budget_ms=5000)
    materializer = ContextMaterializationStoreV1(materializer_ref=_ref("materializer", "materializer:1"),
        redaction_policy_ref=_ref("redaction-policy", "redaction:1"))
    result = materializer.materialize({"evidence:unrelated": {"mean": 1}}, selected_refs=("evidence:unrelated",))
    gateway = ContextEgressGatewayV1.from_materialization_result(result, request_id="request:1",
        destination="remote", provider_ref="provider:1", sensitivity_policy_ref=policy_ref,
        sensitivity=SensitivityClassV1.PUBLIC, token_budget=4096, row_budget=64, time_budget_ms=1000,
        purpose_ref="purpose:1", requested_at="2026-08-15T17:00:00+00:00", expires_at="2026-08-15T18:00:00+00:00")
    issuer = ContextEgressReceiptIssuerV1(policy, materializer_store=materializer,
        clock=lambda: datetime.fromisoformat("2026-08-15T17:30:00+00:00"))
    receipt = issuer.issue(gateway)
    with committed(tmp_path) as (source, *_):
        projection = default_projection_registry().project(source, consumer_id="agent", destination="remote",
            gateway=gateway, receipt=receipt, issuer=issuer)
        assert projection.status.value == "unavailable"
        assert not projection.facts and not projection.sections
        assert projection.audit.restriction_reason == "structured_egress_payload_mismatch"


def test_public_service_selection_and_complete_wire_receipt(tmp_path):
    from workbench.canonical import sha256_canonical
    from workbench.services import results_service as service
    with committed(tmp_path) as (_, run, _, _, kwargs, args):
        owner = owner_for(kwargs, args)
        service.configure_report_evidence_persistence(owner)
        try:
            wire = service.read_persisted_consumer_evidence_for_run(consumer_id="agent",
                project_root=run.parent.parent, run_id="r1", requested_section_ids=["a"], requested_fact_ids=[])
        finally:
            service.configure_report_evidence_persistence(None)
        assert wire["status"] == "available", wire
        assert [s["section_id"] for s in wire["sections"]] == ["a"]
        assert [f["fact_id"] for f in wire["facts"]] == ["fact-mean"]
        assert wire["receipt"]["wire_digest"] == sha256_canonical({k: v for k, v in wire.items() if k != "receipt"})


@pytest.mark.parametrize("attack", ["scope", "authority", "root", "admission_swap"])
def test_exact_store_wrong_authority_scope_root_or_rebound_admission(tmp_path, attack):
    with committed(tmp_path) as (source, _, _, _, kwargs, args):
        authority = kwargs["authority_handle"]
        scope = kwargs["scope_ref"]
        root = kwargs["canonical_project_root"]
        if attack in ("scope", "authority"):
            _, other_host = _authorized_registry("scope:foreign" if attack == "scope" else scope)
            authority = other_host.channel
            if attack == "scope": scope = "scope:foreign"
        if attack == "root":
            root = tmp_path / "foreign"
            root.mkdir()
        other = HostBoundProjectFileStoreV1.from_host(root, authority_handle=authority, scope_ref=scope)
        try:
            if attack == "admission_swap":
                original = kwargs["project_file_store"]._admission
                kwargs["project_file_store"]._admission = other._admission
                try:
                    with pytest.raises(EvidenceProjectionError): project(source)
                finally:
                    kwargs["project_file_store"]._admission = original
            else:
                with pytest.raises(EvidenceProjectionError):
                    ServerOwnedEvidenceProjectionSourceV1(*args, **{**kwargs, "project_file_store": other})
        finally:
            other._admission.close()


def test_row_and_utf8_metadata_budgets_are_measured_not_only_fact_cost(tmp_path):
    from workbench.canonical import canonical_json_v1
    with committed(tmp_path) as (source, *_):
        spec = replace(default_projection_registry().resolve("results"), max_token_budget=4095)
        result = ConsumerProjectionRegistryV1([spec]).project(source, consumer_id="results", destination="local")
        assert result.audit.row_budget == 10  # 2 facts + 2 sections + 2 deps + 2 list entries + 2 refs.
        assert result.audit.token_budget == (len(canonical_json_v1(result.to_dict()).encode("utf-8")) + 3) // 4
        for max_tokens, max_rows in ((result.audit.token_budget - 1, 64), (4096, 9)):
            narrowed = ConsumerProjectionRegistryV1([replace(spec, max_token_budget=max_tokens, max_row_budget=max_rows)])
            blocked = narrowed.project(source, consumer_id="results", destination="local")
            assert blocked.status.value == "unavailable" and not blocked.sections and not blocked.facts


def test_denied_fact_kind_cannot_leak_section_tree(tmp_path):
    with committed(tmp_path) as (source, *_):
        spec = replace(default_projection_registry().resolve("results"), fact_kinds=("not_numeric",))
        result = ConsumerProjectionRegistryV1([spec]).project(source, consumer_id="results", destination="local")
        assert result.audit.restriction_reason == "fact_kind_not_allowed"
        assert not result.facts and not result.sections and result.result_dependencies is None


def test_real_ols_producer_uses_explicit_local_profile_only(producer):
    import numpy as np
    import statsmodels.api as sm
    from workbench.artifacts import write_json
    from tests.test_v189_report_result_sections import prepare
    factory, run, packet = producer
    x = np.linspace(-2.0, 2.0, 30)
    fit = sm.OLS(1.0 + 0.4 * x + np.sin(x * 3) * 0.2, sm.add_constant(x)).fit()
    packet["coefficients"] = {
        name: dict(estimate=float(fit.params[i]), std_error=float(fit.bse[i]),
                   p_value=float(fit.pvalues[i]), confidence_interval=fit.conf_int()[i].tolist(),
                   confidence_interval_method="student_t", confidence_level=0.95)
        for i, name in enumerate(("const", "x"))
    }
    write_json(run / "model_results" / "ols_1.json", packet)
    index = json.loads((run / "artifacts_index.json").read_text())
    index["artifacts"][0]["sha256"] = hashlib.sha256((run / "model_results" / "ols_1.json").read_bytes()).hexdigest()
    write_json(run / "artifacts_index.json", index)
    envelope = prepare(producer)
    receipt = factory.issue_production_receipt(run_id="r1", model_run_id="ols_1", upload_hash="a" * 64)
    owner = factory.create_for_run(run_id="r1", model_run_id="ols_1", production_receipt=receipt,
        envelope=envelope, artifact_file_sha256=factory.report_evidence_file_sha256(envelope))
    source, _ = owner._canonical_report_source_and_artifact()
    # A test-only explicit measurement spec reports demand before choosing the
    # production profile. It is never a hidden runtime unlimited mode.
    spec = default_projection_registry().resolve("results")
    from workbench.evidence.consumer_adapters import _local_read_spec
    measured = ConsumerProjectionRegistryV1([replace(_local_read_spec(spec, "local"),
        max_token_budget=1000000, max_row_budget=100000)]).project(
        source, consumer_id="results", destination="local")
    print(f"REAL_OLS sections={len(measured.sections)} facts={len(measured.facts)} "
          f"tokens={measured.audit.token_budget} rows={measured.audit.row_budget}")
    assert measured.status.value == "available"
    assert len(measured.sections) == 11
    assert measured.audit.token_budget > 4096 or measured.audit.row_budget > 64
    for consumer in ("report", "results"):
        local = default_projection_registry().project(source, consumer_id=consumer, destination="local")
        assert local.status.value == "available", local.audit.to_dict()
        assert local.facts == measured.facts and local.sections == measured.sections
        assert local.audit.policy_ref != default_projection_registry().resolve(consumer).policy_ref
    agent = default_projection_registry().project(source, consumer_id="agent", destination="local")
    assert agent.status.value == "unavailable" and not agent.sections
    assert agent.audit.restriction_reason == "structured_projection_budget_exceeded"
    remote = default_projection_registry().project(source, consumer_id="results", destination="remote")
    assert not remote.sections and not remote.facts
    assert remote.audit.policy_ref == spec.policy_ref


@pytest.mark.parametrize("mode", ["section_count", "repeated_references"])
def test_section_and_reference_counts_cannot_hide_behind_deduplicated_facts(tmp_path, mode):
    options = {"section_copies": 36} if mode == "section_count" else {"reference_copies": 40}
    with committed(tmp_path, **options) as (source, *_):
        spec = replace(default_projection_registry().resolve("results"), max_token_budget=65000)
        result = ConsumerProjectionRegistryV1([spec]).project(source, consumer_id="results", destination="local")
        assert result.status.value == "unavailable"
        assert not result.sections and not result.facts
        assert result.audit.restriction_reason == "structured_projection_budget_exceeded"


@pytest.mark.parametrize("field", ["fact", "label", "reference", "manifest"])
def test_committed_packet_mutations_are_live_and_restoration_recovers(tmp_path, field):
    from workbench.canonical import canonical_json_v1
    with committed(tmp_path) as (source, _, _, _, kwargs, args):
        assert project(source).status.value == "available"
        artifact = args[1].get(kwargs["artifact_id"], scope_ref=kwargs["scope_ref"])
        path = tmp_path / "packets" / "packets" / f"{artifact.content_hash}.json"
        original = path.read_bytes()
        packet = json.loads(original)
        envelope = packet["payload"]["artifact"]["envelope"]
        section = envelope["family_evidence"]["structured_results"]["sections"][0]
        if field == "fact": envelope["numeric_facts"][0]["value"] += 0.01
        elif field == "label":
            section["content"]["fields"]["results"]["items"][0]["fields"]["label"]["value"] = "changed"
        elif field == "reference":
            section["content"]["fields"]["results"]["items"][0]["fields"]["statistic"]["fact_id"] = "fact-coefficient"
        else: envelope["family_evidence"]["result_dependencies"]["records"][0]["sha256"] = "0" * 64
        mutated = canonical_json_v1(packet).encode()
        assert mutated != original, "mutation must change the located packet"
        path.write_bytes(mutated)
        with pytest.raises(EvidenceProjectionError): project(source)
        path.write_bytes(original)
        assert project(source).status.value == "available"


def test_current_materializer_requires_explicit_structured_schema_admission(tmp_path):
    from tests.test_v189_consumer_projection import _ref
    from workbench.contracts.agent.context_egress import ContextMaterializationStoreV1, EgressContractError
    with committed(tmp_path) as (source, *_):
        projection = default_projection_registry().project(source, consumer_id="agent", destination="local")
        store = ContextMaterializationStoreV1(materializer_ref=_ref("materializer", "materializer:1"),
            redaction_policy_ref=_ref("redaction-policy", "redaction:1"))
        with pytest.raises(EgressContractError) as rejected:
            store.materialize({"evidence:projection": projection.egress_payload()},
                              selected_refs=("evidence:projection",))
        assert rejected.value.code == "EGRESS_CONTEXT_KEY_INVALID"


def test_unavailable_source_does_not_claim_omitted_sections_were_selected(tmp_path):
    with committed(tmp_path, blocked=True) as (source, *_):
        result = project(source)
        assert result.status.value == "unavailable"
        assert not result.facts and not result.sections
        assert result.audit.selected_section_ids == ()
        assert result.audit.omitted_section_ids == ("a", "b")


@pytest.mark.parametrize("tamper_unselected", [False, True])
def test_spec2_fact_only_never_expands_implicit_sections(tmp_path, tamper_unselected):
    with committed(tmp_path) as (source, run, *_):
        if tamper_unselected:
            (run / "b.json").write_bytes(b"unselected mutation")
        result = project(source, requested_fact_ids=["fact-mean"])
        assert result.status.value == "available", result.audit.to_dict()
        assert result.fact_ids == ("fact-mean",)
        assert result.sections == ()
        assert result.audit.requested_section_ids == ()
        assert result.audit.selected_section_ids == ()
        assert [row["artifact_id"] for row in result.result_dependencies["records"]] == ["a"]


@pytest.mark.parametrize("label_size", [100, 2600])
@pytest.mark.parametrize("consumer", ["agent", "notebook", "results", "report"])
def test_spec2_final_service_wire_including_receipt_is_budgeted(tmp_path, label_size, consumer):
    from workbench.canonical import canonical_json_v1, sha256_canonical
    from workbench.services import results_service as service
    with committed(tmp_path, label="L" * label_size, reference_copies=2) as (source, run, _, _, kwargs, args):
        core = default_projection_registry().project(source, consumer_id=consumer, destination="local")
        assert core.status.value == "available", core.audit.to_dict()
        limit = 65536 if consumer in {"results", "report"} else 4096
        assert core.audit.token_budget <= limit
        owner = owner_for(kwargs, args)
        service.configure_report_evidence_persistence(owner)
        try:
            wire = service.read_persisted_consumer_evidence_for_run(consumer_id=consumer,
                project_root=run.parent.parent, run_id="r1")
        finally:
            service.configure_report_evidence_persistence(None)
        tokens = (len(canonical_json_v1(wire).encode("utf-8")) + 3) // 4
        print(f"SPEC2 core_tokens={core.audit.token_budget} final_tokens={tokens} status={wire['status']}")
        assert tokens <= limit
        if label_size == 2600 and consumer in {"agent", "notebook"}:
            assert wire["status"] == "unavailable"
            assert not wire["facts"] and not wire.get("sections") and wire["receipt"] is None
            assert wire["reason_code"] == "consumer_delivery_budget_exceeded"
            assert "L" * label_size not in canonical_json_v1(wire)
        else:
            assert wire["status"] == "available"
            assert wire["audit"]["token_budget"] == tokens
            assert wire["receipt"]["wire_digest"] == sha256_canonical({k: v for k, v in wire.items() if k != "receipt"})
            if consumer in {"results", "report"}:
                assert wire["projection_digest"] == sha256_canonical(
                    {k: v for k, v in wire.items() if k not in {"receipt", "projection_digest"}})


@pytest.mark.parametrize("selection", [{"requested_fact_ids": []}, {"requested_section_ids": []}])
def test_spec2_explicit_empty_selection_is_not_default_all(tmp_path, selection):
    with committed(tmp_path) as (source, *_):
        result = project(source, **selection)
        assert result.status.value == "available"
        assert result.facts == () and result.sections == ()
        assert result.result_dependencies["records"] == ()
