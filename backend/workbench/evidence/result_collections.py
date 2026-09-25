"""Owner-issued complete LOCAL collections, never oversized delivery projections.

Each input page retains its delivery budget. This module assembles bounded
local data for renderers; neither this capability nor its wire authorizes egress.
"""
from __future__ import annotations

from types import MappingProxyType
from threading import RLock
import weakref

from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.contracts.common.envelope import freeze_json, thaw_json
from workbench.contracts.evidence.envelope import NumericFactV1
from workbench.contracts.evidence.result_pages import MAX_BUNDLE_BYTES, ResultPageV1, ResultPageAccumulatorV1
from workbench.contracts.evidence.result_sections import ResultSectionV1
from workbench.evidence.authority import build_authority_request, issue_host_proof, validate_host_proof
from workbench.evidence.consumer_adapters import (
    EvidenceProjectionError, ProjectionStatus, default_projection_registry,
    parse_result_section_bundle, _structured_row_count, _result_section_bundle_bytes,
)

MAX_COLLECTION_BYTES = MAX_BUNDLE_BYTES
MAX_COLLECTION_PAGES = 4096
_IDENTITY_KEYS = ("actor_ref", "project_ref", "session_ref", "scope_ref", "run_id", "model_run_id", "confirmation_ref")


def _fail(message):
    raise EvidenceProjectionError("RESULT_COLLECTION_INVALID", message)


def _owner_fields(owner):
    from workbench.services.results_service import ServerOwnedReportEvidencePersistenceV1
    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        _fail("exact server owner required")
    owner._require_report_authority()
    identity = owner._require_report_request_identity(None)
    source, _artifact = owner._canonical_report_source_and_artifact()
    registry = default_projection_registry()
    fields, _observed, spec, extended, deliver = registry._prepare_selection(
        source, consumer_id="report", destination="local")
    if (not extended or not deliver or not fields["sections"]
            or fields["status"] not in {ProjectionStatus.AVAILABLE, ProjectionStatus.DEGRADED}):
        _fail("complete structured evidence is unavailable")
    if {ref for section in fields["sections"] for ref in section.fact_refs} != {f.fact_id for f in fields["facts"]}:
        _fail("complete section directory does not cover every original fact")
    return source, fields, spec, {key: getattr(identity, key) for key in _IDENTITY_KEYS}


def _fields_wire(fields):
    result = dict(fields)
    for key in ("projection_ref", "audit"):
        result[key] = fields[key].to_dict()
    result["status"] = fields["status"].value
    result["facts"] = [f.to_dict() for f in fields["facts"]]
    result["sections"] = [s.to_dict() for s in fields["sections"]]
    for key in ("result_identity", "validation_summary", "result_dependencies", "semantic_selection", "lineage_refs"):
        result[key] = thaw_json(fields[key])
    return result


def _collection_wire(fields, directory, identity):
    return {"schema_version": 1, "delivery_kind": "local_complete_collection", "destination": "local",
            "read_completeness": "COMPLETE", "completion_scope": "run",
            "identity": dict(identity), "section_directory": thaw_json(directory), **_fields_wire(fields)}


