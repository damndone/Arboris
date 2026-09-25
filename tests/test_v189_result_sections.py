from copy import deepcopy

import pytest

from workbench.contracts.evidence.envelope import NumericFactV1
from tests.test_v189_evidence_envelope import _load
from tests.test_v189_report_result_sections import producer as namespace_producer


def _float_union_wire_case(field, value):
    from workbench.contracts.evidence.envelope import DistributionRefV1, OracleCheckV1
    fact = deepcopy(_load()["numeric_facts"][0])
    if field == "degrees_of_freedom":
        wire, parser = fact["reference_distribution"], DistributionRefV1.from_dict
    elif field == "observed_difference":
        wire, parser = fact["oracle_checks"][0], OracleCheckV1.from_dict
    else:
        wire, parser = fact, NumericFactV1.from_dict
    wire[field] = value
    return wire, parser


@pytest.mark.parametrize("field,value", [
    ("degrees_of_freedom", 12.0), ("degrees_of_freedom", 12.5),
    ("degrees_of_freedom", {"status": "not_applicable", "reason": "empirical"}),
    ("standard_error", 1.0), ("standard_error", 0.0),
    ("standard_error", {"status": "not_applicable", "reason": "not estimated"}),
    ("observed_difference", 0.0),
    ("observed_difference", {"status": "not_applicable", "reason": "not compared"}),
    ("confidence_level", 0.95),
])
def test_float_union_wire_canonical_roundtrip(field, value):
    import json
    from workbench.canonical import canonical_json_v1
    wire, parser = _float_union_wire_case(field, value)
    original = parser(wire)
    canonical = canonical_json_v1(original.to_dict())
    decoded = parser(json.loads(canonical))
    assert decoded.to_dict() == original.to_dict()
    assert canonical_json_v1(decoded.to_dict()) == canonical
    if type(value) is float:
        assert type(getattr(decoded, field)) is float
        assert getattr(decoded, field) == value


@pytest.mark.parametrize("field", ["degrees_of_freedom", "standard_error", "observed_difference", "confidence_level"])
@pytest.mark.parametrize("value", [True, False, "12", float("inf"), float("nan"), 2**53, -(2**53)])
def test_float_union_wire_rejects_invalid_numbers(field, value):
    from workbench.contracts.common.envelope import ContractError
    wire, parser = _float_union_wire_case(field, value)
    with pytest.raises(ContractError):
        parser(wire)


@pytest.mark.parametrize("field,value", [
    ("degrees_of_freedom", 0), ("degrees_of_freedom", -1),
    ("standard_error", -1), ("confidence_level", 0), ("confidence_level", 1),
])
def test_float_union_wire_retains_field_constraints(field, value):
    from workbench.contracts.common.envelope import ContractError
    wire, parser = _float_union_wire_case(field, value)
    with pytest.raises(ContractError):
        parser(wire)


@pytest.mark.parametrize("field,value", [
    ("degrees_of_freedom", 12.0), ("standard_error", 1.0), ("observed_difference", 0.0),
])
def test_float_union_wire_does_not_widen_constructor_types(field, value):
    from dataclasses import replace
    from workbench.contracts.common.envelope import ContractError
    wire, parser = _float_union_wire_case(field, value)
    original = parser(wire)
    with pytest.raises(ContractError):
        replace(original, **{field: int(value)})


def _api():
    from workbench.contracts.evidence import result_sections
    return result_sections


def _facts():
    wire = deepcopy(_load()["numeric_facts"][0])
    wire.update(fact_id="p:x", value=1.25e-24)
    return {"p:x": NumericFactV1.from_dict(wire)}


def _section():
    return {
        "section_id": "test:x", "section_type": "statistical_tests",
        "schema_version": 1, "status": "available", "reason_codes": [],
        "fact_refs": ["p:x"], "dependency_refs": ["model:x"],
        "content": {"kind": "object", "fields": {
            "results": {"kind": "list", "items": [{"kind": "object", "fields": {
                "p_value": {"kind": "fact", "fact_id": "p:x", "representation": "number"},
                "label": {"kind": "text", "value": "<script>untrusted label</script>"},
            }}]},
        }},
    }


def _parse(wire):
    return _api().ResultSectionV1.from_dict(wire, facts=_facts(), dependency_ids={"model:x"})


