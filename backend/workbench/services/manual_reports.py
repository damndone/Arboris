"""Deterministic manual reports over persisted public evidence, without an LLM.

Reports are immutable artifacts. Prose, selections and a source fingerprint are
client inputs; values, provenance, timestamps and revision numbers are not.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
import stat
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field

from .. import analysis_disclosure
from ..agent.family_evidence import bounded_model_family_evidence
from ..agent.workflow_runtime import collect_post_estimation_results, count_post_estimation_results
from ..api_errors import WorkbenchAPIError
from ..artifacts import read_json, register_artifact, sha256_file, write_json
from ..graph_store import GraphStore, graph_to_json
from ..lineage.headset import forest_node_key
from ..predictive_research.schema import default_v1_prediction_registry
from .manual_report_text import draft_text, render_values, resolved_ids
from ..report_contract import validate_report_packet, validate_report_response
from ..report_export import export_report
from ..report_view_model import build_regression_table
from ..repository.run_repository import _read_artifacts_index
from .lmm_result_adapter import read_lmm_public_results

REPORT_ID = re.compile(r"^mrpt_[A-Za-z0-9_-]{3,100}$")
SAFE_FIGURE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_FACTS = 5000
COEFFICIENT_FIELDS = frozenset({
    "estimate", "std_error", "p_value", "t_stat", "z_stat", "statistic",
    "ci_lower", "ci_upper", "conf_int", "confidence_interval", "ci",
    "df", "df_resid", "result_id", "inference", "se_type", "covariance_estimator",
    "source_id", "confidence_level", "inference_method", "variance_source", "t_value", "z_value",
})


class ManualReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: str = Field(pattern=r"^mrpt_[A-Za-z0-9_-]{3,100}$")
    source_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=2_000_000)
    fact_ids: list[str] = Field(max_length=MAX_FACTS)
    figure_ids: list[str] = Field(default_factory=list, max_length=100)
    parent_report_id: str | None = Field(default=None, pattern=r"^mrpt_[A-Za-z0-9_-]{3,100}$")


def _error(code: str, message: str, status: int = 422) -> WorkbenchAPIError:
    return WorkbenchAPIError(status_code=status, code=code, message=message)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def _inside(run_root: Path, relative: str) -> Path:
    path = (run_root / relative).resolve()
    if not path.is_relative_to(run_root.resolve()) or not path.is_file():
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Evidence file is missing or outside this run.")
    return path


def _source_bytes(run_root: Path, relative: str) -> bytes:
    """Read one regular file without following links in any relative component."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(part in {".", ".."} for part in parts):
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Evidence path is not run-relative.")
    descriptors = []
    try:
        current = os.open(run_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            descriptors.append(current)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
        descriptors.append(fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise _error("MANUAL_REPORT_SOURCE_INVALID", "Evidence must be a regular file.")
        with os.fdopen(os.dup(fd), "rb") as stream:
            return stream.read()
    except OSError as exc:
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Evidence file is missing or contains a symlink.") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _json_object(data: bytes) -> dict:
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Evidence is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Evidence must be a JSON object.")
    return payload


def _source_records(run_root: Path) -> list[dict]:
    if not os.path.lexists(run_root / "artifacts_index.json"):
        return []
    records = _json_object(_source_bytes(run_root, "artifacts_index.json")).get("artifacts", [])
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Evidence registration is invalid.")
    return records


def _registered_snapshot(run_root: Path, records: list[dict], relative: str) -> tuple[dict, bytes, dict] | None:
    matches = [record for record in records if record.get("path") == relative]
    if not matches:
        return None
    record = matches[0]
    identity = record.get("artifact_id")
    if len(matches) != 1 or not isinstance(identity, str) or not identity or sum(
        item.get("artifact_id") == identity for item in records
    ) != 1:
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Evidence registration must have a unique identity and path.")
    data = _source_bytes(run_root, relative)
    if hashlib.sha256(data).hexdigest() != record.get("sha256"):
        raise _error("MANUAL_REPORT_SOURCE_CHANGED", "Registered evidence no longer matches its recorded hash.", 409)
    payload = _json_object(data)
    if "run_id" in payload and payload["run_id"] != run_root.name:
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Evidence belongs to a different run.")
    return record, data, payload


def _registered_models(run_root: Path, records: list[dict]) -> list[dict]:
    models = []
    for record in sorted(records, key=lambda item: str(item.get("path", ""))):
        relative = record.get("path")
        if not isinstance(relative, str) or not relative.startswith("model_results/"):
            continue
        if record.get("artifact_type") != "model_result":
            continue
        snapshot = _registered_snapshot(run_root, records, relative)
        _, _, payload = snapshot
        identity = record["artifact_id"]
        if relative != f"model_results/{identity}.json" or payload.get("model_id") != identity:
            raise _error("MANUAL_REPORT_SOURCE_INVALID", "Model identity does not match its registered artifact.")
        if isinstance(payload.get("coefficients"), dict):
            models.append(payload)
    # Versioned LMM packets retain their existing descriptor-pinned identity,
    # execution binding, payload-contract and hash validation.
    if os.path.lexists(run_root / "artifacts_index.json"):
        models.extend(read_lmm_public_results(run_root))
    return models


def _registered_metrics(run_root: Path, records: list[dict]) -> dict:
    snapshot = _registered_snapshot(run_root, records, "diagnostic_summary.json")
    if snapshot is None:
        return {}
    record, _, summary = snapshot
    if record.get("artifact_id") != "diagnostic_summary" or record.get("artifact_type") != "metadata" or summary.get("run_id") != run_root.name:
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Diagnostic summary identity is invalid.")
    stats = {}
    nobs = (summary.get("model_identity") or {}).get("n_observations")
    if isinstance(nobs, (int, float)) and nobs:
        stats["n_observations"] = nobs
    metrics = (summary.get("model_quality") or {}).get("metrics")
    if isinstance(metrics, dict):
        stats.update({key: value for key, value in metrics.items() if isinstance(value, (int, float))})
    return stats


def _registered_family_evidence(run_root: Path, records: list[dict], models: list[dict]) -> dict | None:
    if not models:
        return None
    from ..contracts.model.result_envelope_registry import declaration_for

    declaration = declaration_for(models[0].get("kernel_family") or models[0].get("model_type"))
    if declaration is None:
        return None
    relatives = set(declaration.sidecars.values())
    if declaration.evidence_document:
        relatives.add(declaration.evidence_document)
    if not relatives:
        return bounded_model_family_evidence(run_root, models)
    # Project the exact verified bytes through the existing family bounds. The
    # legacy projector may reread documents, so give it only pinned snapshots;
    # never allow that second read to admit an unregistered file or race.
    with TemporaryDirectory(prefix="workbench-report-evidence-") as directory:
        pinned = Path(directory) / run_root.name
        pinned.mkdir()
        selected = []
        for relative in sorted(relatives):
            snapshot = _registered_snapshot(run_root, records, relative)
            if snapshot is None:
                continue
            record, data, _ = snapshot
            target = pinned / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            selected.append(record)
        write_json(pinned / "artifacts_index.json", {"artifacts": selected})
        return bounded_model_family_evidence(pinned, models)


def _figures(run_root: Path) -> list[dict]:
    figures = []
    seen = set()
    for record in _read_artifacts_index(run_root).get("artifacts", []):
        if record.get("artifact_type") != "figure":
            continue
        identity = record.get("artifact_id")
        if not isinstance(identity, str) or not SAFE_FIGURE_ID.fullmatch(identity) or identity in seen:
            raise _error("MANUAL_REPORT_SOURCE_INVALID", "Figure identities must be safe and unique.")
        seen.add(identity)
        path = _inside(run_root, str(record.get("path", "")))
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
            continue
        digest = sha256_file(path)
        if record.get("sha256") != digest:
            raise _error("MANUAL_REPORT_SOURCE_CHANGED", "A registered figure no longer matches its recorded hash.", 409)
        figures.append({"artifact_id": identity, "chart_type": identity, "sha256": digest})
    return sorted(figures, key=lambda item: item["artifact_id"])


def build_manual_report_draft(run_root: Path) -> dict:
    records = _source_records(run_root)
    models = _registered_models(run_root, records)
    model_ids = {model["model_id"] for model in models}
    metrics = _registered_metrics(run_root, records)
    facts: list[dict] = []
    limits = [
        "Evidence uses persisted public graph, coefficient, declared family and registered test projections; it is not a new statistical analysis.",
        "Family evidence follows the existing bounded primary-model projection; this is not an all-family completeness claim.",
        "Raw dataset rows and arbitrary artifact payloads are excluded. Missing inference fields are not inferred.",
    ]

    def emit(value: Any, field: str, *, node: str, ref: str, artifacts: list[str] | None = None, _path: tuple | None = None, source_run_id: str | None = None):
        identity_path = (field,) if _path is None else _path
        if isinstance(value, dict):
            for key in sorted(value):
                emit(value[key], f"{field}/{key}", node=node, ref=ref, artifacts=artifacts, _path=(*identity_path, key), source_run_id=source_run_id)
            return
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                emit(item, f"{field}/{index}", node=node, ref=ref, artifacts=artifacts, _path=(*identity_path, index), source_run_id=source_run_id)
            return
        if not (value is None or isinstance(value, (str, int, float, bool))):
            return
        if isinstance(value, float) and not math.isfinite(value):
            raise _error("MANUAL_REPORT_SOURCE_INVALID", "Evidence contains a non-finite value.")
        if len(facts) >= MAX_FACTS:
            raise _error("MANUAL_REPORT_EVIDENCE_LIMIT", f"Evidence exceeds the {MAX_FACTS}-fact report limit.")
        source = {"run_id": source_run_id or run_root.name, "node_key": node, "result_ref": ref, "artifact_ids": artifacts or []}
        identity = "f_" + _digest([source, identity_path])[7:]
        facts.append({"id": identity, "field": field, "label": field.replace("/", " · "), "value": value, "source": source})

    graph = graph_to_json(GraphStore(run_root.parent).read(run_root.name))
    index_path = run_root / "node_index.json"
    index = read_json(index_path) if index_path.is_file() else {}
    if not graph["nodes"]:
        limits.append("No persisted lineage graph is available for this run.")
    def public_params(value):
        # Parameter forms contain scalar controls and column-name lists. Do
        # not promote embedded tables/row objects into report facts.
        if isinstance(value, dict):
            projected = {key: item for key, item in value.items()
                         if item is None or isinstance(item, (str, int, float, bool))
                         or (isinstance(item, (list, tuple)) and all(
                             v is None or isinstance(v, (str, int, float, bool)) for v in item))}
            if len(projected) != len(value):
                note = "Nested graph parameter objects are omitted; only scalar controls and scalar lists are report facts."
                if note not in limits:
                    limits.append(note)
            return projected
        return value if value is None or isinstance(value, (str, int, float, bool)) else None

    for node_id, node in sorted(graph["nodes"].items()):
        key = forest_node_key(node_id, index)
        for decision in node.get("decision_points", []):
            emit(public_params(decision.get("selected")), f"decision/{decision['decision_id']}/selected", node=key, ref="graph.json")
            params = (decision.get("reason") or {}).get("chosen_params", {})
            emit(public_params(params), f"decision/{decision['decision_id']}/params", node=key, ref="graph.json")
        stats = metrics if node_id.removeprefix("model:") in model_ids and node_id.startswith("model:") else {}
        # Coefficients are projected separately below, including stored CIs.
        emit({k: v for k, v in stats.items() if k not in {"coefficients", "diagnostic_artifacts"}},
             "metric", node=key, ref="diagnostic_summary.json")
    for edge_id, edge in sorted(graph["edges"].items()):
        emit(public_params(edge.get("params", {})), f"param/{edge_id}",
             node=forest_node_key(edge["target_id"], index), ref="graph.json")

    table = build_regression_table([(str(model.get("model_id") or i), model) for i, model in enumerate(models)])
    for i, model in enumerate(models):
        identity = str(model.get("model_id") or i)
        # Statistical definitions are part of the snapshot too, so changing
        # the SE estimator or sample basis invalidates an outstanding draft.
        qualifiers = {key: model[key] for key in (
            "inference", "inference_kernel", "covariance_estimator", "se_type",
            "estimation_method", "inference_method", "confidence_level", "nobs_basis",
            "df_resid", "df_model", "warnings", "formula", "fixed_effects_formula",
        ) if key in model}
        emit(qualifiers, "inference", node=f"model:{identity}", ref=f"model_results:{identity}")
    for model in table["models"]:
        emit(model, "model", node=f"model:{model['id']}", ref=f"model_results:{model['id']}")
    for row in table["rows"]:
        for model_id, cell in row["models"].items():
            if cell is not None:
                emit({k: v for k, v in cell.items() if k in COEFFICIENT_FIELDS},
                     f"coefficient/{row['term']}", node=f"model:{model_id}", ref=f"model_results:{model_id}")
    family = _registered_family_evidence(run_root, records, models)
    if family:
        emit(family, "family", node="run", ref="family_evidence")
    else:
        limits.append("No declared family-specific evidence projection is available for this run.")

    # Reuse the admitted workflow projection, which resolves result ownership
    # and registered artifact hashes instead of accepting arbitrary JSON files.
    post = collect_post_estimation_results(run_root.parent.parent, run_root.name, keep_latest=True)
    total = count_post_estimation_results(run_root.parent.parent, run_root.name)
    if total > len(post):
        limits.append(f"Post-estimation projection includes the latest {len(post)} of {total} results.")
    for entry in post:
        emit(entry["result"], "post_estimation", node=f"workflow:{entry['workflow_step_id']}",
             ref=f"workflow:{entry['workflow_id']}", artifacts=[entry["artifact_id"]], source_run_id=entry["run_id"])

    # Normal-run statistical evidence has its own registered, versioned public
    # payload contract (distinct from workflow post-estimation artifacts).
    for record in _read_artifacts_index(run_root).get("artifacts", []):
        if record.get("path") != "statistical_tests/evidence.json":
            continue
        path = _inside(run_root, record["path"])
        if sha256_file(path) != record.get("sha256"):
            raise _error("MANUAL_REPORT_SOURCE_CHANGED", "Statistical evidence hash changed.", 409)
        raw_packet = read_json(path)
        if raw_packet.get("payload_schema") != "workbench.statistics.evidence-packet":
            raise _error("MANUAL_REPORT_SOURCE_INVALID", "Registered statistical evidence has the wrong payload contract.")
        packet = default_v1_prediction_registry().validate(raw_packet)
        emit(packet, "statistical_evidence", node="run", ref="statistical_tests/evidence.json",
             artifacts=[record["artifact_id"]])

    snapshot = {"run_id": run_root.name, "facts": facts, "figures": _figures(run_root), "limitations": limits}
    fingerprint = _digest({"project": str(run_root.parent.parent.resolve()), **snapshot})
    # Reads like a results section; every number is a value marker bound to
    # its fact, so the prose can be rewritten without touching a number.
    text = draft_text(facts, limits)
    return {"schema_version": "workbench-manual-report-draft/v1", **snapshot,
            "source_fingerprint": fingerprint, "draft_origin": "deterministic", "title": "Analysis report", "text": text}


def _reports_dir(run_root: Path) -> Path:
    path = run_root / "reports"
    if path.is_symlink():
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Report storage must not be a symlink.")
    return path


def _read_report(run_root: Path, report_id: str) -> dict:
    if not REPORT_ID.fullmatch(report_id):
        raise _error("MANUAL_REPORT_NOT_FOUND", "Report revision was not found in this run.", 404)
    path = _reports_dir(run_root) / f"manual_report_{report_id}.json"
    if not path.is_file() or path.is_symlink():
        raise _error("MANUAL_REPORT_NOT_FOUND", "Report revision was not found in this run.", 404)
    payload = read_json(path)
    if payload.get("schema_version") != "workbench-manual-report/v1" or payload["record"]["run_id"] != run_root.name:
        raise _error("MANUAL_REPORT_SOURCE_INVALID", "Stored report identity is invalid.")
    return payload


def list_manual_reports(run_root: Path) -> list[dict]:
    records = [_read_report(run_root, path.stem.removeprefix("manual_report_"))["record"]
               for path in _reports_dir(run_root).glob("manual_report_mrpt_*.json")]
    return sorted(records, key=lambda item: (item["created_at"], item["id"]), reverse=True)


def _request_identity(record: dict) -> dict:
    return {"id": record["id"], "source_fingerprint": record["source_fingerprint"],
            "title": record["title"], "text": record["text"],
            "fact_ids": [f["id"] for f in record["facts"]],
            "figure_ids": [f["artifact_id"] for f in record["figures"]],
            "parent_report_id": record["parent_report_id"]}


def save_manual_report(run_root: Path, request: ManualReportRequest) -> dict:
    directory = _reports_dir(run_root)
    directory.mkdir(exist_ok=True)
    # All manual writers, including distinct server workers, serialize the
    # existence check, revision-parent check and atomic durable publication.
    with FileLock(str(directory / ".manual-reports.lock"), timeout=10):
        path = directory / f"manual_report_{request.id}.json"
        if path.exists():
            existing = _read_report(run_root, request.id)
            if _request_identity(existing["record"]) != request.model_dump():
                raise _error("MANUAL_REPORT_CONFLICT", "Report id already exists with different content.", 409)
            _register_report(run_root, path, request.id)
            return existing
        snapshot = build_manual_report_draft(run_root)
        if snapshot["source_fingerprint"] != request.source_fingerprint:
            raise _error("MANUAL_REPORT_SOURCE_CHANGED", "Evidence changed after this draft was read.", 409)
        selected = {}
        for field, ids, identity in (("facts", request.fact_ids, "id"), ("figures", request.figure_ids, "artifact_id")):
            available = {item[identity]: item for item in snapshot[field]}
            if len(ids) != len(set(ids)) or any(item not in available for item in ids):
                raise _error("MANUAL_REPORT_SELECTION_INVALID", f"Selected {field} must be unique identities in this run's snapshot.")
            selected[field] = [available[item] for item in ids]
        parent = None
        if request.parent_report_id:
            parent = _read_report(run_root, request.parent_report_id)["record"]
            if any(item["parent_report_id"] == parent["id"] for item in list_manual_reports(run_root)):
                raise _error("MANUAL_REPORT_CONFLICT", "The parent revision already has a successor.", 409)
            if any(parent[field] != value for field, value in {**selected, "source_fingerprint": request.source_fingerprint}.items()):
                raise _error("MANUAL_REPORT_CONFLICT", "A prose revision must preserve its parent's evidence snapshot.", 409)
        contract = validate_report_packet({"fact_table": selected["facts"], "figures": selected["figures"]})
        # Figure markers are generated during export; user prose may cite only
        # selected fact IDs and may not inject arbitrary image identities.
        validate_report_response(request.text, contract, require_figure_markers=False)
        _shown, unknown = resolved_ids(request.text, {fact["id"]: fact for fact in selected["facts"]})
        if unknown:
            raise _error("MANUAL_REPORT_SELECTION_INVALID",
                         "The text shows values of facts that are not in the selected evidence, or a marker that "
                         f"names more than one fact: {', '.join(sorted(set(unknown))[:5])}.")
        record = {"id": request.id, "run_id": run_root.name, "author": "user", "draft_origin": "deterministic",
                  "created_at": datetime.now(timezone.utc).isoformat(), "document_id": parent["document_id"] if parent else request.id,
                  "revision_number": parent["revision_number"] + 1 if parent else 1, "parent_report_id": request.parent_report_id,
                  "title": request.title, "text": request.text, "source_fingerprint": request.source_fingerprint,
                  **selected, "limitations": snapshot["limitations"]}
        # Detect source writes during projection/validation too. Source writers
        # do not share the report lock, so this is optimistic snapshot control.
        if build_manual_report_draft(run_root)["source_fingerprint"] != request.source_fingerprint:
            raise _error("MANUAL_REPORT_SOURCE_CHANGED", "Evidence changed while saving the report.", 409)
        payload = {"schema_version": "workbench-manual-report/v1", "record": record}
        write_json(path, payload)
        _register_report(run_root, path, request.id)
        return payload


def _register_report(run_root: Path, path: Path, report_id: str) -> None:
    artifact_id = f"manual_report_{report_id}"
    entries = [entry for entry in _read_artifacts_index(run_root).get("artifacts", [])
               if entry.get("artifact_id") == artifact_id]
    if not entries:
        register_artifact(run_root, artifact_id, path, "manual_report", "reporting", [])
    elif len(entries) != 1 or entries[0].get("sha256") != sha256_file(path):
        raise _error("MANUAL_REPORT_CONFLICT", "Stored report registration differs from the immutable revision.", 409)


def export_manual_report(run_root: Path, report_id: str, format: str) -> tuple[bytes, str, str]:
    record = _read_report(run_root, report_id)["record"]
    by_id = {fact["id"]: fact for fact in record["facts"]}
    # The text's own heading is the title when it starts with one.
    body = render_values(record["text"], by_id)
    markdown = body if body.lstrip().startswith("# ") else f"# {record['title']}\n\n{body}"
    # The appendix lists the facts the text shows, with their exact stored
    # values and sources; the rest of the selected evidence is counted.
    shown_ids, _unknown = resolved_ids(record["text"], by_id)
    cited = list(dict.fromkeys(shown_ids + [m.group(1) for m in re.finditer(r"\[\[c:([^\]]+)\]\]", record["text"])]))
    shown = [by_id[fact_id] for fact_id in cited if fact_id in by_id]
    markdown += "\n\n## Evidence behind the numbers\n\n"
    markdown += "\n".join(
        f"- {fact['label']}: {fact['value']!r} ({fact['source']['result_ref']}; {fact['id']})" for fact in shown
    ) or "- The text shows no computed values."
    if len(record["facts"]) > len(shown):
        markdown += f"\n\n{len(record['facts']) - len(shown)} further computed facts were selected as evidence and are kept with this revision."
    markdown += "\n\n" + "\n".join(f"[[fig:{f['artifact_id']}]]" for f in record["figures"])
    markdown += "\n\n## Evidence limits\n\n" + "\n".join(f"- {item}" for item in record["limitations"])
    settings = analysis_disclosure.read_settings(run_root.parent.parent)
    if settings["include_in_exports"]:
        markdown += "\n\n" + analysis_disclosure.markdown(
            analysis_disclosure.disclosure(run_root.parent.parent, run_root.name), detail=settings["detail"])
    # Pin actual bytes before invoking the existing renderer. A concurrent
    # file replacement cannot change a figure between hash check and export.
    entries = _read_artifacts_index(run_root).get("artifacts", [])
    with TemporaryDirectory(prefix="workbench-manual-report-") as temp:
        export_root = Path(temp)
        pinned = []
        for figure in record["figures"]:
            matches = [item for item in entries if item.get("artifact_id") == figure["artifact_id"] and item.get("artifact_type") == "figure"]
            if len(matches) != 1:
                raise _error("MANUAL_REPORT_SOURCE_CHANGED", "Report figure is no longer uniquely registered.", 409)
            source = _inside(run_root, str(matches[0]["path"]))
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != figure["sha256"]:
                raise _error("MANUAL_REPORT_SOURCE_CHANGED", "Report figure bytes changed since this revision was saved.", 409)
            target = export_root / f"{figure['artifact_id']}{source.suffix}"
            target.write_bytes(data)
            pinned.append({"artifact_id": figure["artifact_id"], "artifact_type": "figure", "path": target.name})
        write_json(export_root / "artifacts_index.json", {"artifacts": pinned})
        return export_report(export_root, markdown=markdown, figures=record["figures"], format=format)
