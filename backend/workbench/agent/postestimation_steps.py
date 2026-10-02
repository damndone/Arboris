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

from ..artifacts import read_json
from ..contracts.model.inference_kernel import (
    InferenceKernelError,
    kernel_relative_path,
    validate_inference_kernel,
)
from ..contracts.model.result_envelope_registry import declaration_for
from ..postestimation import PostestimationRefusal
from ..postestimation.estimation_data import estimation_design
from ..postestimation.registry import OPERATIONS, VALIDATED, run_operation

OPERATION_PREFIX = "postestimation."
DISPATCHER_KEY = "workbench.agent.workflow_runtime.postestimation"
VALIDATOR_KEY = "postestimation"
RESULT_SCHEMA = "workbench.postestimation.result/v1"

_MODEL_REF = (
    "Model node to read, as shown in the graph (`model:logit_1`, or its forest key); "
    "the model must belong to `model_run_id`, or to the workflow's target run when that is omitted."
)
_MODEL_RUN = "Run that owns `model_ref`; omit it for the workflow's target run."
_LEVEL = "Confidence level, default 0.95."

# operation -> (summary, fields, required, field types)
_STEP_SHAPES: Mapping[str, tuple[str, Mapping[str, str], tuple[str, ...], Mapping[str, str]]] = {
    "wald": (
        "Jointly test linear restrictions on a completed model's coefficients (Wald). "
        "Reads the model's stored covariance; F or chi-square follows the model's own inference.",
        {
            "model_ref": _MODEL_REF,
            "model_run_id": _MODEL_RUN,
            "constraints": (
                "Non-empty list of {terms, value}: `terms` maps coefficient names to weights and "
                "the restriction is sum(weight * coefficient) = value. Joint significance of x1 "
                "and x2 is [{terms: {x1: 1}, value: 0}, {terms: {x2: 1}, value: 0}]."
            ),
        },
        ("model_ref", "constraints"),
        {"model_ref": "string", "model_run_id": "string", "constraints": "list"},
    ),
    "lincom": (
        "Estimate a linear combination of a completed model's coefficients, with its standard "
        "error, test and confidence interval.",
        {
            "model_ref": _MODEL_REF,
            "model_run_id": _MODEL_RUN,
            "terms": "Object mapping coefficient names to weights.",
            "constant": "Number added to the combination, default 0.",
            "level": _LEVEL,
        },
        ("model_ref", "terms"),
        {"model_ref": "string", "model_run_id": "string", "terms": "object", "constant": "number", "level": "number"},
    ),
    "nlcom": (
        "Estimate a smooth function of a completed model's coefficients by the delta method.",
        {
            "model_ref": _MODEL_REF,
            "model_run_id": _MODEL_RUN,
            "expression": (
                "Arithmetic over coefficient names: + - * / **, exp, log, sqrt; write a name that is "
                "not an identifier as b[\"name\"]. Example: x1 / x2."
            ),
            "level": _LEVEL,
        },
        ("model_ref", "expression"),
        {"model_ref": "string", "model_run_id": "string", "expression": "string", "level": "number"},
    ),
    "lr": (
        "Likelihood-ratio test of a restricted model nested in a fuller one. Both must be "
        "estimated on the same rows with model-based (not robust or clustered) variance.",
        {
            "model_ref": "The fuller model. " + _MODEL_REF,
            "model_run_id": _MODEL_RUN,
            "restricted_model_ref": "The restricted model nested in it.",
            "restricted_model_run_id": "Run that owns the restricted model; omit for the target run.",
        },
        ("model_ref", "restricted_model_ref"),
        {
            "model_ref": "string", "model_run_id": "string",
            "restricted_model_ref": "string", "restricted_model_run_id": "string",
        },
    ),
    "margins": (
        "Marginal effects of regressors on the predicted outcome: averaged over the estimation "
        "sample (`at: average`) or at the regressors' means (`at: means`).",
        {
            "model_ref": _MODEL_REF,
            "model_run_id": _MODEL_RUN,
            "variables": "Non-empty list of regressor names.",
            "at": "`average` (default) or `means`.",
            "level": _LEVEL,
        },
        ("model_ref", "variables"),
        {"model_ref": "string", "model_run_id": "string", "variables": "list", "at": "string", "level": "number"},
    ),
}

def _execution_error(message: str) -> Exception:
    # Imported here: the workflow module imports the step contracts, which
    # import this module.
    from .workflow import WorkflowExecutionError

    return WorkflowExecutionError(message)


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MODEL_ID = re.compile(r"^[a-z][a-z0-9_]*_\d+$")
_FOREST_KEY = re.compile(r"^[0-9a-f]{64}::")


def postestimation_operation_id(operation: str) -> str:
    return OPERATION_PREFIX + operation


def postestimation_step_contracts() -> dict[str, Any]:
    from .workflow_contracts import StepSpecContract

    contracts = {}
    for operation in OPERATIONS:
        summary, fields, required, types = _STEP_SHAPES[operation]
        families = sorted({family for family, op in VALIDATED if op == operation})
        contracts[postestimation_operation_id(operation)] = StepSpecContract(
            summary=summary + f" Validated for: {', '.join(families)}.",
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
    from .operations import OperationValidationError

    operation = operation_id.removeprefix(OPERATION_PREFIX)
    try:
        model_id_from_ref(spec.get("model_ref"))
        if "restricted_model_ref" in spec:
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
    except InferenceKernelError as exc:
        raise _execution_error(f"the inference kernel of {model_id} is not usable: {exc}") from exc
    return kernel


def execute_postestimation_step(root: Path, target_run_id: str, step: Any) -> tuple[dict[str, Any], str, str]:
    """Run one step; returns (result, model run id, model id)."""
    operation = step.operation_id.removeprefix(OPERATION_PREFIX)
    spec = step.spec
    run_id = str(spec.get("model_run_id") or target_run_id)
    run_root = _run_root(root, run_id)
    model_id = model_id_from_ref(spec.get("model_ref"))
    kernels = [_load_kernel(run_root, model_id)]
    context: dict[str, Any] = {}
    try:
        if operation == "lr":
            restricted_root = _run_root(root, str(spec.get("restricted_model_run_id") or target_run_id))
            kernels.append(_load_kernel(restricted_root, model_id_from_ref(spec.get("restricted_model_ref"))))
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
    return result, run_id, model_id