def _arma_report_section(report_fields):
    return {**_section(), "section_type": "model_family_evidence", "fact_refs": [],
        "content": {"kind": "object", "fields": {
            "model_family": {"kind": "text", "value": "time_series.arma_garch"},
            "results": {"kind": "object", "fields": {
                "arma": {"kind": "object", "fields": {
                    "report": {"kind": "object", "fields": report_fields}}}}}}}}


@pytest.mark.parametrize("field", ["mae", "validation_n", "interval_coverage"])
def test_arma_report_numeric_text_is_not_a_fact(field):
    wire = _arma_report_section({"metrics": {"kind": "object", "fields": {
        field: {"kind": "text", "value": "0.5"}}}})
    with pytest.raises(Exception, match="fact"):
        _parse(wire)


def test_arma_chart_reference_requires_section_dependency():
    wire = _arma_report_section({"chart_artifacts": {"kind": "list", "items": [
        {"kind": "text", "value": "ts.chart.acf"}]}})
    with pytest.raises(Exception, match="dependency"):
        _parse(wire)


def test_arma_parameter_estimate_requires_fact():
    wire = _arma_report_section({"parameters": {"kind": "object", "fields": {
        "final_fit": {"kind": "object", "fields": {"omega": {"kind": "text", "value": "0.1"}}}}}})
    with pytest.raises(Exception, match="fact"):
        _parse(wire)


def test_arma_schema_declaration_cannot_mutate_runtime_contract():
    api = _api()
    declaration = api.result_sections_declaration()
    original = declaration["arma_report"]["metrics"]["mae"]
    try:
        declaration["arma_report"]["metrics"]["mae"] = ("text", None)
        assert api.result_sections_declaration()["arma_report"]["metrics"]["mae"] == original
    finally:
        declaration["arma_report"]["metrics"]["mae"] = original


def test_arma_missing_and_tiny_metric_stay_lossless():
    wire = _arma_report_section({"metrics": {"kind": "object", "fields": {
        "mae": {"kind": "fact", "fact_id": "p:x", "representation": "number"},
        "rmse": {"kind": "missing", "status": "unavailable", "reason": "not produced"}}}})
    wire["fact_refs"] = ["p:x"]
    resolved = _api().resolve_section_content(_parse(wire), facts=_facts())
    metrics = resolved["results"]["arma"]["report"]["metrics"]
    assert metrics["mae"] == 1.25e-24
    assert metrics["rmse"] == {"status": "unavailable", "reason": "not produced"}


def test_arma_presentation_marks_absent_values_unavailable():
    from workbench.report_view_model import _admitted_arma_presentation

    missing = {"kind": "missing", "status": "unavailable", "reason": "not produced"}
    wire = _arma_report_section({"metrics": {"kind": "object", "fields": {
        "mae": {"kind": "fact", "fact_id": "p:x", "representation": "number"}, "rmse": missing}},
        "parameters": missing, "next_forecast": missing,
        "chart_artifacts": {"kind": "list", "items": []}})
    wire["fact_refs"] = ["p:x"]
    admitted = _api().resolve_section_content(_parse(wire), facts=_facts())
    view = _admitted_arma_presentation(admitted)
    assert view["metrics"]["mae"] == 1.25e-24
    assert view["metrics"]["rmse"] == "unavailable"
    assert view["parameters"] == [{"component": "unavailable", "parameter": "unavailable", "estimate": "unavailable"}]
    assert view["next_forecast"] == [{"field": "Forecast", "value": "unavailable"}]


def test_tiny_p_value_round_trip_and_immutable_tree():
    wire = _section()
    section = _parse(wire)
    assert section.to_dict() == wire
    assert section.fact_refs == ("p:x",)
    wire["content"]["fields"].clear()
    assert section.to_dict() == _section()
    assert _api().resolve_section_content(section, facts=_facts())["results"][0]["p_value"] == 1.25e-24


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2), ("schema_version", True),
    ("section_type", "raw_json"), ("fact_refs", []),
    ("fact_refs", ["p:x", "p:x"]), ("dependency_refs", ["foreign"]),
    ("dependency_refs", []), ("reason_codes", ["UNAVAILABLE"]),
    ("status", "success"), ("section_id", ""),
])
def test_invalid_section_metadata_fails_closed(field, value):
    wire = _section(); wire[field] = value
    with pytest.raises(ValueError):
        _parse(wire)


