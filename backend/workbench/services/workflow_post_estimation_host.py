"""Server-owned runtime boundary for workflow post-estimation adapters.

The provider manifest only declares three opaque executor identities.  This
module is the explicit host-side join for those identities.  It accepts a
bounded workflow plan and recompiles it with the server compiler; it never
accepts a filesystem path, evidence owner, authority token, import path, or a
serialized compiler receipt from a request.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
from typing import Any

from workbench.agent.trusted_executor_registry import (
    ProviderRuntimeContextV1,
    ProviderRuntimeContributionV1,
    TrustedExecutorRegistryError,
)
from workbench.agent.workflow import (
    WorkflowExecutionError,
    compile_workflow,
    execute_workflow,
)
from workbench.agent.workflow_runtime import (
    WorkflowHostEndpointV1,
    collect_post_estimation_results,
    issue_server_evidence_port,
)
from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.contracts.common.provider import (
    AdapterDeclarationV1,
    ProviderContributionV1,
)


WORKFLOW_POST_ESTIMATION_RESULT_SCHEMA = "workbench.workflow.post-estimation.result/v1"
WORKFLOW_POST_ESTIMATION_ADAPTERS = (
    "workflow.post_estimation.joint_f_test",
    "workflow.post_estimation.white_test",
    "workflow.post_estimation.quadratic_stationary_point",
)
WORKFLOW_POST_ESTIMATION_EXECUTOR_REFS = {
    adapter_id: f"executor:{adapter_id}" for adapter_id in WORKFLOW_POST_ESTIMATION_ADAPTERS
}

_SERVER_OWNED_ISSUER = object()
_SERVER_OWNED_CAPABILITY = object()
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GENERIC_REQUEST_FIELDS = frozenset(
    {"capability_id", "target_ref", "data_snapshot_ref", "source_text_digest", "options"}
)
_PLAN_FIELDS = frozenset(
    {"workflow_id", "workflow_template", "target", "preconditions", "bindings", "steps"}
)
_TARGET_FIELDS = frozenset({"run_id", "node_ref", "artifact_id"})
_PRECONDITION_FIELDS = frozenset(
    {
        "context_fingerprint",
        "source_artifact_fingerprint",
        "active_head_run_id",
        "context_version",
        "owner_resolution",
    }
)
_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "adapter_id",
        "status",
        "workflow_id",
        "workflow_step_id",
        "artifact_id",
        "result_digest",
        "result",
    }
)
_FORBIDDEN_REQUEST_KEYS = frozenset(
    {
        "authority",
        "authority_id",
        "authorization",
        "evidence_owner",
        "evidence_owner_ref",
        "evidence_ref",
        "import",
        "import_path",
        "module",
        "module_path",
        "owner",
        "owner_ref",
        "path",
    }
)
_FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "authority",
        "evidence_owner",
        "module",
        "path",
        "raw_data",
        "raw_rows",
        "rows",
    }
)

_OPERATION_BY_ADAPTER = {
    "workflow.post_estimation.joint_f_test": "model.joint_f_test",
    "workflow.post_estimation.white_test": "model.white_test",
    "workflow.post_estimation.quadratic_stationary_point": "model.quadratic_stationary_point",
}
_RESULT_FIELDS_BY_ADAPTER = {
    "workflow.post_estimation.joint_f_test": frozenset(
        {
            "schema_version",
            "test",
            "branch_id",
            "term_selectors",
            "coefficient_terms",
            "f_statistic",
            "p_value",
            "numerator_df",
            "denominator_df",
            "nobs",
            "covariance",
        }
    ),
    "workflow.post_estimation.white_test": frozenset(
        {
            "schema_version",
            "test",
            "branch_id",
            "lm_statistic",
            "lm_p_value",
            "f_statistic",
            "f_p_value",
            "auxiliary_df",
            "residual_df",
            "nobs",
            "covariance",
        }
    ),
    "workflow.post_estimation.quadratic_stationary_point": frozenset(
        {
            "schema_version",
            "branch_id",
            "column",
            "linear_coefficient",
            "quadratic_coefficient",
            "stationary_point",
            "observed_min",
            "observed_max",
            "stationary_point_within_observed_range",
            "curvature",
            "nobs",
            "covariance",
        }
    ),
}


def _error(code: str, message: str | None = None) -> TrustedExecutorRegistryError:
    return TrustedExecutorRegistryError(code, message or code)


def _safe_text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise _error("RUNTIME_REQUEST_INVALID", f"{name} must be a non-empty string")
    if value.startswith(("/", "\\", "~")) or "://" in value or ".." in value:
        raise _error("RUNTIME_REQUEST_INVALID", f"{name} must be an opaque reference")
    return value


def _bounded_json(value: object, *, path: str = "payload", depth: int = 0) -> None:
    if depth > 8:
        raise _error("RUNTIME_REQUEST_INVALID", f"{path} is too deeply nested")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if type(key) is not str or not key or key.casefold() in _FORBIDDEN_REQUEST_KEYS:
                raise _error("RUNTIME_REQUEST_INVALID", f"{path} contains a forbidden field")
            _bounded_json(child, path=f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > 64:
            raise _error("RUNTIME_REQUEST_INVALID", f"{path} exceeds its list bound")
        for index, child in enumerate(value):
            _bounded_json(child, path=f"{path}[{index}]", depth=depth + 1)
        return
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise _error("RUNTIME_REQUEST_INVALID", f"{path} contains an unsupported value")


def _validate_plan(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PLAN_FIELDS:
        raise _error("WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED", "canonical workflow plan is required")
    _bounded_json(value)
    workflow_id = _safe_text(value.get("workflow_id"), "workflow_id")
    workflow_template = _safe_text(value.get("workflow_template"), "workflow_template")
    target = value.get("target")
    if not isinstance(target, Mapping) or set(target) != _TARGET_FIELDS:
        raise _error("RUNTIME_REQUEST_INVALID", "workflow target must contain only run_id, node_ref, artifact_id")
    normalized_target = {
        name: _safe_text(target.get(name), f"target.{name}") for name in _TARGET_FIELDS
    }
    preconditions = value.get("preconditions")
    if not isinstance(preconditions, Mapping):
        raise _error("RUNTIME_REQUEST_INVALID", "workflow preconditions must be an object")
    unknown_preconditions = set(preconditions) - _PRECONDITION_FIELDS
    if unknown_preconditions:
        raise _error("RUNTIME_REQUEST_INVALID", "workflow preconditions contain unsupported fields")
    if not preconditions.get("context_fingerprint"):
        raise _error("WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED", "workflow context fingerprint is required")
    normalized_preconditions = dict(preconditions)
    for name, item in normalized_preconditions.items():
        _safe_text(item, f"preconditions.{name}")
    bindings = value.get("bindings")
    if not isinstance(bindings, Mapping):
        raise _error("RUNTIME_REQUEST_INVALID", "workflow bindings must be an object")
    steps = value.get("steps")
    if not isinstance(steps, list) or not steps or len(steps) > 32:
        raise _error("WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED", "canonical workflow steps are required")
    for step in steps:
        if not isinstance(step, Mapping):
            raise _error("RUNTIME_REQUEST_INVALID", "workflow steps must be objects")
    normalized = {
        "workflow_id": workflow_id,
        "workflow_template": workflow_template,
        "target": normalized_target,
        "preconditions": normalized_preconditions,
        "bindings": dict(bindings),
        "steps": [dict(step) for step in steps],
    }
    try:
        if len(canonical_json_v1(normalized).encode("utf-8")) > 128 * 1024:
            raise _error("RUNTIME_REQUEST_INVALID", "canonical workflow plan exceeds its size bound")
    except TrustedExecutorRegistryError:
        raise
    except (TypeError, ValueError) as exc:
        raise _error("RUNTIME_REQUEST_INVALID", "canonical workflow plan is not JSON-safe") from exc
    return normalized


def _server_owned_default_workflow_plan(
    project_root: Path,
    *,
    target_ref: str,
    data_snapshot_ref: str,
    adapter_id: str,
    project_ref: str,
    session_ref: str,
    execution_identity: str,
) -> dict[str, Any]:
    """Build the bounded post-estimation plan from the selected local run.

    The cutover compiler intentionally keeps the public intent small: a user
    names a registered post-estimation capability and the server binds it to
    the current run.  The local provider still needs the canonical workflow
    shape, so this adapter derives that shape from server-owned run inputs and
    graph identity.  It never accepts a caller path, formula, model branch, or
    evidence owner.  If the durable run does not contain enough information,
    it fails closed and asks for a typed workflow plan instead of guessing.
    """

    if not isinstance(project_root, Path):
        raise _error("WORKFLOW_POST_ESTIMATION_UNAVAILABLE")
    run_id = target_ref.removeprefix("run:")
    if not run_id or run_id == "." or run_id == "..":
        raise _error("WORKFLOW_POST_ESTIMATION_SCOPE_MISMATCH")
    from workbench.data_operations import resolve_data_column_cast_context
    from workbench.graph_store import GraphStore
    from workbench.lineage.run_inputs import read_run_inputs

    try:
        source = resolve_data_column_cast_context(
            project_root,
            source_run_id=run_id,
            source_node_id="stage:raw",
        )
        graph = GraphStore(project_root / "runs").read(run_id)
        inputs = read_run_inputs(project_root / "runs" / run_id)
    except Exception as exc:
        raise _error("WORKFLOW_POST_ESTIMATION_UNAVAILABLE") from exc

    expected_snapshot_ref = f"dataset:{source['source_sha256']}"
    if data_snapshot_ref != expected_snapshot_ref:
        raise _error(
            "WORKFLOW_POST_ESTIMATION_SCOPE_MISMATCH",
            "selected data snapshot is not the server-resolved raw snapshot",
        )

    executed = inputs.get("executed_payload")
    if not isinstance(executed, Mapping):
        raise _error("WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED")
    if executed.get("model_type") != "ols":
        raise _error(
            "WORKFLOW_POST_ESTIMATION_UNSUPPORTED_FAMILY",
            "the local post-estimation adapter currently requires an OLS run",
        )
    outcome = executed.get("y")
    predictors = executed.get("x")
    covariance = executed.get("covariance")
    if (
        type(outcome) is not str
        or not outcome
        or not isinstance(predictors, list)
        or not predictors
        or any(type(item) is not str or not item for item in predictors)
        or type(covariance) is not str
        or covariance not in {"unadjusted", "robust", "clustered"}
    ):
        raise _error("WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED")

    model_id = None
    routing = inputs.get("model_routing")
    if isinstance(routing, Mapping):
        candidate = routing.get("effective_model_id")
        if isinstance(candidate, str) and candidate:
            model_id = candidate
    model_node = graph.nodes.get(f"model:{model_id}") if model_id else None
    if model_node is None:
        model_nodes = [
            node
            for node in graph.nodes.values()
            if getattr(node, "kind", None).value == "model"
        ]
        if len(model_nodes) == 1:
            model_node = model_nodes[0]
    branch_id = getattr(model_node, "branch_id", None)
    if type(branch_id) is not str or not branch_id:
        raise _error("WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED")

    available_columns = {
        str(item.get("name"))
        for item in source.get("columns", [])
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    if outcome not in available_columns or any(item not in available_columns for item in predictors):
        raise _error("WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED")

    if adapter_id == "workflow.post_estimation.joint_f_test":
        post_spec: dict[str, Any] = {
            "branch_id": branch_id,
            "term_selectors": [
                {"kind": "linear", "column": column} for column in predictors
            ],
        }
    elif adapter_id == "workflow.post_estimation.white_test":
        post_spec = {"branch_id": branch_id}
    else:
        raise _error(
            "WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED",
            "quadratic stationary-point execution needs an explicit polynomial workflow plan",
        )

    operation_id = _OPERATION_BY_ADAPTER[adapter_id]
    execution_token = sha256_canonical(
        {"execution_identity": execution_identity}
    )[:24]
    workflow_id = (
        f"agent-post-estimation-{run_id}-{adapter_id.replace('.', '-')}-{execution_token}"
    )
    context_fingerprint = f"sha256:{source['source_sha256']}"
    return {
        "workflow_id": workflow_id,
        "workflow_template": "agent-composed-v1",
        "target": {
            "run_id": run_id,
            "node_ref": "stage:raw",
            "artifact_id": source["source_artifact_id"],
        },
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": context_fingerprint,
            "source_artifact_fingerprint": source["source_sha256"],
            "active_head_run_id": run_id,
            "owner_resolution": "single_candidate",
        },
        "bindings": {
            "source_model_id": model_id or "server-resolved-single-model",
            "project_ref": project_ref,
            "session_ref": session_ref,
        },
        "steps": [
            {
                "step_id": "model",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "ols",
                    "covariance": covariance,
                    "branches": [
                        {
                            "branch_id": branch_id,
                            "outcome": outcome,
                            "predictors": list(predictors),
                            "covariance": covariance,
                        }
                    ],
                },
            },
            {
                "step_id": "post_estimation",
                "operation_id": operation_id,
                "depends_on": ["model"],
                "spec": post_spec,
            },
        ],
    }


def validate_workflow_post_estimation_request(
    adapter_id: str, request: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the finite provider request without accepting host authority."""

    if not isinstance(request, Mapping) or set(request) != _GENERIC_REQUEST_FIELDS:
        raise _error("RUNTIME_REQUEST_INVALID", "workflow post-estimation request fields are not exact")
    if request.get("capability_id") != adapter_id:
        raise _error("RUNTIME_REQUEST_INVALID", "workflow post-estimation capability identity changed")
    normalized = {
        "capability_id": _safe_text(request.get("capability_id"), "capability_id"),
        "target_ref": _safe_text(request.get("target_ref"), "target_ref"),
        "data_snapshot_ref": _safe_text(request.get("data_snapshot_ref"), "data_snapshot_ref"),
        "source_text_digest": _safe_text(request.get("source_text_digest"), "source_text_digest"),
    }
    options = request.get("options")
    if not isinstance(options, Mapping) or set(options) != {"workflow_draft"}:
        raise _error(
            "WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED",
            "options.workflow_draft is required; request-owned paths and authorities are not accepted",
        )
    normalized["options"] = {"workflow_draft": _validate_plan(options.get("workflow_draft"))}
    return normalized


