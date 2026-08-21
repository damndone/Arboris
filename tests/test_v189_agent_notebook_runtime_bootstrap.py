from __future__ import annotations

from collections.abc import Mapping
import time

import pytest
import pandas as pd
from fastapi import FastAPI

from workbench.agent.cutover_runtime import EvidenceCommitReceiptV1
from workbench.agent.runtime_bootstrap import (
    RuntimeBootstrapError,
    build_builtin_runtime_contributions,
    compose_builtin_agent_notebook_runtime,
)
from workbench.app import (
    bootstrap_builtin_agent_notebook_runtime,
)
from workbench.canonical import sha256_canonical
from workbench.providers.catalog import load_builtin_catalog
from tests.v189_cutover_test_host import CutoverTestHostCompiler


def _evidence_committer(context: object, result: Mapping[str, object]) -> EvidenceCommitReceiptV1:
    return EvidenceCommitReceiptV1(
        evidence_ref="evidence:runtime-bootstrap:test",
        evidence_digest=sha256_canonical(
            {
                "execution_instance_hash": context.execution_instance_hash,
                "result": dict(result),
            }
        ),
        compilation_record_id=context.compilation_record_id,
        execution_instance_hash=context.execution_instance_hash,
        actor_ref=context.actor_ref,
        session_ref=context.session_ref,
        project_ref=context.project_ref,
    )


def _server_classification_execution_port(
    *,
    catalog,
    project_ref: str,
    session_ref: str,
    snapshot_ref: str,
    input_ref: str,
    model_id: str = "logistic_regression",
    actor_ref: str = "principal:runtime-natural-language",
):
    import workbench.predictive_research.classification_adapters as module
    from workbench.predictive_research.classification_adapters import (
        ClassificationExecutionPortV1,
        ClassificationInputV1,
    )

    typed_input = ClassificationInputV1.from_server(
        input_ref=input_ref,
        catalog_digest=catalog.catalog_digest,
        actor_ref=actor_ref,
        project_ref=project_ref,
        session_ref=session_ref,
        snapshot_ref=snapshot_ref,
        model_id=model_id,
        expires_at=time.time() + 60.0,
        _issuer=module._CLASSIFICATION_SERVER_OWNED_ISSUER,
    )
    features = pd.DataFrame(
        {
            "x1": [0.0, 0.2, 1.0, 1.2, 0.1, 1.1],
            "x2": [1.0, 1.2, 0.0, 0.2, 0.8, 0.1],
        }
    )
    target = pd.Series([0, 0, 1, 1, 0, 1])
    return ClassificationExecutionPortV1.from_server(
        typed_input,
        catalog_digest=catalog.catalog_digest,
        resolver=lambda _input: (features, target),
        _issuer=module._CLASSIFICATION_SERVER_OWNED_ISSUER,
    )


def test_builtin_runtime_contribution_set_matches_every_live_declaration() -> None:
    catalog = load_builtin_catalog()

    contributions = build_builtin_runtime_contributions(catalog)

    expected = {
        declaration.executor_ref
        for provider in catalog.providers
        for declaration in provider.adapter_declarations
    }
    assert {contribution.executor_ref for contribution in contributions} == expected
    assert all(contribution.owner.startswith("workbench.server") for contribution in contributions)


def test_builtin_runtime_composition_binds_the_exact_catalog() -> None:
    catalog = load_builtin_catalog()

    runtime = compose_builtin_agent_notebook_runtime(
        provider_catalog=catalog,
        evidence_committer=_evidence_committer,
        host_compiler=CutoverTestHostCompiler(),
    )

    assert runtime.provider_catalog is catalog
    assert runtime.catalog.provider_catalog_digest == catalog.catalog_digest
    assert runtime.runtime_registry.executor_refs


def test_low_level_runtime_composition_rejects_a_forged_catalog_clone() -> None:
    from workbench.agent.cutover_runtime import compose_agent_notebook_runtime
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    catalog = load_builtin_catalog()
    forged = catalog._replace(catalog_digest="f" * 64)

    with pytest.raises(TrustedExecutorRegistryError, match="catalog"):
        compose_agent_notebook_runtime(
            provider_catalog=forged,
            contributions=build_builtin_runtime_contributions(catalog),
            evidence_committer=_evidence_committer,
            host_compiler=CutoverTestHostCompiler(),
        )


def test_builtin_runtime_composition_accepts_only_the_server_data_execution_port() -> None:
    import workbench.data_operation_manifest as manifest_module
    from workbench.data_operation_manifest import (
        DataConsumerExecutionPortV1,
        DataConsumerRuntimeOutputV1,
    )

    catalog = load_builtin_catalog()
    output = DataConsumerRuntimeOutputV1.from_server(
        record_id="record:bootstrap-data",
        operation_id="data.sort",
        operation_version="v1",
        execution_key="execution:bootstrap-data",
        child_node_id="node:bootstrap-data",
        artifact_ids=("artifact:bootstrap-data",),
        evidence_digest="b" * 64,
        catalog_digest=catalog.catalog_digest,
        _issuer=manifest_module._SERVER_OWNED_ISSUER,
    )
    port = DataConsumerExecutionPortV1.from_server(
        lambda _context, _request: output,
        catalog_digest=catalog.catalog_digest,
        _issuer=manifest_module._SERVER_OWNED_ISSUER,
    )

    runtime = compose_builtin_agent_notebook_runtime(
        provider_catalog=catalog,
        evidence_committer=_evidence_committer,
        host_compiler=CutoverTestHostCompiler(),
        data_consumer_execution_port=port,
    )

    contribution = runtime.runtime_registry.require(
        "executor:workbench.data_consumer.adapter"
    )
    assert contribution.execution_allowed is True
    assert contribution.metadata["status"] == "available"