@pytest.mark.parametrize("node", [
    {"kind": "number", "value": 0.05},
    {"kind": "fact", "fact_id": "unknown", "representation": "number"},
    {"kind": "fact", "fact_id": "p:x", "representation": "integer"},
    {"kind": "text", "value": "x" * 4097},
    {"kind": "text", "value": "汉" * 2000},
    {"kind": "text", "value": "ok", "hidden_value": 123},
    {"kind": "boolean", "value": 1},
    {"kind": "null", "value": None},
])
def test_tree_does_not_bypass_fact_or_shape_contract(node):
    wire = _section(); wire["content"]["fields"]["results"]["items"][0]["fields"]["p_value"] = node
    with pytest.raises(ValueError):
        _parse(wire)


def test_unavailable_section_cannot_carry_hidden_content():
    wire = _section(); wire.update(status="unavailable", reason_codes=["SOURCE_MISSING"])
    with pytest.raises(ValueError):
        _parse(wire)
    wire.update(fact_refs=[], dependency_refs=[], content={"kind": "null"})
    assert _parse(wire).to_dict() == wire


def test_depth_limit_precedes_recursive_freezing(monkeypatch):
    api = _api()
    wire = _section(); node = {"kind": "text", "value": "bounded"}
    for _ in range(api.MAX_DEPTH - 2):
        node = {"kind": "list", "items": [node]}
    wire["content"]["fields"]["warnings"] = {"kind": "list", "items": [node]}
    assert _parse(wire).to_dict() == wire
    wire["content"]["fields"]["warnings"]["items"] = [{"kind": "list", "items": [node]}]
    def forbidden(*args):
        pytest.fail("over-depth tree reached freezing")
    monkeypatch.setattr(api, "freeze_json", forbidden)
    with pytest.raises(api.ResultSectionError, match="tree depth/node budget exceeded"):
        _parse(wire)


def test_extension_has_exact_version_digest_and_unique_ids():
    api = _api()
    wire = {"schema_version": 1, "contract_digest": api.RESULT_SECTIONS_CONTRACT_DIGEST,
            "sections": [_section()]}
    parsed = api.StructuredResultsV1.from_dict(wire, facts=_facts(), dependency_ids={"model:x"})
    assert parsed.to_dict() == wire
    for bad in ({**wire, "contract_digest": "a" * 64},
                {**wire, "sections": [_section(), _section()]},
                {**wire, "extra": True}):
        with pytest.raises(ValueError):
            api.StructuredResultsV1.from_dict(bad, facts=_facts(), dependency_ids={"model:x"})


def test_section_specific_fields_reject_arbitrary_summary_blob():
    wire = _section()
    wire["content"]["fields"]["raw_model_results"] = {"kind": "text", "value": "not allowed"}
    with pytest.raises(ValueError):
        _parse(wire)


@pytest.mark.parametrize("envelope", [False, True])
@pytest.mark.parametrize("mutation", ["nan", "collision"])
def test_canonical_failures_are_contract_errors(envelope, mutation):
    api = _api(); section = _section()
    fields = section["content"]["fields"]["results"]["items"][0]["fields"]
    if mutation == "nan":
        fields["label"]["value"] = float("nan")
    else:
        fields.update({"é": {"kind": "null"}, "e\u0301": {"kind": "null"}})
    with pytest.raises(api.ResultSectionError) as error:
        if envelope:
            from workbench.contracts.evidence.envelope import EvidenceEnvelopeV1
            wire = _load()
            wire["family_evidence"]["structured_results"] = {
                "schema_version": 1, "contract_digest": api.RESULT_SECTIONS_CONTRACT_DIGEST,
                "sections": [section]}
            EvidenceEnvelopeV1.from_dict(wire)
        else:
            _parse(section)
    assert error.value.code == "RESULT_SECTION_INVALID"


