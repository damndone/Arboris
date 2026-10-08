"""Post-estimation as read-only workflow steps on completed model nodes.

`postestimation.<operation>` steps read a model's persisted inference kernel
(and, for marginal effects, its estimation sample from lineage); they never
refit and never change data, so a workflow of them runs under the read-only
policy and is counted in the analysis ledger as inferential.

The step contracts are generated from the post-estimation registry, so an
operation added there with its oracle data is reachable here without another
table to remember.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..artifacts import read_json, sha256_file
from ..contracts.model.inference_kernel import (
    InferenceKernelError,
    kernel_relative_path,
    validate_inference_kernel,
)
from ..contracts.model.result_envelope_registry import declaration_for
from ..postestimation import PostestimationRefusal
from ..postestimation.estimation_data import estimation_design
from ..contracts.model.postestimation_steps import STEP_SHAPES as _STEP_SHAPES
from ..postestimation.registry import OPERATIONS, VALIDATED, run_operation

OPERATION_PREFIX = "postestimation."
DISPATCHER_KEY = "workbench.agent.workflow_runtime.postestimation"
VALIDATOR_KEY = "postestimation"
RESULT_SCHEMA = "workbench.postestimation.result/v1"

_LR_PROPOSAL_NOTES = {
    "zh": "LR 比较同一样本上嵌套模型的似然，因此要求模型方差；稳健、聚类或抽样设计方差不适用于这个 LR。你也可以选择在原模型上做 Wald 检验，保留原来的标准误口径。",
    "en": "LR compares the likelihoods of nested models on the same sample and requires model-based variance. Robust, clustered or design-based variance is unsuitable for this LR. You can instead choose a Wald test on the original model, retaining its original covariance.",
}

def _execution_error(message: str) -> Exception:
    # Imported here: the workflow module imports the step contracts, which
    # import this module.
    from .workflow import WorkflowExecutionError

    return WorkflowExecutionError(message)


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MODEL_ID = re.compile(r"^[a-z][a-z0-9_]*_\d+$")
_FOREST_KEY = re.compile(r"^[0-9a-f]{64}::")
_STEP_MODEL_REF = re.compile(r"^step:([A-Za-z0-9][A-Za-z0-9_.-]{0,63}):([A-Za-z0-9][A-Za-z0-9_.-]{0,63})$")


def model_step_reference(ref: Any) -> tuple[str, str] | None:
    """Parse an explicit plan-local reference, preserving existing model refs."""
    if not isinstance(ref, str) or not ref.startswith("step:"):
        return None
    matched = _STEP_MODEL_REF.fullmatch(ref)
    if matched is None:
        raise _execution_error("model_ref step binding must be step:<step_id>:<branch_id>")
    return matched.group(1), matched.group(2)


def bind_model_step_dependencies(step: dict, by_id: Mapping, contracts: Mapping) -> None:
    """Declare producer edges before the workflow's cycle/order validation."""
    from ..contracts.common.errors import OperationValidationError

    for field in contracts[step["operation_id"]].model_reference_fields:
        binding = model_step_reference(step["spec"].get(field))
        if binding is None:
            continue
        producer_id, branch_id = binding
        if field.replace("_ref", "_run_id") in step["spec"]:
            raise OperationValidationError("a plan-local model reference cannot also specify a model run id")
        if producer_id == step["step_id"]:
            raise OperationValidationError(f"workflow step {step['step_id']} model reference refers to itself")
        producer = by_id.get(producer_id)
        if producer is None:
            raise OperationValidationError(f"model reference refers to unknown step: {producer_id}")
        if not contracts[producer["operation_id"]].produces_model_branches:
            raise OperationValidationError(f"step {producer_id} does not produce model branches")
        branches = producer["spec"].get("branches", [])
        if not any(branch.get("branch_id") == branch_id for branch in branches):
            raise OperationValidationError(f"step {producer_id} does not declare model branch {branch_id}")
        if producer_id not in step["depends_on"]:
            step["depends_on"].append(producer_id)


def postestimation_operation_id(operation: str) -> str:
    return OPERATION_PREFIX + operation