@pytest.mark.parametrize("missing", ("evidence", "host"))
def test_builtin_runtime_bootstrap_requires_host_authority(missing: str) -> None:
    catalog = load_builtin_catalog()
    kwargs = {
        "provider_catalog": catalog,
        "evidence_committer": _evidence_committer,
        "host_compiler": CutoverTestHostCompiler(),
    }
    kwargs["evidence_committer" if missing == "evidence" else "host_compiler"] = None

    with pytest.raises(RuntimeBootstrapError):
        compose_builtin_agent_notebook_runtime(**kwargs)


def test_app_bootstrap_installs_one_runtime_bundle_for_the_exact_scope() -> None:
    host_app = FastAPI()
    runtime = bootstrap_builtin_agent_notebook_runtime(
        project_ref="project:runtime-bootstrap",
        session_ref="session:runtime-bootstrap",
        provider_catalog=load_builtin_catalog(),
        evidence_committer=_evidence_committer,
        host_compiler=CutoverTestHostCompiler(),
        app_instance=host_app,
    )

    assert host_app.state.agent_notebook_cutover_store.authorities[
        ("project:runtime-bootstrap", "session:runtime-bootstrap")
    ] is runtime.compiler


def test_app_bootstrap_can_install_the_server_owned_durable_data_resolver(tmp_path) -> None:
    host_app = FastAPI()
    runtime = bootstrap_builtin_agent_notebook_runtime(
        project_ref="project:runtime-data-host",
        session_ref="session:runtime-data-host",
        provider_catalog=load_builtin_catalog(),
        evidence_committer=_evidence_committer,
        host_compiler=CutoverTestHostCompiler(),
        data_project_root=tmp_path,
        app_instance=host_app,
    )

    contribution = runtime.runtime_registry.require(
        "executor:workbench.data_consumer.adapter"
    )
    assert contribution.execution_allowed is True
    assert contribution.metadata["status"] == "available"
    assert contribution.metadata["reason_code"] == "DATA_CONSUMER_EXECUTED"


def test_bootstrapped_builtin_runtime_compiles_and_executes_classification_after_confirmation(
    tmp_path,
) -> None:
    host_app = FastAPI()
    catalog = load_builtin_catalog()
    runtime = bootstrap_builtin_agent_notebook_runtime(
        project_ref="project:runtime-natural-language",
        session_ref="session:runtime-natural-language",
        provider_catalog=catalog,
        evidence_committer=_evidence_committer,
        host_compiler=CutoverTestHostCompiler(),
        classification_execution_port=_server_classification_execution_port(
            catalog=catalog,
            project_ref="project:runtime-natural-language",
            session_ref="session:runtime-natural-language",
            snapshot_ref="dataset:snapshot:runtime-natural-language",
            input_ref="dataset:snapshot:runtime-natural-language",
        ),
        app_instance=host_app,
    )
    fields = {
        "capability_id": "workbench.classification_ml.capability",
        "target_ref": "dataset:runtime-natural-language",
        "data_snapshot_ref": "dataset:snapshot:runtime-natural-language",
        "data_snapshot_digest": "c" * 64,
        "requested_effect": "read",
        "sensitivity": "public",
        "options": {"model_id": "logistic_regression"},
    }

    agent = runtime.compiler.compile_natural_language(
        "请对 dataset:runtime-natural-language 做分类分析",
        actor_ref="principal:runtime-natural-language",
        session_ref="session:runtime-natural-language",
        project_ref="project:runtime-natural-language",
        normalized_fields=fields,
        entrypoint="agent",
    )
    notebook = runtime.compiler.compile_natural_language(
        "请对 dataset:runtime-natural-language 做分类分析",
        actor_ref="principal:runtime-natural-language",
        session_ref="session:runtime-natural-language",
        project_ref="project:runtime-natural-language",
        normalized_fields=fields,
        entrypoint="notebook",
    )

    assert host_app.state.agent_notebook_cutover_store.authorities[
        ("project:runtime-natural-language", "session:runtime-natural-language")
    ] is runtime.compiler
    assert agent.semantic_plan_hash == notebook.semantic_plan_hash
    assert agent.compilation_record_id != notebook.compilation_record_id
    assert agent.plan_diff["entrypoint"] == "agent"
    assert notebook.plan_diff["entrypoint"] == "notebook"

    record = runtime.compiler.record(agent.compilation_record_id)
    proposal_store = runtime.compiler.server_proposal_store(tmp_path / "proposals")
    proposal = proposal_store.create(
        session_id=record.session_ref,
        chain_id="chain:runtime-natural-language",
        operation_id="model.rerun",
        target={"run_id": "run:runtime-natural-language"},
        preconditions={
            "server_compilation": {
                "compilation_record_id": record.record_id,
                "confirmation_id": "confirmation:runtime-natural-language",
                "actor_ref": record.principal_ref,
                "session_ref": record.session_ref,
                "project_ref": record.project_ref,
                "semantic_plan_hash": record.semantic_plan_hash,
                "target": {"run_id": "run:runtime-natural-language"},
                "chain_id": "chain:runtime-natural-language",
                "operation_id": "model.rerun",
            }
        },
        changes={},
        evidence_refs=(),
        expected_effect=("read",),
        risks=(),
    )
    runtime.compiler.bind_persisted_proposal(
        record.record_id,
        proposal_store,
        proposal.proposal_id,
    )
    confirmation = runtime.compiler.confirm(record.record_id)
    execution = runtime.compiler.execute(record.record_id, confirmation)

    assert execution.status == "completed"
    assert execution.result["model_id"] == "logistic_regression"
    assert execution.evidence_refs == ("evidence:runtime-bootstrap:test",)