def test_oversized_text_rejected_without_proportional_allocation():
    import tracemalloc
    api = _api(); wire = _section()
    wire["content"]["fields"]["warnings"] = {"kind": "text", "value": "x" * (8 * 1024 * 1024)}
    tracemalloc.start()
    try:
        with pytest.raises(api.ResultSectionError):
            _parse(wire)
        assert tracemalloc.get_traced_memory()[1] < 256 * 1024
    finally:
        tracemalloc.stop()


def test_field_shapes_are_immutable_and_digest_bound():
    api = _api()
    with pytest.raises(TypeError):
        api.FIELD_SHAPES["method"] = frozenset({"object"})
    declaration = api.result_sections_declaration()
    from workbench.canonical import sha256_canonical
    assert sha256_canonical(declaration) == api.RESULT_SECTIONS_CONTRACT_DIGEST
    declaration["field_shapes"]["method"] = ["object"]
    assert sha256_canonical(declaration) != api.RESULT_SECTIONS_CONTRACT_DIGEST


def _manifest_envelope():
    wire = _load()
    wire["result_identity"].update(run_id="r1")
    wire["family_evidence"]["result_dependencies"] = {
        "schema_version": 1, "project_ref": "project:1", "run_id": "r1", "records": [{
            "artifact_id": "a", "path": ["runs", "r1", "a.json"], "sha256": "a" * 64,
            "index_record": {"artifact_id": "a", "path": "a.json", "sha256": "a" * 64,
                             "artifact_type": "model_results", "step": "estimation", "inputs": []}}]}
    return wire


def test_c0_admits_only_versioned_safe_dependency_paths():
    from workbench.evidence.contracts import EvidenceEnvelopeFacadeV1, _validate_envelope_provenance
    _validate_envelope_provenance(EvidenceEnvelopeFacadeV1.from_dict(_manifest_envelope()))
    for target in ("manifest", "extra"):
        wire = _manifest_envelope()
        row = wire["family_evidence"]["result_dependencies"]["records"][0]
        if target == "manifest":
            row["path"] = ["runs", "r1", "..", "secret"]
        else:
            row["index_record"]["extra"] = {"source_path": "/private/secret"}
        with pytest.raises(ValueError):
            _validate_envelope_provenance(EvidenceEnvelopeFacadeV1.from_dict(wire))


def test_section_rejects_wrong_semantic_field_shape():
    wire = _section()
    wire["content"]["fields"]["results"] = {"kind": "text", "value": "invented result"}
    wire["fact_refs"] = []
    with pytest.raises(ValueError):
        _parse(wire)


def test_envelope_admission_rejects_invalid_structured_extension():
    from workbench.contracts.evidence.envelope import EvidenceEnvelopeV1
    wire = _load()
    wire["family_evidence"]["structured_results"] = {
        "schema_version": 99, "contract_digest": "a" * 64, "sections": [],
    }
    with pytest.raises(ValueError, match="UNSUPPORTED_VERSION"):
        EvidenceEnvelopeV1.from_dict(wire)


@pytest.mark.parametrize("node", [{"kind": "text", "value": "0.05"},
                                  {"kind": "boolean", "value": True}, {"kind": "null"}])
def test_nested_numerical_roles_cannot_be_disguised_as_metadata(node):
    wire = _section(); wire["fact_refs"] = []
    wire["content"]["fields"]["results"]["items"][0]["fields"]["p_value"] = node
    with pytest.raises(ValueError):
        _parse(wire)


def test_counts_cannot_use_fractional_number_representation():
    wire = _section()
    wire["content"]["fields"]["results"]["items"][0]["fields"]["nobs"] = {
        "kind": "fact", "fact_id": "p:x", "representation": "number"}
    with pytest.raises(ValueError):
        _parse(wire)


def test_available_section_requires_declared_result_fields():
    wire = _section(); wire["fact_refs"] = []
    wire["content"] = {"kind": "object", "fields": {"warnings": {"kind": "list", "items": []}}}
    with pytest.raises(ValueError):
        _parse(wire)


def test_envelope_rejects_oversize_sections_before_family_canonicalization(monkeypatch):
    from workbench.contracts.evidence import envelope as module
    original = module._mapping
    def guarded(value, name):
        assert name != "family_evidence", "oversized family was materialized"
        return original(value, name)
    wire = _load()
    wire["family_evidence"]["structured_results"] = {
        "schema_version": 1, "contract_digest": _api().RESULT_SECTIONS_CONTRACT_DIGEST,
        "sections": [_section()] * 129}
    monkeypatch.setattr(module, "_mapping", guarded)
    with pytest.raises(ValueError):
        module.EvidenceEnvelopeV1.from_dict(wire)


