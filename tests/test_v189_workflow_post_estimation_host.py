from __future__ import annotations

from collections.abc import Mapping
import platform

import pytest
from fastapi import FastAPI

from workbench.agent.runtime_bootstrap import compose_builtin_agent_notebook_runtime
from workbench.agent.trusted_executor_registry import (
    ProviderRuntimeContextV1,
    TrustedExecutorRegistryError,
)
from workbench.canonical import sha256_canonical
from workbench.app import bootstrap_builtin_agent_notebook_runtime
from workbench.providers.catalog import load_builtin_catalog
from workbench.services import workflow_post_estimation_host as host_module
from workbench.services.workflow_post_estimation_host import (
    WorkflowPostEstimationExecutionPortV1,
)
from tests.v189_cutover_test_host import CutoverTestHostCompiler


_ADAPTERS = (
    (
        "workflow.post_estimation.joint_f_test",
        "executor:workflow.post_estimation.joint_f_test",
    ),
    (
        "workflow.post_estimation.white_test",
        "executor:workflow.post_estimation.white_test",
    ),
    (
        "workflow.post_estimation.quadratic_stationary_point",
        "executor:workflow.post_estimation.quadratic_stationary_point",
    ),
)


def _result(adapter_id: str) -> dict[str, object]:
    result_by_adapter = {
        "workflow.post_estimation.joint_f_test": {
            "schema_version": "workbench.model.joint-f-test/v1",
            "test": "joint_f_test",
            "branch_id": "linear",
            "term_selectors": [{"kind": "linear", "column": "exposure"}],
            "coefficient_terms": ["Q('exposure')"],
            "f_statistic": 1.0,
            "p_value": 0.5,
            "numerator_df": 1.0,
            "denominator_df": 20.0,
            "nobs": 24,
            "covariance": "unadjusted",
        },
        "workflow.post_estimation.white_test": {
            "schema_version": "workbench.model.white-test/v1",
            "test": "white_test",
            "branch_id": "linear",
            "lm_statistic": 1.0,
            "lm_p_value": 0.5,
            "f_statistic": 1.0,
            "f_p_value": 0.5,
            "auxiliary_df": 1,
            "residual_df": 20,
            "nobs": 24,
            "covariance": "unadjusted",
        },
        "workflow.post_estimation.quadratic_stationary_point": {
            "schema_version": "workbench.model.quadratic-stationary-point/v1",
            "branch_id": "linear",
            "column": "exposure",
            "linear_coefficient": 1.0,
            "quadratic_coefficient": -1.0,
            "stationary_point": 0.5,
            "observed_min": 0.0,
            "observed_max": 1.0,
            "stationary_point_within_observed_range": True,
            "curvature": "maximum",
            "nobs": 24,
            "covariance": "unadjusted",
        },
    }
    return dict(result_by_adapter[adapter_id])


def _port(catalog, adapter_id: str) -> WorkflowPostEstimationExecutionPortV1:
    def execute(_context: object, request: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "schema_version": "workbench.workflow.post-estimation.result/v1",
            "adapter_id": adapter_id,
            "status": "completed",
            "workflow_id": "workflow:test",
            "workflow_step_id": "post_estimation",
            "artifact_id": "artifact:post-estimation",
            "result_digest": sha256_canonical(_result(adapter_id)),
            "result": _result(adapter_id),
        }

    return WorkflowPostEstimationExecutionPortV1.from_server(
        execute,
        catalog_digest=catalog.catalog_digest,
        project_ref="project:test",
        session_ref="session:test",
        _issuer=host_module._SERVER_OWNED_ISSUER,
    )


def _valid_request(adapter_id: str) -> dict[str, object]:
    return {
        "capability_id": adapter_id,
        "target_ref": "run:test",
        "data_snapshot_ref": "artifact:test",
        "source_text_digest": "digest:test",
        "options": {
            "workflow_draft": {
                "workflow_id": "workflow:test",
                "workflow_template": "agent-composed-v1",
                "target": {
                    "run_id": "test",
                    "node_ref": "stage:raw",
                    "artifact_id": "raw:test",
                },
                "preconditions": {"context_fingerprint": "context:test"},
                "bindings": {},
                "steps": [
                    {
                        "step_id": "post_estimation",
                        "operation_id": "model.joint_f_test",
                        "depends_on": ["model"],
                        "spec": {"branch_id": "linear", "term_selectors": []},
                    }
                ],
            }
        },
    }


@pytest.mark.parametrize("adapter_id, executor_ref", _ADAPTERS)
def test_injected_server_port_enables_each_declared_post_estimation_adapter(
    adapter_id: str,
    executor_ref: str,
) -> None:
    catalog = load_builtin_catalog()
    runtime = compose_builtin_agent_notebook_runtime(
        provider_catalog=catalog,
        evidence_committer=lambda _context, _result: object(),
        host_compiler=CutoverTestHostCompiler(),
        project_ref="project:test",
        session_ref="session:test",
        workflow_post_estimation_execution_port=_port(catalog, adapter_id),
    )

    contribution = runtime.runtime_registry.require(executor_ref)

    assert contribution.execution_allowed is True
    assert contribution.metadata["status"] == "available"
    assert contribution.adapter_id == adapter_id


def test_missing_server_port_keeps_all_post_estimation_adapters_blocked() -> None:
    catalog = load_builtin_catalog()
    runtime = compose_builtin_agent_notebook_runtime(
        provider_catalog=catalog,
        evidence_committer=lambda _context, _result: object(),
        host_compiler=CutoverTestHostCompiler(),
    )

    for _adapter_id, executor_ref in _ADAPTERS:
        contribution = runtime.runtime_registry.require(executor_ref)
        assert contribution.execution_allowed is False
        assert contribution.metadata["status"] == "unavailable"