def _make_collection_api():
    issued = weakref.WeakKeyDictionary()
    lock = RLock()

    class ServerOwnedLocalResultCollectionV1:
        __slots__ = ("__weakref__",)

        def __init__(self):
            raise TypeError("complete collections require server owner issuance")

        def __setattr__(self, name, value):
            raise TypeError("complete collection is immutable")

        def __copy__(self):
            raise TypeError("complete collections cannot be copied")

        def __deepcopy__(self, memo):
            raise TypeError("complete collections cannot be copied")

        def __reduce__(self):
            raise TypeError("complete collections cannot be serialized as capabilities")

        def __getattr__(self, name):
            state = state_for(self)
            if name == "read_completeness":
                return "COMPLETE"
            if name == "section_directory":
                return state["directory"]
            if name == "collection_digest":
                return state["digest"]
            if name in state["fields"]:
                return state["fields"][name]
            raise AttributeError(name)

        def to_dict(self):
            state = state_for(self)
            return {**_collection_wire(state["fields"], state["directory"], state["identity"]),
                    "collection_digest": state["digest"]}

    def state_for(collection):
        if type(collection) is not ServerOwnedLocalResultCollectionV1:
            _fail("exact collection capability required")
        with lock:
            state = issued.get(collection)
        if state is None:
            _fail("collection was not issued")
        return state

    def validate(collection, *, owner):
        state = state_for(collection)
        if state["owner"] is not owner:
            _fail("collection belongs to a different owner")
        source, current, _spec, identity = _owner_fields(owner)
        if (identity != state["identity"] or source._payload_digest() != state["source_digest"]
                or sha256_canonical(_collection_wire(current, state["directory"], identity)) != state["digest"]):
            _fail("collection no longer matches current owner evidence")
        validate_host_proof(owner._authority_handle, state["request"], state["proof"])

    def collect(owner, *, max_wire_bytes=None):
        source, expected, spec, identity = _owner_fields(owner)
        if len(canonical_json_v1(_fields_wire(expected)).encode("utf-8")) > MAX_COLLECTION_BYTES:
            _fail("collection exceeds local resource ceiling")
        source_binding = source._payload_digest()
        directory, collected_sections, collected_facts = [], [], {}
        consumed = page_count = 0
        for section in expected["sections"]:
            selected, _observed, _spec, extended, deliver = default_projection_registry()._prepare_selection(
                source, consumer_id="report", destination="local", requested_fact_ids=(),
                requested_section_ids=(section.section_id,))
            if not extended or not deliver or selected["status"] not in {ProjectionStatus.AVAILABLE, ProjectionStatus.DEGRADED}:
                _fail("owner section is no longer available for local delivery")
            expected_bundle = _result_section_bundle_bytes(selected)
            expected_rows = _structured_row_count(selected["facts"], selected["sections"], selected["result_dependencies"])
            offset, accumulator, count, bundle = 0, None, 0, None
            while offset is not None:
                page_count += 1
                if page_count > MAX_COLLECTION_PAGES:
                    _fail("collection exceeds bounded page count")
                wire = owner.read_result_section_page(consumer_id="report", section_id=section.section_id,
                    offset=offset, max_wire_bytes=max_wire_bytes)
                receipt, delivery = wire["receipt"], wire["delivery"]
                if (wire["identity"] != identity or receipt["identity"] != identity
                        or delivery["identity"] != {key: identity[key] for key in ("project_ref", "run_id", "scope_ref")}
                        or delivery["consumer_id"] != "report" or delivery["destination"] != "local"
                        or wire["consumer_id"] != "report" or wire["destination"] != "local"
                        or receipt["kind"] != "evidence.report.page-receipt.v1"
                        or receipt["wire_digest"] != sha256_canonical({k: v for k, v in wire.items() if k != "receipt"})
                        or receipt["payload_digest"] != delivery["wire_digest"]
                        or delivery["wire_digest"] != sha256_canonical({k: v for k, v in delivery.items() if k != "wire_digest"})):
                    _fail("page receipt or owner identity changed")
                for key, value in (("artifact_ref", expected["artifact_ref"]), ("commit_id", expected["commit_id"]),
                                   ("envelope_digest", expected["envelope_digest"])):
                    if wire[key] != value or delivery[key] != value or receipt["provenance"][key] != value:
                        _fail("page source binding changed")
                size = len(canonical_json_v1(wire).encode("utf-8"))
                if (size > (max_wire_bytes or spec.max_token_budget * 4)
                        or wire["audit"]["token_budget"] != (size + 3) // 4
                        or wire["audit"]["token_budget"] > spec.max_token_budget
                        or type(wire["audit"]["row_budget"]) is not int
                        or wire["audit"]["row_budget"] != expected_rows
                        or delivery["audit"]["row_budget"] != expected_rows
                        or wire["audit"]["row_budget"] > spec.max_row_budget):
                    _fail("page exceeds declared final delivery budget")
                page = ResultPageV1.from_dict(delivery["page"])
                binding = dict(source_ref=expected["artifact_ref"], source_digest=expected["envelope_digest"],
                    section_id=section.section_id, consumer_id="report", destination="local")
                if accumulator is None:
                    if consumed + page.total_bytes > MAX_COLLECTION_BYTES:
                        _fail("section bundles exceed local resource ceiling")
                    accumulator = ResultPageAccumulatorV1(binding, max_total_bytes=MAX_COLLECTION_BYTES - consumed)
                accumulator.add(page)
                offset, count = page.next_offset, count + 1
            raw = accumulator.finish()
            if raw != expected_bundle:
                _fail("complete section bundle differs from its canonical owner binding")
            bundle = parse_result_section_bundle(raw)
            if canonical_json_v1(bundle["section"]) != canonical_json_v1(section.to_dict()):
                _fail("reassembled section differs from owner directory")
            facts = {f["fact_id"]: NumericFactV1.from_dict(thaw_json(f)) for f in bundle["facts"]}
            originals = {f.fact_id: f for f in expected["facts"] if f.fact_id in section.fact_refs}
            if canonical_json_v1({k: f.to_dict() for k, f in facts.items()}) != canonical_json_v1({k: f.to_dict() for k, f in originals.items()}):
                _fail("reassembled facts differ from owner evidence")
            rows = _structured_row_count(tuple(facts.values()), (section,), bundle["result_dependencies"])
            if wire["audit"]["row_budget"] != rows:
                _fail("page row charge differs from logical section charge")
            collected_facts.update(facts)
            collected_sections.append(ResultSectionV1.from_dict(bundle["section"], facts=facts,
                dependency_ids={r["artifact_id"] for r in bundle["result_dependencies"]["records"]}))
            consumed += len(raw)
            directory.append(dict(section_id=section.section_id, section_type=bundle["section"]["section_type"],
                status=bundle["section"]["status"], section_digest=sha256_canonical(bundle["section"]),
                bundle_digest=page.bundle_digest, total_bytes=len(raw), received_bytes=len(raw), page_count=count))
        if set(collected_facts) != {f.fact_id for f in expected["facts"]}:
            _fail("collection fact coverage is incomplete")
        _source, current, _spec, current_identity = _owner_fields(owner)
        if (current_identity != identity or _source._payload_digest() != source_binding
                or sha256_canonical(_fields_wire(current)) != sha256_canonical(_fields_wire(expected))):
            _fail("owner source changed during collection")
        fields = dict(expected, facts=tuple(collected_facts[f.fact_id] for f in expected["facts"]),
                      sections=tuple(collected_sections))
        for key in ("result_identity", "validation_summary", "result_dependencies", "semantic_selection", "lineage_refs"):
            fields[key] = freeze_json(fields[key])
        fields, directory = MappingProxyType(fields), freeze_json(directory)
        digest = sha256_canonical(_collection_wire(fields, directory, identity))
        collection = object.__new__(ServerOwnedLocalResultCollectionV1)
        request = build_authority_request(owner._authority_handle, purpose="evidence.report.local_collection",
            scope_ref=owner.scope_ref, subject_id=id(collection), payload_digest=digest)
        proof = issue_host_proof(owner._authority_handle, request)
        validate_host_proof(owner._authority_handle, request, proof)
        with lock:
            issued[collection] = dict(owner=owner, fields=fields, directory=directory, identity=identity,
                digest=digest, source_digest=source_binding, request=request, proof=proof)
        return collection

    return ServerOwnedLocalResultCollectionV1, collect, validate


(ServerOwnedLocalResultCollectionV1, collect_server_owned_local_results,
 validate_server_owned_local_result_collection) = _make_collection_api()
del _make_collection_api