def test_aggregate_budget_precedes_section_freezing(monkeypatch):
    api = _api(); sections = []
    for i in range(3):
        wire = _section(); wire["section_id"] = f"test:{i}"
        wire["content"]["fields"]["warnings"] = {
            "kind": "list", "items": [{"kind": "text", "value": "x" * 4096}] * 200}
        sections.append(wire)
    def forbidden(*_args, **_kwargs):
        pytest.fail("oversized extension reached recursive freezing")
    monkeypatch.setattr(api, "freeze_json", forbidden)
    with pytest.raises(ValueError):
        api.StructuredResultsV1.from_dict({"schema_version": 1,
            "contract_digest": api.RESULT_SECTIONS_CONTRACT_DIGEST, "sections": sections},
            facts=_facts(), dependency_ids={"model:x"})


@pytest.mark.parametrize("column", ["income", "p_value", "nobs"])
def test_dynamic_labels_are_not_statistical_field_names(column):
    wire = _section()
    wire.update(section_type="descriptive_statistics", fact_refs=[])
    wire["content"] = {"kind": "object", "fields": {
        "rows": {"kind": "list", "items": []},
        "labels": {"kind": "object", "fields": {column: {"kind": "text", "value": "Variable label"}}}}}
    assert _parse(wire).to_dict() == wire


def test_dynamic_model_ids_do_not_override_regression_value_roles():
    wire = _section()
    wire.update(section_type="regression_table")
    wire["content"] = {"kind": "object", "fields": {
        "models": {"kind": "object", "fields": {"nobs": {"kind": "object", "fields": {}}}},
        "rows": {"kind": "list", "items": [{"kind": "object", "fields": {
            "models": {"kind": "object", "fields": {"p_value": {"kind": "object", "fields": {
                "estimate": {"kind": "fact", "fact_id": "p:x", "representation": "number"}}}}}}}]}}}
    assert _parse(wire).to_dict() == wire
    wire["content"]["fields"]["rows"]["items"][0]["fields"]["models"]["fields"]["p_value"]["fields"]["estimate"] = {"kind": "text", "value": "0.01"}
    wire["fact_refs"] = []
    with pytest.raises(ValueError):
        _parse(wire)


@pytest.fixture
def lmm_namespace_envelope(namespace_producer):
    from tests.test_lmm_result_adapter import _complete_payload, _envelope
    from tests.test_v189_report_result_sections import prepare
    from workbench.artifacts import write_json, register_artifact
    from workbench.report_view_model import build_regression_table
    from workbench.engine.packs.linear_mixed_effects.runner import _TERMINAL_RESULT_ARTIFACT_ID, _TERMINAL_RESULT_PATH
    _, run, _ = namespace_producer
    payload = _complete_payload()
    payload["execution_binding"]["run_id"] = "r1"
    write_json(run / _TERMINAL_RESULT_PATH, _envelope(payload))
    register_artifact(run, _TERMINAL_RESULT_ARTIFACT_ID, run / _TERMINAL_RESULT_PATH,
                      "model_result_packet", "linear_mixed_effects", [])
    return prepare(namespace_producer, model_run_id=payload["model_id"], primary_model_type="linear_mixed_effects",
        model_artifact_ids=[_TERMINAL_RESULT_ARTIFACT_ID],
        regression_table=build_regression_table([(payload["model_id"], payload)]))


def _admit_namespace_provenance(wire):
    from workbench.evidence.contracts import EvidenceEnvelopeFacadeV1, _validate_envelope_provenance
    facade = EvidenceEnvelopeFacadeV1.from_dict(wire)
    _validate_envelope_provenance(facade)
    assert facade.to_dict() == wire


def test_declared_lmm_namespace_real_prepare_to_c0(namespace_producer, lmm_namespace_envelope):
    factory = namespace_producer[0]
    envelope = lmm_namespace_envelope
    model_id = envelope["result_identity"]["model_run_id"]
    receipt = factory.issue_production_receipt(run_id="r1", model_run_id=model_id, upload_hash="a" * 64)
    owner = factory.create_for_run(run_id="r1", model_run_id=model_id, production_receipt=receipt,
        envelope=envelope, artifact_file_sha256=factory.report_evidence_file_sha256(envelope))
    assert owner._canonical_report_artifact().envelope.to_dict() == envelope


