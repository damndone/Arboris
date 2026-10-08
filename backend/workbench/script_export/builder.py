"""Build an export from a closed path of completed, registered owner artifacts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import re
import pandas as pd
from scipy import stats
from types import MappingProxyType
from collections.abc import Mapping
from contextlib import ExitStack
import os
import stat

from ..artifacts import read_json
from ..lineage.rerun_provenance import dataset_source
from ..jsonl_store import read_jsonl
from ..agent.workflow import WorkflowStep, WorkflowStepResult, WorkflowExecutionError
from ..agent.postestimation_steps import _resolve_model_binding
from ..config import load_config
from ..contracts.model.inference_kernel import kernel_relative_path, validate_inference_kernel
from ..contracts.model.result_envelope_registry import declaration_for
from ..contracts.model.script_inputs import SCRIPT_INPUT_OPTION_BINDINGS
from ..contracts.model.script_results import SCRIPT_RESULT_LAYOUTS, DEFAULT_SCRIPT_RESULT_LAYOUT
from ..data_operation_registry import get_data_operation
from ..data_operations import (_coerce_to_dtype, _schema_fingerprint, _schema_sidecar_path,
                               DataColumnCastSpecV1, DataColumnsCastSpecV1, DataCastItem)
from ..graph_store import GraphStore
from ..identity.root import open_validated_project_root
from ..ingestion import _read_frame as read_ingested_frame
from ..lineage.hashing import dag_hash
from ..postestimation.comparison_data import _bound_bytes, assert_completed_kernel, assert_lr_comparable
from ..postestimation.estimation_data import estimation_design
from ..postestimation.registry import OPERATIONS, run_operation
from ..predictive_research.contracts import FeatureRecipeV1
from ..predictive_research.feature_recipe import apply_feature_recipe
from ..services.server_run_artifacts import read_server_owned_run_artifacts
from ..survey.fields import DESIGN_FIELDS
from ..tabular_io import read_table
from .plan import ScriptPlan, ScriptSource, ScriptStep, ScriptSnapshot, ScriptExportRefusal
from .result_snapshot import result_snapshot_binding, validate_result_snapshot, RESULT_SNAPSHOT_CONTRACT
from .storage import _directory, _same

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")


def refuse(message):
    raise ScriptExportRefusal("EXPORT_PROVENANCE_UNAVAILABLE", message)


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _columns(value):
    if isinstance(value, str):
        value = json.loads(value) if value.lstrip().startswith('[') else [item.strip() for item in value.split(',') if item.strip()]
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) or not item for item in value):
        refuse("Completed input has an invalid column list")
    return list(value)


def _numeric_paths(value, path=()):
    """Full-precision completed values keep their document-role JSON pointers."""
    if isinstance(value, Mapping):
        for key,item in value.items():
            yield from _numeric_paths(item,(*path,str(key)))
    elif isinstance(value,(list,tuple)):
        for index,item in enumerate(value):
            yield from _numeric_paths(item,(*path,str(index)))
    elif type(value) in (int,float) and math.isfinite(value):
        yield '/'+'/'.join(part.replace('~','~0').replace('/','~1') for part in path),value


class _VerifiedSource(io.BytesIO):
    """The unchanged ingestion parser reads only the already verified bytes."""
    def __init__(self, raw, filename):
        super().__init__(raw)
        self.name = Path(filename).name
        self.suffix = Path(filename).suffix


def _schema_bytes(project, run_id, relative):
    """Read the optional sidecar through held, admitted owner directory FDs."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(part in {'.','..'} for part in parts):
        refuse('Invalid owner schema path')
    try:
        with open_validated_project_root(project) as admission, ExitStack() as stack:
            parents = []
            def directory(parent,name):
                fd = _directory(parent,name)
                stack.callback(os.close,fd)
                parents.append((parent,name,fd))
                return fd
            owner = directory(directory(admission.fd,'runs'),run_id)
            parent = owner
            for name in parts[:-1]:
                parent = directory(parent,name)
            try:
                fd = os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            except FileNotFoundError:
                raw = None
            else:
                with os.fdopen(fd,'rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        refuse('Data schema must be a singly linked regular file')
                    raw = stream.read()
            for parent,name,bound in parents:
                _same(parent,name,bound)
            return raw
    except ScriptExportRefusal:
        raise
    except (OSError,ValueError) as exc:
        raise ScriptExportRefusal('EXPORT_PROVENANCE_UNAVAILABLE','Data schema cannot be read through its admitted owner directory') from exc


@dataclass(frozen=True)
class BuiltScriptPlan:
    plan: ScriptPlan
    files: Mapping[str, bytes]
    result_sidecars: Mapping[str, tuple[str, bytes]]
    source_columns: tuple[str, ...]


def _kernel_values(kernel):
    coefficients = dict(zip(kernel['param_names'], kernel['params']))
    errors = {name: math.sqrt(kernel['vcov'][i][i]) for i,name in enumerate(kernel['param_names'])}
    distribution = kernel['reference_distribution']
    df = kernel['df_resid'] if distribution == 't' else None
    if distribution == 't' and (df is None or df <= 0):
        refuse('Completed model has no positive reference degrees of freedom')
    statistics = {}
    for name,estimate in coefficients.items():
        value = estimate/errors[name] if errors[name] > 0 else None
        if value is not None and not math.isfinite(value):
            value = None
        p = None if value is None else float(2*(stats.t.sf(abs(value),df) if distribution == 't' else stats.norm.sf(abs(value))))
        statistics[name] = dict(value=value,df=df,df_denominator=None,p_value=p,distribution=distribution)
    return {'nobs':kernel['nobs'],'coefficients':coefficients,'std_errors':errors,'statistics':statistics}


def _post_values(payload):
    result = payload["result"]
    values = {"nobs": result.get("nobs"), "coefficients": {}, "std_errors": {}, "statistics": {}}
    if "effects" in result:
        for effect in result["effects"]:
            name = effect["variable"]
            values["coefficients"][name] = effect["estimate"]
            values["std_errors"][name] = effect["std_error"]
            values["statistics"][name] = {"value": effect["statistic"], "df": result.get("df"),
                "df_denominator": None, "p_value": effect["p_value"], "distribution": result["distribution"]}
    elif "estimate" in result:
        values["coefficients"]["estimate"] = result["estimate"]
        values["std_errors"]["estimate"] = result["std_error"]
    if "statistic" in result:
        values["statistics"]["test"] = {"value": result["statistic"], "df": result.get("df_num", result.get("df")),
            "df_denominator": result.get("df_den"), "p_value": result.get("p_value"), "distribution": result.get("distribution")}
    return values


class _Builder:
    def __init__(self, project, run_id):
        self.project = Path(project).resolve()
        self.run_id = run_id
        self.owners = {}; self.steps = []; self.sources = []; self.files = {}; self.frames = {}
        self.done = {}; self.active = set(); self.provenance = []; self.result_sources = {}; self.result_documents = {}; self.kernels = {}
        self.source_columns = set()

    def owner(self, run_id):
        if run_id in self.owners:
            return self.owners[run_id]
        if len(self.owners) >= 64 or not isinstance(run_id, str) or _ID.fullmatch(run_id) is None:
            refuse("Invalid or excessive owner run identities")
        root = (self.project / "runs" / run_id).resolve()
        if root.parent != (self.project / "runs").resolve():
            refuse("Owner run escapes project")
        manifest = read_json(root / "run_manifest.json")
        if manifest.get("run_id") != run_id or manifest.get("status") != "completed":
            refuse("Script export requires an identified completed owner run")
        records = read_server_owned_run_artifacts(self.project, run_id, required=True)
        for field in ("artifact_id", "path"):
            identities = [item.get(field) for item in records]
            if any(not isinstance(item, str) or not item for item in identities) or len(identities) != len(set(identities)):
                refuse("Duplicate or missing registered artifact identity")
        inputs = read_json(root / "run_inputs.json")
        if inputs.get("run_input_schema_version") != 1 or inputs.get("dag_hash") != dag_hash(inputs["upload"]["sha256"], inputs["form"]):
            refuse("Executed inputs do not match the recorded input hash")
        graph = GraphStore(self.project / "runs").read(run_id)
        if graph.run_id != run_id or not graph.nodes or graph.legacy:
            refuse("Owner has no complete executable lineage graph")
        # The artifact index is verified by the owner reader. Only consumed
        # records enter the path digest: registering an unrelated export must
        # not change the same completed analysis path's identity.
        for filename in ("run_manifest.json", "run_inputs.json", "graph.json"):
            self.provenance.append([run_id, filename, _digest((root / filename).read_bytes())])
        self.owners[run_id] = root, records, inputs, graph
        return self.owners[run_id]

    def record(self, run_id, *, path=None, artifact_id=None):
        root, records, _, _ = self.owner(run_id)
        matches = [item for item in records if (path is None or item["path"] == path) and (artifact_id is None or item["artifact_id"] == artifact_id)]
        if len(matches) != 1:
            refuse("Artifact has no unique recorded owner")
        record = matches[0]; raw = _bound_bytes(root, root / record["path"])
        self.provenance.append([run_id, record["artifact_id"], record["path"], _digest(raw)])
        return record, raw

    def frame(self, run_id, path):
        root = self.owner(run_id)[0]
        _, raw = self.record(run_id, path=path)
        frame = read_table(io.BytesIO(raw), suffix=Path(path).suffix)
        sidecar = _schema_sidecar_path(root / path)
        schema_raw = _schema_bytes(self.project,run_id,sidecar.relative_to(root).as_posix())
        if schema_raw is not None:
            schema = json.loads(schema_raw)
            if not isinstance(schema.get("dtypes"), dict) or set(schema["dtypes"]) != set(frame.columns):
                refuse("Incomplete data schema sidecar")
            for name,dtype in schema['dtypes'].items():
                frame[name] = _coerce_to_dtype(frame[name],str(dtype))
            if any(str(frame[name].dtype) != dtype for name, dtype in schema["dtypes"].items()):
                refuse("Data schema conversion cannot be reproduced")
            self.provenance.append([run_id, sidecar.relative_to(root).as_posix(), _digest(schema_raw)])
        return frame

    def step_id(self, run_id, node_id):
        return "step_" + _digest(_json_bytes([run_id, node_id]))[:24]

    def assert_source(self, run_id, node_id, artifact_id, digest):
        record, raw = self.record(run_id, artifact_id=artifact_id)
        node = self.owner(run_id)[3].nodes.get(node_id)
        if node is None or node.payload_ref != record["path"] or digest != _digest(raw):
            refuse("Recipe source artifact or SHA differs from its executed graph binding")

    def snapshot(self, step_id, frame):
        name = step_id + ".csv"
        raw = frame.to_csv(index=False, float_format="%.17g").encode()
        self.files[name] = raw
        return ScriptSnapshot(name, "csv", _digest(raw), len(frame), tuple(map(str, frame.columns)))

    def append_data(self, run_id, node_id, operation, parameters, inputs, frame, label):
        step_id = self.step_id(run_id, node_id)
        self.steps.append(ScriptStep(step_id, "data_operation", operation, parameters, tuple(inputs), output_dataset=step_id,
            expected={"nrows": len(frame), "columns": list(map(str, frame.columns))}, snapshot=self.snapshot(step_id, frame), label=label))
        self.frames[step_id] = frame
        return step_id

    def dataset(self, run_id, node_id):
        key = (run_id, node_id)
        if key in self.done:
            return self.done[key]
        if key in self.active or len(self.active) >= 256:
            refuse("Lineage contains a cycle or exceeds the path budget")
        self.active.add(key)
        root, _, inputs, graph = self.owner(run_id)
        node = graph.nodes.get(node_id)
        if node is None or str(node.kind.value) != "dataset_stage":
            refuse("Lineage input is not an owned dataset node")
        if node_id == "stage:raw":
            raw_records = [item for item in self.owner(run_id)[1] if item["artifact_type"] == "raw_data"]
            if len(raw_records) != 1:
                refuse("Export requires an explicitly bound single source file")
            record, raw = self.record(run_id, artifact_id=raw_records[0]["artifact_id"])
            if _digest(raw) != inputs["upload"]["sha256"]:
                refuse("Original upload SHA differs from the recorded source")
            bridge = dataset_source(inputs)
            if bridge:
                ancestor = self.dataset(bridge["source_run_id"], bridge["op_node_id"])
                source_record, source_raw = self.record(bridge["source_run_id"], artifact_id=bridge["source_artifact_id"])
                source_node = self.owner(bridge["source_run_id"])[3].nodes[bridge["op_node_id"]]
                if source_node.payload_ref != source_record["path"] or source_raw != raw:
                    refuse("Dispatched model upload does not match its source lineage")
                result = ancestor
            elif inputs.get("rerun_of"):
                # A rerun re-executes its parent's upload, byte for byte, so its
                # raw data is the parent's source, wherever that came from.
                parent = inputs["rerun_of"]
                if (self.owner(parent)[2].get("upload") or {}).get("sha256") != inputs["upload"]["sha256"]:
                    refuse("Cross-run source lineage is incomplete")
                result = self.dataset(parent, "stage:raw")
            else:
                if inputs.get("from_node"):
                    refuse("Cross-run source lineage is incomplete")
                fmt = Path(record["path"]).suffix.removeprefix(".").lower()
                name = "source_" + _digest(raw)[:24] + "." + fmt
                result = "source_" + _digest(_json_bytes(key))[:24]
                options = {"sheet_name": inputs["form"]["sheet_name"]} if fmt == "xlsx" and inputs["form"].get("sheet_name") else {}
                if inputs["form"].get("transpose") in (True, "true"):
                    options["transpose"] = True
                self.sources.append(ScriptSource(result, fmt, name, _digest(raw), options))
                self.files[name] = raw
                self.frames[result] = read_ingested_frame(_VerifiedSource(raw, record['path']), load_config(self.project / "config.yml"), options.get("sheet_name"), options.get("transpose", False))
                self.source_columns.update(map(str, self.frames[result].columns))
                if fmt == "xlsx":
                    # The bundle retains the entire original workbook, including
                    # sheets that did not participate in model fitting.
                    with pd.ExcelFile(io.BytesIO(raw)) as workbook:
                        for sheet in workbook.sheet_names:
                            self.source_columns.update(map(str, pd.read_excel(workbook, sheet_name=sheet, nrows=0).columns))
        elif node_id == "stage:cleaned":
            parent = self.dataset(run_id, "stage:raw")
            frame = self.frame(run_id, node.payload_ref)
            _, raw = self.record(run_id, artifact_id="cleaning_actions")
            actions = json.loads(raw)["actions"]
            identity = self.frames[parent].reset_index(drop=True).equals(frame.reset_index(drop=True))
            result = self.append_data(run_id, node_id, "data.cleaning", {"actions": actions, "identity": identity}, [parent], frame, "Recorded cleaning and source normalization")
        else:
            annotations = [item for item in node.annotations if item.get("type") == "data_operation"]
            if len(annotations) != 1 or not node.parent_stage_id:
                refuse("Dataset transformation has no unambiguous executed recipe")
            annotation = annotations[0]
            parent = self.dataset(run_id, node.parent_stage_id)
            record, raw = self.record(run_id, path=annotation["recipe_path"])
            recipe = json.loads(raw); output_record, output_raw = self.record(run_id, path=node.payload_ref)
            if any(recipe["result"].get(key) != value for key, value in
                   {"artifact_id": output_record["artifact_id"], "path": node.payload_ref}.items()):
                refuse("Recipe does not own the selected dataset output")
            frame = self.frame(run_id, node.payload_ref)
            if annotation.get("schema_fingerprint") != _schema_fingerprint(frame):
                refuse("Transformation schema fingerprint changed")
            if recipe.get("payload_schema") == "workbench.data-operation":
                spec = recipe["spec"]; operation = spec["operation_id"]
                declaration = get_data_operation(operation)
                if declaration is None:
                    refuse("Transformation operation is not declared")
                if spec["source_run_id"] != run_id or spec["source_node_id"] != node.parent_stage_id:
                    refuse("Transformation recipe source identity differs from its graph")
                self.assert_source(run_id, node.parent_stage_id, spec["source_artifact_id"], recipe["preview"]["source_sha256"])
                parameters = spec["parameters"]; dependency = [parent]
                if declaration.secondary_input:
                    secondary = self.dataset(spec["secondary_run_id"], spec["secondary_node_id"])
                    self.assert_source(spec["secondary_run_id"], spec["secondary_node_id"], spec["secondary_artifact_id"], recipe["preview"]["secondary_source_sha256"])
                    dependency.append(secondary)
                if recipe["preview"]["schema_fingerprint_before"] != _schema_fingerprint(self.frames[parent]) or recipe["preview"]["schema_fingerprint_after"] != _schema_fingerprint(frame):
                    refuse("Recipe schema fingerprint changed")
            elif recipe.get("payload_schema") == "workbench.prediction.feature-recipe":
                parameters = {key: recipe[key] for key in FeatureRecipeV1.__dataclass_fields__}
                feature = FeatureRecipeV1(**parameters)
                feature.validate()
                if feature.lineage_parent != node.parent_stage_id or feature.to_dict() != annotation.get("typed_payload"):
                    refuse("Feature recipe differs from its executed graph binding")
                self.assert_source(run_id, node.parent_stage_id, feature.source_artifact, recipe["source_sha256"])
                reproduced_frame = apply_feature_recipe(self.frames[parent], feature)
                # Compare the producer's exact CSV serialization rather than
                # reparsed floating-point bits, which pandas may round on read.
                if reproduced_frame.to_csv(index=False).encode() != output_raw:
                    refuse("Feature output disagrees with its recorded executed arithmetic")
                parameters["native_inputs_numeric"] = all(pd.api.types.is_numeric_dtype(self.frames[parent][name]) for name in feature.inputs)
                operation = "data.feature_recipe"; dependency = [parent]
            elif recipe.get("schema_version") in {"data-column-cast.v1", "data-columns-cast.v1"}:
                spec = recipe["spec"]
                operation = "data.column.cast" if recipe["schema_version"] == "data-column-cast.v1" else "data.columns.cast"
                if spec.get("operation_id") != operation or annotation.get("operation_id") != operation:
                    refuse("Cast operation differs from its recorded schema")
                if operation == "data.column.cast":
                    typed = DataColumnCastSpecV1(**spec)
                    parameters = {"column": typed.column, "target_dtype": typed.target_dtype}
                else:
                    values = dict(spec); values["casts"] = tuple(DataCastItem(**item) for item in values["casts"])
                    typed = DataColumnsCastSpecV1(**values)
                    if list(annotation["casts"]) != spec["casts"] or recipe["casts"] != spec["casts"]:
                        refuse("Batch cast declarations changed")
                    parameters = {"casts": spec["casts"], "output_format": typed.output_format}
                if typed.source_run_id != run_id or typed.source_node_id != node.parent_stage_id:
                    refuse("Cast source differs from its graph parent")
                self.assert_source(run_id, node.parent_stage_id, typed.source_artifact_id, recipe["source"]["sha256"])
                preview = recipe["preview"]
                if (preview["schema_fingerprint_before"] != _schema_fingerprint(self.frames[parent])
                        or preview["schema_fingerprint_after"] != _schema_fingerprint(frame)
                        or recipe["result"]["schema_fingerprint"] != _schema_fingerprint(frame)
                        or preview["status"] != "ready"):
                    refuse("Completed cast schema or preview changed")
                dependency = [parent]
            else:
                refuse("Transformation recipe has no validated export provenance adapter")
            result = self.append_data(run_id, node_id, operation, parameters, dependency, frame, node.display_label)
        self.active.remove(key); self.done[key] = result
        return result

    def model(self, run_id, node_id):
        key = (run_id, node_id)
        if key in self.done:
            return self.done[key]
        root, _, inputs, graph = self.owner(run_id)
        node = graph.nodes.get(node_id)
        if node is None or node.kind.value != "model" or not node.payload_ref:
            refuse("Target is not a materialized owned model")
        if any(item.get("rerun_required") for item in node.annotations):
            refuse("Selected model requires a rerun after its data changed")
        record, packet_raw = self.record(run_id, path=node.payload_ref)
        packet = json.loads(packet_raw)
        model_id = node_id.removeprefix("model:")
        kernel_record, raw = self.record(run_id, path=kernel_relative_path(model_id))
        kernel = json.loads(raw); validate_inference_kernel(kernel)
        if kernel["model_id"] != model_id:
            refuse("Inference kernel model identity differs from its owner")
        assert_completed_kernel(root, kernel)
        layout = SCRIPT_RESULT_LAYOUTS.get(kernel['model_type'], DEFAULT_SCRIPT_RESULT_LAYOUT)
        declaration = declaration_for(kernel['model_type'])
        documents = {'packet': (record,packet_raw), 'kernel':(kernel_record,raw)}
        if record['artifact_id'] != model_id+layout.artifact_suffix:
            refuse('Model graph and registered artifact identity disagree')
        original_packet = packet
        if layout.packet_adapter:
            try:
                packet = layout.packet_adapter(packet,kernel,model_id,run_id)
            except (ValueError,KeyError,TypeError) as exc:
                raise ScriptExportRefusal('EXPORT_PROVENANCE_UNAVAILABLE','Completed typed result layout is invalid') from exc
        if packet.get("model_id") != model_id or packet.get("nobs") != kernel["nobs"]:
            refuse("Model result and inference kernel identity or sample size disagree")
        _, diagnostic_raw = self.record(run_id, path="diagnostic_summary.json")
        identity = json.loads(diagnostic_raw)["model_identity"]
        diagnostic_record,_ = self.record(run_id,path="diagnostic_summary.json")
        documents['diagnostic_summary'] = diagnostic_record,diagnostic_raw
        if declaration and declaration.evidence_document:
            documents['evidence'] = self.record(run_id,path=declaration.evidence_document)
        if declaration:
            for role,path in declaration.sidecars.items():
                documents['sidecar:'+role] = self.record(run_id,path=path)
        if layout.reference_field:
            references = original_packet.get(layout.reference_field)
            if not isinstance(references,dict):refuse('Completed result references are missing')
            for role,path in references.items():
                if not isinstance(role,str) or not isinstance(path,str):refuse('Invalid completed document reference')
                if path.endswith('.json'):
                    if role in documents:refuse('Duplicate completed document role')
                    referenced = self.record(run_id,path=path,artifact_id=role)
                    value = json.loads(referenced[1])
                    if value.get('artifact_id') != role or value.get('metadata',{}).get('run_id') != run_id:
                        refuse('Referenced completed document belongs to a different role or owner')
                    documents[role] = referenced
        if layout.completed_document_validator:
            try:
                layout.completed_document_validator(original_packet,
                    {role:json.loads(document[1]) for role,document in documents.items()})
            except (ValueError,KeyError,TypeError) as exc:
                raise ScriptExportRefusal('EXPORT_PROVENANCE_UNAVAILABLE',
                    'Completed result documents disagree with their primary projection') from exc
        executed = inputs.get("executed_payload")
        form = inputs["form"]
        if executed is None and form.get("model_type") == kernel["model_type"]:
            # Older completed handlers leave the explicit requested identity in
            # the sealed inputs rather than a second terminal payload. Require
            # exact identity; never guess the resolved family of an auto run.
            executed = {"model_type": form["model_type"], "model_options": form.get("model_options") or {}}
        if not isinstance(executed, dict):
            refuse("Model has no compatible actual executed parameter record")
        options = dict(executed.get("model_options") or {})
        base, separator, qualifier = kernel["model_type"].partition(":")
        if separator and form.get("model_type") == kernel["model_type"] and "family" not in options:
            options["family"] = qualifier
        actual_type = executed.get("model_type")
        if actual_type != kernel["model_type"] and not (
                separator and actual_type == base and options.get("family") == qualifier):
            refuse("Model has no compatible actual executed parameter record")
        if separator and options.get("family") != qualifier:
            refuse("Executed family qualifier differs from its inference kernel")
        for field, option in SCRIPT_INPUT_OPTION_BINDINGS.get(kernel['model_type'], {}).items():
            value = _columns(form.get(field, []))
            if not value or option in options and _columns(options[option]) != value:
                refuse("Completed model role fields disagree or are missing")
            options[option] = value
        source = self.dataset(run_id, "stage:cleaned")
        y = identity["y_variable"]; x = identity["x_variables"]
        if executed.get("y", y) != y or executed.get("x", x) != x:
            refuse("Executed response or regressors disagree with the owner identity")
        if layout.completed_input_validator:
            try:
                layout.completed_input_validator(original_packet,kernel,self.frames[source],form,y,x,options)
            except (ValueError,KeyError,TypeError) as exc:
                raise ScriptExportRefusal('EXPORT_PROVENANCE_UNAVAILABLE',
                    'Completed result differs from its executed input or internal projection') from exc
        coefficients = packet.get('coefficients')
        positions = list(enumerate(kernel['param_names']))
        if layout.coefficient_records:
            try:
                coefficients = layout.coefficient_records(original_packet,kernel,self.frames[source],form,y,x)
            except (ValueError,KeyError,TypeError) as exc:
                raise ScriptExportRefusal('EXPORT_PROVENANCE_UNAVAILABLE','Completed public coefficient projection is invalid') from exc
            positions = [(kernel['param_names'].index(name),name) for name in coefficients]
        if coefficients is None and layout.empty_coefficients and not kernel['param_names']:
            coefficients = {}
        if not isinstance(coefficients,dict):refuse('Completed model needs a declared coefficient-record adapter')
        for position,name in positions:
            entry = coefficients.get(name)
            if not isinstance(entry,dict) or entry.get('estimate') is None or entry.get('std_error') is None:
                refuse('Every kernel parameter requires a completed result estimate and standard error')
            if float(entry['estimate']) != kernel['params'][position]:
                refuse('Model coefficient and inference kernel disagree')
            if not math.isclose(float(entry['std_error']),math.sqrt(kernel['vcov'][position][position]),
                    rel_tol=16*math.ulp(1.0),abs_tol=0.0):
                refuse('Model standard error and inference kernel disagree')
        evidence = packet.get('covariance_evidence') or {}
        covariance = executed.get("covariance") or packet.get('covariance') or form.get('covariance') or None
        if covariance is None:
            if kernel["covariance_estimator"] in {"nonrobust", "unadjusted"}:
                covariance = "unadjusted"
            elif kernel['covariance_estimator'] is not None:
                refuse("Executed covariance cannot be proved from the owner record")
        labels = {'unadjusted': {'nonrobust','unadjusted'}, 'robust': {'robust','HC1'},
                  'clustered': {'cluster','clustered'}, 'hac': {'HAC'}}
        if not isinstance(packet.get('survey_design'), dict) and covariance is not None:
            if kernel['covariance_estimator'] not in labels.get(covariance, set()):
                refuse("Executed covariance input disagrees with its actual inference kernel")
        cluster = options.get('cluster') or executed.get('entity_col') or form.get('entity_col') or None
        if covariance == 'clustered' and evidence:
            if (evidence.get('cluster_variable') != cluster or evidence.get('cluster_count') != kernel['n_clusters']
                    or evidence.get('inference_distribution') != kernel['reference_distribution']
                    or evidence.get('effective_df') != kernel['df_resid']):
                refuse("Executed clustering evidence disagrees with the inference kernel or input column")
        parameters = {"model_type": kernel["model_type"], "y": y, "x": x,
            "categorical_x": _columns(form.get("categorical_x") or []), "covariance": covariance,
            "cluster": cluster, "entity": executed.get("entity_col") or form.get("entity_col") or None,
            "time": form.get("time_col") or None, "hac_lags": form.get("hac_lags") or None,
            "weights": None, "model_options": options}
        if form.get("weights") or form.get("weight_col"):
            refuse("Weight provenance requires an explicit executed weight adapter")
        weight = packet.get("weights")
        requested = [(kind, form.get(kind + "_weight")) for kind in ("frequency", "analysis", "sampling")
                     if form.get(kind + "_weight")]
        if requested:
            if (len(requested) != 1 or not isinstance(weight, dict) or weight.get("executed") is not True
                    or (weight.get("kind"), weight.get("column")) != requested[0]
                    or kernel.get("weights") != weight["kind"]):
                refuse("Executed weight packet, inputs and inference kernel disagree")
            parameters["weights"] = {"kind": weight["kind"], "column": weight["column"]}
        elif (isinstance(weight, dict) and weight.get("executed") is not False
                or kernel.get("weights") not in (None, "none")):
            refuse("Executed weights have no declared input column")
        survey = packet.get("survey_design")
        if isinstance(survey, dict):
            if not parameters["weights"] or parameters["weights"]["kind"] != "sampling":
                refuse("Executed survey design has no sampling weight binding")
            method = survey["variance_method"]
            if kernel["covariance_estimator"] != "survey_design_" + method or kernel["df_method"] != survey["df_convention"]:
                refuse("Executed design variance and inference kernel disagree")
            design = {key: form[key] for key in DESIGN_FIELDS if form.get(key) not in (None, "", [])}
            fields = {"survey_strata_col": "strata_column", "survey_psu_col": "psu_column",
                      "survey_subpop": "subpopulation"}
            for field, result_field in fields.items():
                if (form.get(field) or None) != (survey.get(result_field) or None):
                    refuse("Executed survey design differs from its input declaration")
            if (form.get("survey_fpc_col") or None) != ((survey.get("fpc") or {}).get("column")):
                refuse("Executed FPC differs from its input declaration")
            if survey["weight_column"] != parameters["weights"]["column"]:
                refuse("Executed survey weight column changed")
            design.update(sampling_weight=survey["weight_column"], survey_method=method,
                          survey_df=survey["df_convention"], survey_lonely_psu=survey["lonely_psu_policy"])
            options["survey_design"] = design
            parameters["covariance"] = "survey_design"
        if layout.input_preparer:
            try:
                prepared = layout.input_preparer(self.frames[source],form,y)
            except (ValueError,KeyError,TypeError) as exc:
                raise ScriptExportRefusal('EXPORT_PROVENANCE_UNAVAILABLE','Executed estimator preparation cannot be reproduced') from exc
            preparation_parameters={'executed_form_sha256':_digest(_json_bytes(form))}
            if layout.input_parameters:
                preparation_parameters.update(layout.input_parameters(self.frames[source],form,y))
            source = self.append_data(run_id,node_id+':estimation-input','data.estimation_input',
                preparation_parameters,[source],prepared,'Executed estimator input normalization')
        values = _kernel_values(kernel)
        if layout.snapshot_numbers:
            selections = {}
            evidence_document = json.loads(documents.get('evidence',documents['packet'])[1])
            if declaration:
                for field in declaration.fields:
                    document = json.loads(documents['sidecar:'+field.sidecar][1]) if field.sidecar else evidence_document
                    value = document.get(field.source_key)
                    if field.nested_key and isinstance(value,dict):value = value.get(field.nested_key)
                    selections['declared:'+field.key] = value
            for role in layout.numeric_document_roles:
                if role not in documents:refuse('Required numerical document role is missing')
                selections[role] = json.loads(documents[role][1])
            for pointer,value in _numeric_paths(selections):
                values['statistics']['completed:'+pointer] = dict(value=value,df=None,df_denominator=None,p_value=None,distribution=None)
            if values['nobs'] is None and layout.packet_adapter:
                # A forecast sample size belongs to its typed result, even
                # when it has no regression inference kernel.
                result = original_packet.get('result',{})
                if type(result.get('n_obs')) is int:values['nobs'] = result['n_obs']
        step_id = self.step_id(run_id, node_id)
        self.result_documents[step_id] = documents
        self.steps.append(ScriptStep(step_id, "model", "model." + kernel["model_type"], parameters, (source,),
            expected=values, snapshot=self.snapshot(step_id, self.frames[source]), label=node.display_label))
        self.frames[step_id] = self.frames[source]
        self.result_sources[step_id] = (kernel_record, raw, "workbench.inference_kernel/v1", lambda artifact,values=values:values)
        self.kernels[step_id] = kernel
        self.done[key] = step_id
        return step_id

    def build(self, target):
        if not isinstance(target, str) or _ID.fullmatch(target) is None:
            refuse("Invalid export target identity")
        if target.startswith("model:"):
            self.model(self.run_id, target)
        elif target.startswith("artifact:"):
            self.postestimation(target.removeprefix("artifact:"))
        else:
            refuse("Export target requires a recorded model or post-estimation binding")
        lineage_hash = _digest(_json_bytes(self.provenance))
        plan = ScriptPlan(self.project.name, self.run_id, tuple(self.sources), tuple(self.steps), "1.8.11", lineage_hash)
        sidecars = {}
        for step in self.steps:
            if step.step_id not in self.result_sources:
                continue
            record, raw, contract, projector = self.result_sources[step.step_id]
            binding = result_snapshot_binding(plan, step)
            payload = {"contract": RESULT_SNAPSHOT_CONTRACT, "schema_version": 1, "binding": binding,
                "source": {"artifact_id": record["artifact_id"], "artifact_sha256": _digest(raw), "result_contract": contract},
                "values": projector(json.loads(raw))}
            if step.step_id in self.result_documents:
                payload['documents'] = {}
                for role,(document_record,document_raw) in self.result_documents[step.step_id].items():
                    filename = 'result_'+_digest(_json_bytes([step.step_id,role]))[:24]+'.json'
                    self.files[filename] = document_raw
                    payload['documents'][role] = {'artifact_id':document_record['artifact_id'],
                        'filename':filename,'sha256':_digest(document_raw)}
            validate_result_snapshot(payload, expected_binding=binding)
            sidecars[step.step_id] = (step.step_id + ".json", _json_bytes(payload))
        return BuiltScriptPlan(plan, MappingProxyType(dict(self.files)), MappingProxyType(sidecars), tuple(sorted(self.source_columns)))

    def postestimation(self, artifact_id):
        record, raw = self.record(self.run_id, artifact_id=artifact_id)
        payload = json.loads(raw)
        if record["artifact_type"] != "post_estimation" or payload.get("schema_version") != "workbench.workflow.post-estimation/v1":
            refuse("Target is not a recorded workflow post-estimation result")
        source = payload["source"]; result = payload["result"]
        workflow_id = source["workflow_id"]
        if not isinstance(workflow_id, str) or _ID.fullmatch(workflow_id) is None:
            refuse("Invalid workflow identity")
        state_path = self.project / "workbench" / "workflows" / (workflow_id + ".jsonl")
        states = [item for item in read_jsonl(state_path) if item.get("record_type") == "workflow_state"]
        if not states:
            refuse("Post-estimation has no durable execution state")
        state = states[-1]; executed = state["steps"][source["workflow_step_id"]]
        if (state["workflow_id"] != workflow_id or state["status"] != "completed"
                or executed["status"] != "completed" or artifact_id not in executed["artifact_ids"]
                or executed["fingerprint"] != source["workflow_step_fingerprint"]):
            refuse("Post-estimation workflow binding is incomplete or changed")
        plan_record = payload.get("execution")
        if not isinstance(plan_record, dict):
            refuse("Legacy post-estimation lacks a retained compiled request; rerun the test before exporting")
        identity = {key: plan_record[key] for key in ("schema_version", "workflow_template", "target", "steps")}
        if "sha256:" + _digest(_json_bytes(identity)) != state["plan_fingerprint"]:
            refuse("Post-estimation compiled request differs from its durable plan fingerprint")
        fingerprints = {}; request_step = None
        for candidate in plan_record["steps"]:
            if candidate["step_id"] in fingerprints:
                refuse("Duplicate compiled workflow step identity")
            identity = {key: candidate[key] for key in ("step_id", "operation_id", "operation_version", "depends_on", "spec", "expected_artifacts")}
            identity.update(schema_version=plan_record["schema_version"],
                            dependency_fingerprints=[fingerprints[key] for key in candidate["depends_on"]])
            fingerprint = "sha256:" + _digest(_json_bytes(identity))
            if fingerprint != candidate["fingerprint"]:
                refuse("Compiled workflow step fingerprint changed")
            fingerprints[candidate["step_id"]] = fingerprint
            if candidate["step_id"] == source["workflow_step_id"]:
                request_step = candidate
        if request_step is None or request_step["fingerprint"] != executed["fingerprint"]:
            refuse("Completed test has no matching compiled request")
        if plan_record.get('workflow_id') != workflow_id or plan_record['target']['run_id'] != self.run_id:
            refuse('Compiled request belongs to a different workflow or artifact owner')
        step = WorkflowStep(**{**request_step, 'depends_on':tuple(request_step['depends_on']),
                               'expected_artifacts':tuple(request_step['expected_artifacts'])})
        previous = {}
        for dependency in step.depends_on:
            completed = state['steps'][dependency]
            if completed['status'] != 'completed' or completed['fingerprint'] != fingerprints[dependency]:
                refuse('Original model producer has no completed matching dependency state')
            previous[dependency] = WorkflowStepResult(payload={'branches':completed.get('model_branches')},
                restored_from_state=True)
        try:
            requested_root, requested_id = _resolve_model_binding(self.project,self.run_id,step,'model_ref',previous)
            if (requested_root.name,requested_id) != (source['model_run_id'],source['model_artifact_id']):
                refuse('Completed test model owner differs from its original compiled request')
            if 'restricted_model_ref' in step.spec:
                restricted_root, restricted_id = _resolve_model_binding(self.project,self.run_id,step,'restricted_model_ref',previous)
                if (restricted_root.name,restricted_id) != (result['restricted_model_run_id'],result['restricted']['model_id']):
                    refuse('Completed restricted model owner differs from its original compiled request')
        except WorkflowExecutionError as exc:
            refuse('Original compiled model binding is unavailable: '+str(exc))
        self.provenance.append(["workflow", workflow_id, _digest(state_path.read_bytes())])
        operation = result["operation"]
        if result.get("schema_version") != "workbench.postestimation.result/v1" or record["step"] != "postestimation." + operation:
            refuse("Post-estimation result operation differs from its recorded owner")
        run_id = source["model_run_id"]; model_id = source["model_artifact_id"]
        if source["run_id"] != self.run_id or result["model_run_id"] != run_id:
            refuse("Post-estimation run identity changed")
        model_step = self.model(run_id, "model:" + model_id)
        data_record, data_raw = self.record(run_id, artifact_id=source["artifact_id"])
        node = self.owner(run_id)[3].nodes.get(source["node_ref"])
        if node is None or node.payload_ref != data_record["path"] or _digest(data_raw) != source["sha256"]:
            refuse("Post-estimation analysis source differs from its executed binding")
        identity = result.get("full", result)
        if identity.get("model_id") != model_id:
            refuse("Post-estimation model identity differs from its kernel")
        parameters = {"models": [model_step]}
        fields = {"wald": ("constraints",), "lincom": ("terms", "constant"),
            "nlcom": ("expression",), "margins": ("at",), "lr": ()}
        if operation not in fields:
            refuse("Recorded post-estimation has no export parameter adapter")
        for field in fields[operation]:
            parameters[field] = result[field]
        if "level" in result:
            parameters["level"] = result["level"]
        if operation == "margins":
            parameters["variables"] = [item["variable"] for item in result["effects"]]
        if operation == "lr":
            parameters["models"].append(self.model(result["restricted_model_run_id"], "model:" + result["restricted"]["model_id"]))
            assert_lr_comparable(self.owner(run_id)[0], self.kernels[model_step],
                self.owner(result["restricted_model_run_id"])[0], self.kernels[parameters["models"][1]])
        context = {}
        if OPERATIONS[operation].needs_estimation_data:
            declaration = declaration_for(self.kernels[model_step]["model_type"])
            context = {"design": estimation_design(self.owner(run_id)[0], self.kernels[model_step]),
                "inverse_link": declaration.inverse_link if declaration is not None else None}
        if request_step["operation_id"] != "postestimation." + operation:
            refuse("Executed operation differs from its compiled request")
        reproduced = run_operation(operation, [self.kernels[key] for key in parameters["models"]], request_step["spec"], context)
        if _json_bytes(reproduced) != _json_bytes({key: result.get(key) for key in reproduced}):
            refuse("Completed post-estimation result disagrees with its current owner kernel and analysis source")
        values = _post_values(payload)
        expected = dict(values)
        if expected["nobs"] is None:
            del expected["nobs"]
        step_id = self.step_id(self.run_id, artifact_id)
        self.steps.append(ScriptStep(step_id, "postestimation", "postestimation." + operation, parameters,
            tuple(parameters["models"]), expected=expected, label="Completed " + operation))
        self.result_sources[step_id] = record, raw, "workbench.workflow.post-estimation/v1", _post_values


def build_script_plan(project_root: Path, run_id: str, target: str) -> BuiltScriptPlan:
    """Read only; callers cannot supply numbers, paths, parameters or projectors."""
    try:
        return _Builder(project_root, run_id).build(target)
    except ScriptExportRefusal:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ScriptExportRefusal("EXPORT_PROVENANCE_UNAVAILABLE", "Completed export provenance is unavailable: " + str(exc)) from exc