def _validate_local_synthesis_request(
    adapter_id: str, request: Mapping[str, Any]
) -> dict[str, Any]:
    """Admit only an empty provider-options envelope for local plan synthesis."""

    if not isinstance(request, Mapping) or set(request) != _GENERIC_REQUEST_FIELDS:
        raise _error("RUNTIME_REQUEST_INVALID", "workflow post-estimation request fields are not exact")
    if request.get("capability_id") != adapter_id:
        raise _error("RUNTIME_REQUEST_INVALID", "workflow post-estimation capability identity changed")
    for name in ("capability_id", "target_ref", "data_snapshot_ref", "source_text_digest"):
        _safe_text(request.get(name), name)
    options = request.get("options")
    if isinstance(options, Mapping) and not options:
        _bounded_json(request)
        return dict(request)
    return validate_workflow_post_estimation_request(adapter_id, request)


def _finite_number(value: object, name: str) -> None:
    if type(value) not in {int, float} or isinstance(value, bool) or not math.isfinite(float(value)):
        raise _error("RUNTIME_RESULT_INVALID", f"{name} must be finite")


def _validate_post_estimation_payload(adapter_id: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error("RUNTIME_RESULT_INVALID", "post-estimation result must be an object")
    expected = _RESULT_FIELDS_BY_ADAPTER[adapter_id]
    if set(value) != expected:
        raise _error("RUNTIME_RESULT_INVALID", "post-estimation result fields are not exact")
    schema_by_adapter = {
        "workflow.post_estimation.joint_f_test": "workbench.model.joint-f-test/v1",
        "workflow.post_estimation.white_test": "workbench.model.white-test/v1",
        "workflow.post_estimation.quadratic_stationary_point": "workbench.model.quadratic-stationary-point/v1",
    }
    if value.get("schema_version") != schema_by_adapter[adapter_id]:
        raise _error("RUNTIME_RESULT_INVALID", "post-estimation result schema is unsupported")
    if adapter_id == "workflow.post_estimation.joint_f_test":
        if value.get("test") != "joint_f_test":
            raise _error("RUNTIME_RESULT_INVALID", "joint F result identity is invalid")
        if not isinstance(value.get("term_selectors"), list) or not isinstance(value.get("coefficient_terms"), list):
            raise _error("RUNTIME_RESULT_INVALID", "joint F result terms are invalid")
        for name in ("f_statistic", "p_value", "numerator_df", "denominator_df"):
            _finite_number(value.get(name), name)
    elif adapter_id == "workflow.post_estimation.white_test":
        if value.get("test") != "white_test":
            raise _error("RUNTIME_RESULT_INVALID", "White result identity is invalid")
        for name in ("lm_statistic", "lm_p_value", "f_statistic", "f_p_value"):
            _finite_number(value.get(name), name)
        for name in ("auxiliary_df", "residual_df"):
            if type(value.get(name)) is not int or value[name] < 1:
                raise _error("RUNTIME_RESULT_INVALID", f"{name} must be a positive integer")
    else:
        if type(value.get("column")) is not str or not value["column"]:
            raise _error("RUNTIME_RESULT_INVALID", "stationary-point column is invalid")
        if value.get("curvature") not in {"minimum", "maximum"}:
            raise _error("RUNTIME_RESULT_INVALID", "stationary-point curvature is invalid")
        if type(value.get("stationary_point_within_observed_range")) is not bool:
            raise _error("RUNTIME_RESULT_INVALID", "stationary-point range flag is invalid")
        for name in (
            "linear_coefficient",
            "quadratic_coefficient",
            "stationary_point",
            "observed_min",
            "observed_max",
        ):
            _finite_number(value.get(name), name)
    for name in ("branch_id", "covariance"):
        _safe_text(value.get(name), name)
    if type(value.get("nobs")) is not int or value["nobs"] < 1:
        raise _error("RUNTIME_RESULT_INVALID", "nobs must be a positive integer")
    _bounded_json(value)
    return dict(value)


def validate_workflow_post_estimation_result(adapter_id: str, value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or set(value) != _RESULT_FIELDS:
        raise _error("RUNTIME_RESULT_INVALID", "post-estimation envelope fields are not exact")
    if value.get("schema_version") != WORKFLOW_POST_ESTIMATION_RESULT_SCHEMA:
        raise _error("RUNTIME_RESULT_INVALID", "post-estimation envelope schema is unsupported")
    if value.get("adapter_id") != adapter_id or value.get("status") != "completed":
        raise _error("RUNTIME_RESULT_INVALID", "post-estimation envelope identity or status is invalid")
    for name in ("workflow_id", "workflow_step_id", "artifact_id"):
        _safe_text(value.get(name), name)
    digest = value.get("result_digest")
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        raise _error("RUNTIME_RESULT_INVALID", "post-estimation result digest is invalid")
    result = _validate_post_estimation_payload(adapter_id, value.get("result"))
    if digest != sha256_canonical(result):
        raise _error("RUNTIME_RESULT_INVALID", "post-estimation result digest does not match result")
    _bounded_json(value)


@dataclass(frozen=True, slots=True)
class WorkflowPostEstimationExecutionPortV1:
    """A server-issued post-estimation execution port.

    The generic runtime receives this object only after application startup
    has composed it.  Request data is passed to the port as a bounded plan;
    the port owns the project root, scope and workflow endpoint.
    """

    _execute: Callable[[ProviderRuntimeContextV1, Mapping[str, Any]], Mapping[str, Any]]
    catalog_digest: str
    project_ref: str
    session_ref: str
    project_root: Path | None = field(default=None, repr=False, compare=False)
    workflow_endpoint: WorkflowHostEndpointV1 | None = field(default=None, repr=False, compare=False)
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not callable(self._execute):
            raise TypeError("workflow post-estimation port requires a callable server implementation")
        if type(self.catalog_digest) is not str or _SHA256.fullmatch(self.catalog_digest) is None:
            raise ValueError("workflow post-estimation port catalog digest is invalid")
        if type(self.project_ref) is not str or not self.project_ref.startswith("project:"):
            raise ValueError("workflow post-estimation port project scope is invalid")
        if type(self.session_ref) is not str or not self.session_ref.startswith("session:"):
            raise ValueError("workflow post-estimation port session scope is invalid")
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("workflow post-estimation port requires the server-owned issuer")
        if self.workflow_endpoint is not None and type(self.workflow_endpoint) is not WorkflowHostEndpointV1:
            raise TypeError("workflow post-estimation port endpoint is invalid")

    @classmethod
    def from_server(
        cls,
        execute: Callable[[ProviderRuntimeContextV1, Mapping[str, Any]], Mapping[str, Any]],
        *,
        catalog_digest: str,
        project_ref: str,
        session_ref: str,
        _issuer: object | None = None,
    ) -> "WorkflowPostEstimationExecutionPortV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("workflow post-estimation port requires the server-owned issuer")
        return cls(
            _execute=execute,
            catalog_digest=catalog_digest,
            project_ref=project_ref,
            session_ref=session_ref,
            _capability=_SERVER_OWNED_CAPABILITY,
        )

    @classmethod
    def from_local_host(
        cls,
        *,
        project_root: Path | str,
        workflow_endpoint: WorkflowHostEndpointV1,
        project_ref: str,
        session_ref: str,
        catalog_digest: str,
    ) -> "WorkflowPostEstimationExecutionPortV1":
        root = Path(project_root).expanduser().resolve()
        if type(workflow_endpoint) is not WorkflowHostEndpointV1:
            raise TypeError("local workflow post-estimation port requires the admitted workflow endpoint")
        if workflow_endpoint.project_root != root:
            raise ValueError("local workflow post-estimation endpoint/project binding changed")
        # This call is the admission check. It proves that the endpoint is
        # current in this process without retaining a second evidence owner.
        evidence_port = issue_server_evidence_port(root)
        evidence_port.close()
        port = cls(
            _execute=lambda _context, _request: {},
            catalog_digest=catalog_digest,
            project_ref=project_ref,
            session_ref=session_ref,
            project_root=root,
            workflow_endpoint=workflow_endpoint,
            _capability=_SERVER_OWNED_CAPABILITY,
        )
        object.__setattr__(port, "_execute", port._execute_local)
        return port

    def execute(
        self,
        context: ProviderRuntimeContextV1,
        request: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if type(context) is not ProviderRuntimeContextV1:
            raise _error("RUNTIME_CONTEXT_REQUIRED")
        if context.project_ref != self.project_ref or context.session_ref != self.session_ref:
            raise _error("WORKFLOW_POST_ESTIMATION_SCOPE_MISMATCH")
        if context.effect not in {"read", "read_only"} or context.evidence_required is not True:
            raise _error("WORKFLOW_POST_ESTIMATION_POLICY_REQUIRED")
        if not isinstance(request, Mapping):
            raise _error("RUNTIME_REQUEST_REQUIRED")
        try:
            result = self._execute(context, dict(request))
        except TrustedExecutorRegistryError:
            raise
        except Exception as exc:
            raise _error("WORKFLOW_POST_ESTIMATION_UNAVAILABLE") from exc
        if not isinstance(result, Mapping):
            raise _error("RUNTIME_RESULT_INVALID")
        return dict(result)

    def _execute_local(
        self,
        context: ProviderRuntimeContextV1,
        request: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if self.project_root is None or self.workflow_endpoint is None:
            raise _error("WORKFLOW_POST_ESTIMATION_UNAVAILABLE")
        if not isinstance(request, Mapping) or "options" not in request:
            raise _error("WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED")
        adapter_id = str(request.get("capability_id", ""))
        if adapter_id not in WORKFLOW_POST_ESTIMATION_ADAPTERS:
            raise _error("RUNTIME_REQUEST_INVALID")
        effective_request = dict(request)
        options = request.get("options")
        if isinstance(options, Mapping) and "workflow_draft" not in options:
            if options:
                raise _error(
                    "WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED",
                    "options.workflow_draft is required; unrecognized provider options are not accepted",
                )
            effective_request["options"] = {
                "workflow_draft": _server_owned_default_workflow_plan(
                    self.project_root,
                    target_ref=_safe_text(request.get("target_ref"), "target_ref"),
                    data_snapshot_ref=_safe_text(
                        request.get("data_snapshot_ref"), "data_snapshot_ref"
                    ),
                    adapter_id=adapter_id,
                    project_ref=self.project_ref,
                    session_ref=self.session_ref,
                    execution_identity=context.compilation_record_id,
                )
            }
        normalized = validate_workflow_post_estimation_request(adapter_id, effective_request)
        plan = normalized["options"]["workflow_draft"]
        target_run_id = str(plan["target"]["run_id"])
        target_ref = str(normalized["target_ref"])
        if target_ref not in {target_run_id, f"run:{target_run_id}"}:
            raise _error("WORKFLOW_POST_ESTIMATION_SCOPE_MISMATCH")
        matching_steps = [
            step
            for step in plan["steps"]
            if isinstance(step, Mapping)
            and step.get("operation_id") == _OPERATION_BY_ADAPTER[adapter_id]
        ]
        if len(matching_steps) != 1:
            raise _error("WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED")
        try:
            draft = compile_workflow(
                workflow_id=plan["workflow_id"],
                workflow_template=plan["workflow_template"],
                target=plan["target"],
                preconditions=plan["preconditions"],
                bindings=plan["bindings"],
                steps=plan["steps"],
                project_ref=context.project_ref,
                session_ref=context.session_ref,
            )
        except Exception as exc:
            raise _error("WORKFLOW_POST_ESTIMATION_REQUEST_INVALID") from exc
        evidence_port = None
        try:
            evidence_port = issue_server_evidence_port(self.project_root)
            state = execute_workflow(self.project_root, draft, evidence_port=evidence_port)
        except Exception as exc:
            raise _error("WORKFLOW_POST_ESTIMATION_UNAVAILABLE") from exc
        finally:
            if evidence_port is not None:
                evidence_port.close()
        if state.status != "completed":
            raise _error("WORKFLOW_POST_ESTIMATION_UNAVAILABLE")
        step_id = str(matching_steps[0]["step_id"])
        try:
            entries = collect_post_estimation_results(self.project_root, target_run_id)
        except Exception as exc:
            raise _error("WORKFLOW_POST_ESTIMATION_UNAVAILABLE") from exc
        matches = [
            entry
            for entry in entries
            if entry.get("workflow_id") == draft.workflow_id
            and entry.get("workflow_step_id") == step_id
            and entry.get("operation_id") == _OPERATION_BY_ADAPTER[adapter_id]
        ]
        if len(matches) != 1:
            raise _error("WORKFLOW_POST_ESTIMATION_UNAVAILABLE")
        entry = matches[0]
        result = _validate_post_estimation_payload(adapter_id, entry.get("result"))
        envelope = {
            "schema_version": WORKFLOW_POST_ESTIMATION_RESULT_SCHEMA,
            "adapter_id": adapter_id,
            "status": "completed",
            "workflow_id": draft.workflow_id,
            "workflow_step_id": step_id,
            "artifact_id": str(entry.get("artifact_id", "")),
            "result_digest": sha256_canonical(result),
            "result": result,
        }
        validate_workflow_post_estimation_result(adapter_id, envelope)
        return envelope


def build_workflow_post_estimation_runtime_contribution(
    provider: ProviderContributionV1,
    declaration: AdapterDeclarationV1,
    *,
    catalog_digest: str,
    execution_port: WorkflowPostEstimationExecutionPortV1 | None,
) -> ProviderRuntimeContributionV1:
    """Join one manifest declaration to one explicitly injected host port."""

    adapter_id = declaration.adapter_id
    if adapter_id not in WORKFLOW_POST_ESTIMATION_ADAPTERS:
        raise TrustedExecutorRegistryError("WORKFLOW_POST_ESTIMATION_ADAPTER_INVALID")
    if execution_port is None:
        raise TrustedExecutorRegistryError("WORKFLOW_POST_ESTIMATION_EXECUTION_PORT_REQUIRED")
    if type(execution_port) is not WorkflowPostEstimationExecutionPortV1:
        raise TrustedExecutorRegistryError("WORKFLOW_POST_ESTIMATION_EXECUTION_PORT_REQUIRED")
    if execution_port.catalog_digest != catalog_digest:
        raise TrustedExecutorRegistryError("WORKFLOW_POST_ESTIMATION_CATALOG_MISMATCH")

    request_validator = (
        _validate_local_synthesis_request
        if execution_port.project_root is not None and execution_port.workflow_endpoint is not None
        else validate_workflow_post_estimation_request
    )
    return ProviderRuntimeContributionV1(
        provider_id=provider.provider_id,
        adapter_id=adapter_id,
        executor_ref=declaration.executor_ref,
        owner="workbench.server.workflow_post_estimation",
        signature="workbench.workflow.post_estimation.runtime.v1",
        effect="read_only",
        request_contract_ref=declaration.request_schema_ref,
        result_contract_refs=declaration.output_refs,
        executor=lambda context, request: execution_port.execute(context, request),
        request_validator=lambda request: request_validator(adapter_id, request),
        result_validator=lambda result: validate_workflow_post_estimation_result(adapter_id, result),
        execution_allowed=True,
        metadata={
            "status": "available",
            "provider_id": provider.provider_id,
            "adapter_id": adapter_id,
            "catalog_digest": catalog_digest,
            "evidence_required": True,
        },
    )


__all__ = [
    "WORKFLOW_POST_ESTIMATION_ADAPTERS",
    "WORKFLOW_POST_ESTIMATION_EXECUTOR_REFS",
    "WORKFLOW_POST_ESTIMATION_RESULT_SCHEMA",
    "WorkflowPostEstimationExecutionPortV1",
    "build_workflow_post_estimation_runtime_contribution",
    "validate_workflow_post_estimation_request",
    "validate_workflow_post_estimation_result",
]