def postestimation_step_contracts() -> dict[str, Any]:
    from .workflow_contracts import StepSpecContract

    contracts = {}
    for operation in OPERATIONS:
        summary, fields, required, types = _STEP_SHAPES[operation]
        families = sorted({family for family, op in VALIDATED if op == operation})
        contracts[postestimation_operation_id(operation)] = StepSpecContract(
            summary=(
                summary + f" Offered for: {', '.join(families)}, the families where it has been "
                "checked against a reference implementation; for any other family say it is not "
                "offered yet because that check is missing, not because the model cannot. Plan the workflow on the "
                "dataset node the model was estimated from (its parent stage, such as "
                "stage:cleaned), not on the model node; name the model in model_ref."
            ),
            fields=fields,
            required=required,
            field_types=types,
            semantic_validator_key=VALIDATOR_KEY,
            risk_class="low",
            confirmation_policy="proposal_authorization",
            output_schema_ref=RESULT_SCHEMA,
            dispatcher_key=DISPATCHER_KEY,
            effect_level="read_only",
            scope="post-estimation on a completed model",
            risk_level="none",
            reconciler_key=postestimation_operation_id(operation),
            diff_builder_key="model.post_estimation.diff.v1",
            verification_builder_key="model.post_estimation.verification.v1",
            ui_description=summary,
            # The step reads the model's kernel, not the workflow's input table.
            consumes_input_frame=False,
            model_reference_fields=tuple(name for name in fields if name.endswith("model_ref")),
            proposal_notes=_LR_PROPOSAL_NOTES if operation == "lr" else {},
        )
    return contracts


def model_id_from_ref(ref: Any) -> str:
    """`logit_1` from `model:logit_1`, `<hash>::model:logit_1` or `logit_1`."""
    if not isinstance(ref, str) or not ref.strip():
        raise _execution_error("model_ref must name a model node")
    text = _FOREST_KEY.sub("", ref.strip())
    text = text.removeprefix("model:")
    if not _MODEL_ID.fullmatch(text):
        raise _execution_error(f"model_ref {ref!r} does not name a model node such as model:logit_1")
    return text


def validate_postestimation_spec(operation_id: str, spec: Mapping[str, Any]) -> None:
    """Shape checks at plan time; the statistics are checked when the step runs."""
    from ..contracts.common.errors import OperationValidationError

    operation = operation_id.removeprefix(OPERATION_PREFIX)
    try:
        if model_step_reference(spec.get("model_ref")) is None:
            model_id_from_ref(spec.get("model_ref"))
        if "restricted_model_ref" in spec:
            if model_step_reference(spec.get("restricted_model_ref")) is None:
                model_id_from_ref(spec.get("restricted_model_ref"))
    except Exception as exc:  # noqa: BLE001 - the model_ref message is the validation message
        raise OperationValidationError(str(exc)) from exc
    for key in ("model_run_id", "restricted_model_run_id"):
        if key in spec and not (isinstance(spec[key], str) and _RUN_ID.fullmatch(spec[key])):
            raise OperationValidationError(f"{operation_id} {key} must be a run id")
    if operation == "wald" and not spec.get("constraints"):
        raise OperationValidationError("postestimation.wald needs at least one constraint")
    if operation == "lincom" and not spec.get("terms"):
        raise OperationValidationError("postestimation.lincom needs at least one weighted coefficient")
    if operation == "margins":
        variables = spec.get("variables")
        if not variables or not all(isinstance(item, str) and item for item in variables):
            raise OperationValidationError("postestimation.margins needs a list of regressor names")
        if spec.get("at", "average") not in ("average", "means"):
            raise OperationValidationError("postestimation.margins `at` must be average or means")