def test_declared_namespace_not_hardcoded_to_lmm(lmm_namespace_envelope):
    wire = deepcopy(lmm_namespace_envelope)
    record = wire["family_evidence"]["result_dependencies"]["records"][0]
    old = record["artifact_id"]
    new = "model_results.other_model-2"
    record["artifact_id"] = record["index_record"]["artifact_id"] = new
    record["index_record"]["path"] = "artifacts/model_results/other_model-2.result.json"
    record["path"] = ["runs", "r1", "artifacts", "model_results", "other_model-2.result.json"]
    for section in wire["family_evidence"]["structured_results"]["sections"]:
        section["dependency_refs"] = [new if ref == old else ref for ref in section["dependency_refs"]]
    for dependency in wire["dependencies"]:
        if dependency.get("artifact_ref") == old:
            dependency["artifact_ref"] = new
    _admit_namespace_provenance(wire)


@pytest.mark.parametrize("attack", ["foreign_ref", "wrong_namespace", "wrong_type", "wrong_path", "unsealed",
    "extra_source_ref", "extra_path", "manifest_source_ref", "hash_mismatch", "dotted_model_id"])
def test_namespace_admission_stays_position_and_manifest_bound(lmm_namespace_envelope, attack):
    wire = deepcopy(lmm_namespace_envelope)
    family = wire["family_evidence"]
    manifest = family["result_dependencies"]
    record = manifest["records"][0]
    identity = record["artifact_id"]
    dependency = next(item for item in wire["dependencies"] if item.get("artifact_ref") == identity)
    if attack == "foreign_ref":
        for section in family["structured_results"]["sections"]:
            section["dependency_refs"] = ["model_results.foreign" if ref == identity else ref for ref in section["dependency_refs"]]
        dependency["artifact_ref"] = "model_results.foreign"
    elif attack in {"wrong_namespace", "dotted_model_id"}:
        new = "foreign.model" if attack == "wrong_namespace" else "model_results.nested.model"
        record["artifact_id"] = record["index_record"]["artifact_id"] = new
        dependency["artifact_ref"] = new
        for section in family["structured_results"]["sections"]:
            section["dependency_refs"] = [new if ref == identity else ref for ref in section["dependency_refs"]]
    elif attack == "wrong_type":
        record["index_record"]["artifact_type"] = "model_result"
    elif attack == "wrong_path":
        record["index_record"]["path"] = "artifacts/model_results/foreign.result.json"
        record["path"][-1] = "foreign.result.json"
    elif attack == "unsealed":
        family.pop("result_dependencies")
    elif attack == "extra_source_ref":
        dependency["source_ref"] = identity
    elif attack == "extra_path":
        dependency["metadata"] = {"path": "artifacts/model_results/foreign.result.json"}
    elif attack == "manifest_source_ref":
        record["index_record"]["source_ref"] = identity
    elif attack == "hash_mismatch":
        record["sha256"] = "b" * 64
    with pytest.raises(ValueError):
        _admit_namespace_provenance(wire)


def test_namespace_does_not_relax_global_opaque_ref():
    from workbench.evidence.contracts import _opaque_ref
    with pytest.raises(ValueError):
        _opaque_ref("model_results.other_model-2", "source_ref")


@pytest.fixture
def bracket_selector_envelope(namespace_producer):
    from tests.test_v189_report_result_sections import prepare
    return prepare(namespace_producer, report_fields={"statistical_evidence": {
        "results": [{"dy/dx": 0.25, 'quoted"key\\tail': 0.5}]}})


def test_bound_bracket_selectors_preserve_slashes_quotes_and_backslashes(namespace_producer, bracket_selector_envelope):
    factory = namespace_producer[0]
    wire = bracket_selector_envelope
    _admit_namespace_provenance(wire)
    receipt = factory.issue_production_receipt(run_id="r1", model_run_id="ols_1", upload_hash="a" * 64)
    owner = factory.create_for_run(run_id="r1", model_run_id="ols_1", production_receipt=receipt,
        envelope=wire, artifact_file_sha256=factory.report_evidence_file_sha256(wire))
    assert owner._canonical_report_artifact().envelope.to_dict() == wire