def test_app_bootstrap_forwards_the_server_port_into_the_shared_runtime() -> None:
    catalog = load_builtin_catalog()
    app = FastAPI()
    runtime = bootstrap_builtin_agent_notebook_runtime(
        project_ref="project:test",
        session_ref="session:test",
        provider_catalog=catalog,
        evidence_committer=lambda _context, _result: object(),
        host_compiler=CutoverTestHostCompiler(),
        workflow_post_estimation_execution_port=_port(
            catalog, "workflow.post_estimation.white_test"
        ),
        app_instance=app,
    )

    contribution = runtime.runtime_registry.require(
        "executor:workflow.post_estimation.white_test"
    )
    assert app.state.agent_notebook_cutover_store.authorities[
        ("project:test", "session:test")
    ] is runtime.compiler
    assert contribution.execution_allowed is True
    assert contribution.metadata["status"] == "available"


def test_bound_port_dispatches_only_the_typed_bounded_result() -> None:
    catalog = load_builtin_catalog()
    runtime = compose_builtin_agent_notebook_runtime(
        provider_catalog=catalog,
        evidence_committer=lambda _context, _result: object(),
        host_compiler=CutoverTestHostCompiler(),
        project_ref="project:test",
        session_ref="session:test",
        workflow_post_estimation_execution_port=_port(
            catalog, "workflow.post_estimation.joint_f_test"
        ),
    )
    context = ProviderRuntimeContextV1(
        compilation_record_id="record:test",
        execution_instance_hash="hash:test",
        actor_ref="principal:test",
        session_ref="session:test",
        project_ref="project:test",
        effect="read_only",
    )

    result = runtime.runtime_registry.dispatch(
        "executor:workflow.post_estimation.joint_f_test",
        context,
        _valid_request("workflow.post_estimation.joint_f_test"),
        catalog_digest=catalog.catalog_digest,
    )

    assert result["status"] == "completed"
    assert result["artifact_id"] == "artifact:post-estimation"


def test_post_estimation_result_rejects_raw_or_forged_fields() -> None:
    catalog = load_builtin_catalog()
    runtime = compose_builtin_agent_notebook_runtime(
        provider_catalog=catalog,
        evidence_committer=lambda _context, _result: object(),
        host_compiler=CutoverTestHostCompiler(),
        project_ref="project:test",
        session_ref="session:test",
        workflow_post_estimation_execution_port=_port(
            catalog, "workflow.post_estimation.joint_f_test"
        ),
    )
    context = ProviderRuntimeContextV1(
        compilation_record_id="record:test",
        execution_instance_hash="hash:test",
        actor_ref="principal:test",
        session_ref="session:test",
        project_ref="project:test",
        effect="read_only",
    )
    request = {
        "capability_id": "workflow.post_estimation.joint_f_test",
        "target_ref": "run:test",
        "data_snapshot_ref": "artifact:test",
        "source_text_digest": "digest:test",
        "options": {"workflow_draft": {"not": "used by the fake port"}},
    }
    with pytest.raises(TrustedExecutorRegistryError) as caught:
        runtime.runtime_registry.dispatch(
            "executor:workflow.post_estimation.joint_f_test",
            context,
            {**request, "options": {"path": "/tmp/not-accepted"}},
            catalog_digest=catalog.catalog_digest,
        )
    assert caught.value.code == "RUNTIME_UNSAFE_PAYLOAD"


@pytest.mark.skipif(platform.system() != "Darwin", reason="local workflow host is macOS-only")
def test_local_port_requires_a_canonical_workflow_plan(tmp_path) -> None:
    from workbench.agent.workflow_runtime import bootstrap_local_workflow_host

    endpoint = bootstrap_local_workflow_host(tmp_path)
    try:
        port = WorkflowPostEstimationExecutionPortV1.from_local_host(
            project_root=tmp_path,
            workflow_endpoint=endpoint,
            project_ref="project:test",
            session_ref="session:test",
            catalog_digest=load_builtin_catalog().catalog_digest,
        )
        context = ProviderRuntimeContextV1(
            compilation_record_id="record:test",
            execution_instance_hash="hash:test",
            actor_ref="principal:test",
            session_ref="session:test",
            project_ref="project:test",
            effect="read_only",
        )
        with pytest.raises(TrustedExecutorRegistryError, match="WORKFLOW_POST_ESTIMATION_REQUEST_REQUIRED"):
            port.execute(context, {})
    finally:
        endpoint.close()


@pytest.mark.skipif(platform.system() != "Darwin", reason="local workflow host is macOS-only")
def test_local_bundle_bootstrap_installs_available_post_estimation_bindings(tmp_path) -> None:
    from fastapi import FastAPI

    from workbench.services.local_host_bootstrap import bootstrap_local_workbench_host

    bundle = bootstrap_local_workbench_host(
        project_root=tmp_path,
        project_ref="project:test",
        session_ref="session:test",
        actor_ref="principal:test",
        app_instance=FastAPI(),
    )
    try:
        assert bundle.runtime is not None
        for _adapter_id, executor_ref in _ADAPTERS:
            contribution = bundle.runtime.runtime_registry.require(executor_ref)
            assert contribution.execution_allowed is True
            assert contribution.metadata["status"] == "available"
    finally:
        bundle.close()