def _run_root(root: Path, run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise _execution_error(f"{run_id!r} is not a run id")
    run_root = root / "runs" / run_id
    if not run_root.is_dir():
        raise _execution_error(f"run {run_id} does not exist in this project")
    return run_root


def _load_kernel(run_root: Path, model_id: str) -> dict[str, Any]:
    path = run_root / kernel_relative_path(model_id)
    if not path.is_file():
        raise _execution_error(
            f"model {model_id} in run {run_root.name} has no inference kernel; it was fitted before "
            "kernels were recorded, so rerun it to use post-estimation"
        )
    kernel = read_json(path)
    try:
        validate_inference_kernel(kernel)
        if kernel.get("model_id") != model_id:
            raise InferenceKernelError("kernel identity does not match the requested model owner")
    except InferenceKernelError as exc:
        raise _execution_error(f"the inference kernel of {model_id} is not usable: {exc}") from exc
    from ..postestimation.comparison_data import assert_completed_kernel

    try:
        assert_completed_kernel(run_root, kernel)
    except (OSError, ValueError, KeyError) as exc:
        raise _execution_error(f"the model's completed kernel binding is not usable: {exc}") from exc
    return kernel


def _resolve_model_binding(root: Path, target_run_id: str, step: Any, field: str, previous: Mapping) -> tuple[Path, str]:
    binding = model_step_reference(step.spec.get(field))
    if binding is None:
        run_id = str(step.spec.get(field.replace("_ref", "_run_id")) or target_run_id)
        return _run_root(root, run_id), model_id_from_ref(step.spec.get(field))
    producer_id, branch_id = binding
    if field.replace("_ref", "_run_id") in step.spec:
        raise _execution_error("a plan-local model reference cannot also specify a model run id")
    if producer_id not in step.depends_on or producer_id not in previous:
        raise _execution_error(f"model producer {producer_id} has not completed as a direct dependency")
    branches = previous[producer_id].payload.get("branches")
    if not isinstance(branches, list):
        raise _execution_error(f"model producer {producer_id} did not publish model branches")
    matched = [branch for branch in branches if isinstance(branch, Mapping) and branch.get("branch_id") == branch_id]
    if len(matched) != 1:
        raise _execution_error(f"model branch {branch_id} is missing or ambiguous")
    branch = matched[0]
    model_id = model_id_from_ref(branch.get("model_id"))
    if model_id not in branch.get("artifact_ids", []):
        raise _execution_error(f"model branch {branch_id} does not publish the model artifact")
    run_root = _run_root(root, str(branch.get("run_id") or ""))
    manifest_path = run_root / "run_manifest.json"
    if not manifest_path.is_file() or read_json(manifest_path).get("status") != "completed":
        raise _execution_error(f"model branch {branch_id} run has not completed")
    path = run_root / kernel_relative_path(model_id)
    digest = branch.get("inference_kernel_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or not path.is_file() or sha256_file(path) != digest:
        raise _execution_error(f"model branch {branch_id} inference kernel is missing or changed")
    if read_json(path).get("model_id") != model_id:
        raise _execution_error(f"model branch {branch_id} inference kernel identity does not match")
    return run_root, model_id


def execute_postestimation_step(root: Path, target_run_id: str, step: Any, *, previous: Mapping | None = None) -> tuple[dict[str, Any], str, str]:
    """Run one step; returns (result, model run id, model id)."""
    operation = step.operation_id.removeprefix(OPERATION_PREFIX)
    spec = step.spec
    run_root, model_id = _resolve_model_binding(root, target_run_id, step, "model_ref", previous or {})
    run_id = run_root.name
    kernels = [_load_kernel(run_root, model_id)]
    context: dict[str, Any] = {}
    try:
        if operation == "lr":
            restricted_root, restricted_id = _resolve_model_binding(root, target_run_id, step, "restricted_model_ref", previous or {})
            kernels.append(_load_kernel(restricted_root, restricted_id))
            from ..postestimation.comparison_data import assert_lr_comparable

            assert_lr_comparable(run_root, kernels[0], restricted_root, kernels[1])
        if OPERATIONS[operation].needs_estimation_data:
            declaration = declaration_for(str(kernels[0]["model_type"]))
            context = {
                "design": estimation_design(run_root, kernels[0]),
                "inverse_link": declaration.inverse_link if declaration is not None else None,
            }
        payload = {key: value for key, value in spec.items() if key != "source_artifact_fingerprint"}
        result = run_operation(operation, kernels, payload, context)
    except PostestimationRefusal as refusal:
        raise _execution_error(refusal.message) from refusal
    result = {"schema_version": RESULT_SCHEMA, "model_run_id": run_id, **result}
    if operation == "lr":
        result["restricted_model_run_id"] = restricted_root.name
    return result, run_id, model_id