@pytest.mark.parametrize("attack", ["malformed", "negative", "leading_zero", "float_index", "trailing",
    "raw_path", "wrong_prefix", "unknown_section", "unknown_field", "unbound", "digest", "type", "path",
    "extra_key", "unsealed", "extra_provenance", "wrong_fact"])
def test_bracket_selector_exception_is_exact_and_source_bound(bracket_selector_envelope, attack):
    wire = deepcopy(bracket_selector_envelope)
    fact = next(f for f in wire["numeric_facts"] if 'dy/dx' in f["source_selector"]["selector"])
    source = fact["source_selector"]
    manifest = wire["family_evidence"]["result_dependencies"]
    record = next(r for r in manifest["records"] if r["artifact_id"] == source["artifact_ref"])
    malformed = {
        "malformed": '$["sections"]["statistical_tests"]["results"][0]["dy/dx"',
        "negative": source["selector"].replace('[0]', '[-1]'),
        "leading_zero": source["selector"].replace('[0]', '[00]'),
        "float_index": source["selector"].replace('[0]', '[0.0]'),
        "trailing": source["selector"] + '.__class__',
        "raw_path": '/runs/r1/result_input.json',
        "wrong_prefix": source["selector"].replace('"sections"', '"files"'),
        "unknown_section": source["selector"].replace('"statistical_tests"', '"not_declared"'),
        "unknown_field": source["selector"].replace('"dy/dx"', '"unknown/field"'),
    }
    if attack in malformed:
        source["selector"] = malformed[attack]
    elif attack == "unbound":
        source["artifact_ref"] = "result-input:foreign"
    elif attack == "digest":
        source["artifact_digest"] = "b" * 64
    elif attack == "type":
        record["index_record"]["artifact_type"] = "model_result"
    elif attack == "path":
        record["path"][-1] = record["index_record"]["path"] = "other.json"
    elif attack == "extra_key":
        source["path"] = "result_input.json"
    elif attack == "unsealed":
        wire["family_evidence"].pop("result_dependencies")
    elif attack == "extra_provenance":
        wire["dependencies"][0]["selector"] = source["selector"]
    elif attack == "wrong_fact":
        source["selector"] = next(f["source_selector"]["selector"] for f in wire["numeric_facts"]
                                  if f["fact_id"] != fact["fact_id"] and 'quoted' in f["source_selector"]["selector"])
    with pytest.raises(ValueError):
        _admit_namespace_provenance(wire)


@pytest.mark.parametrize("key", ["dy/dx", "x.y", 'a"b', "a[b]", "效应/变化", "a\\b"])
def test_bracket_selector_accepts_generic_json_key_tokens(namespace_producer, key):
    from tests.test_v189_report_result_sections import prepare
    wire = prepare(namespace_producer, report_fields={"statistical_evidence": {"results": [{key: 0.125}]}})
    _admit_namespace_provenance(wire)


@pytest.mark.parametrize("selector", [
    '$["sections"]["statistical_tests"]["bad\\q"]',
    '$["sections"]["statistical_tests"]garbage',
    '$["sections"]["statistical_tests"]' + '[0]' * 100,
    '$["sections"]["statistical_tests"]["' + 'x' * 500000 + '"]',
], ids=["escape", "trailing", "depth", "size"])
def test_bad_selector_fails_before_json_decode_and_defensive_copy(bracket_selector_envelope, selector, monkeypatch):
    from workbench.evidence import contracts
    wire = deepcopy(bracket_selector_envelope)
    wire["numeric_facts"][0]["source_selector"]["selector"] = selector
    facade = contracts.EvidenceEnvelopeFacadeV1.from_dict(wire)
    def forbidden(*args, **kwargs):
        pytest.fail("invalid selector reached JSON decode or defensive copy")
    monkeypatch.setattr(contracts.EvidenceEnvelopeFacadeV1, "to_dict", forbidden)
    monkeypatch.setattr(contracts.json, "loads", forbidden)
    with pytest.raises(ValueError):
        contracts._validate_envelope_provenance(facade)
