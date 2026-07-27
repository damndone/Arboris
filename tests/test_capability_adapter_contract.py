from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import subprocess
import sys

import pytest


def _implementation():
    from workbench.capability_factory.contracts import (
        CapabilityRequirementRevision,
        ImplementationRevision,
        SemanticProfile,
    )

    profile = SemanticProfile(
        profile_id="profile.generic",
        revision=1,
        input_kinds=("table", "numeric"),
        operations=("fit", "predict", "summarize"),
        output_facets=("parameters", "uncertainty", "predictions"),
        assumptions=("finite_inputs",),
        consumers={
            "report_projection": "report.generic.v1",
            "diagnostic_adapter": "diagnostic.generic.v1",
            "figure_provider": None,
            "compare_adapter": None,
        },
    )
    requirement = CapabilityRequirementRevision(
        requirement_id="requirement.generic",
        revision=1,
        semantic_profile=profile,
        requested_operations=("fit", "summarize"),
        requested_consumers=("report_projection",),
        input_schema={"response": "numeric", "features": "table"},
    )
    return ImplementationRevision(
        implementation_id="implementation.generic",
        revision=1,
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        profile_digest=profile.content_digest,
        input_schema_digest=requirement.input_schema_digest,
        source_kind="generated_adapter",
        trust_tier="generated_adapter",
        operations=("fit", "predict", "summarize"),
        consumer_support={
            "report_projection": "report.generic.v1",
            "diagnostic_adapter": "diagnostic.generic.v1",
            "figure_provider": None,
            "compare_adapter": None,
        },
        artifact_ref="a" * 64,
    )


def _consumer_support():
    return {
        "report_projection": "adapter.report.v1",
        "diagnostic_adapter": None,
        "figure_provider": None,
        "compare_adapter": None,
    }


def test_adapter_contract_binds_profile_schema_operations_and_consumers_explicitly():
    from workbench.capability_factory.adapter_contract import AdapterContract

    implementation = _implementation()
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.generic",
        revision=1,
        entrypoint_ref="b" * 64,
        operations=("fit", "summarize"),
        consumer_support=_consumer_support(),
    )

    assert adapter.implementation_ref == implementation.content_digest
    assert adapter.profile_digest == implementation.profile_digest
    assert adapter.input_schema_digest == implementation.input_schema_digest
    assert adapter.operations == ("fit", "summarize")
    assert adapter.consumer_support["diagnostic_adapter"] is None
    adapter.validate_against(implementation)
    with pytest.raises(FrozenInstanceError):
        adapter.revision = 2


def test_adapter_contract_rejects_mismatched_bindings_and_missing_consumer_slots():
    from workbench.capability_factory.adapter_contract import AdapterContract, AdapterContractError

    implementation = _implementation()
    with pytest.raises(AdapterContractError, match="profile"):
        AdapterContract(
            adapter_id="adapter.generic",
            revision=1,
            implementation_ref=implementation.content_digest,
            profile_id="profile.other",
            profile_revision=implementation.profile_revision,
            profile_digest=implementation.profile_digest,
            input_schema_digest=implementation.input_schema_digest,
            source_kind=implementation.source_kind,
            trust_tier=implementation.trust_tier,
            operations=("fit",),
            consumer_support=_consumer_support(),
            entrypoint_ref="b" * 64,
        ).validate_against(implementation)

    with pytest.raises(AdapterContractError, match="consumer_support"):
        AdapterContract.from_implementation(
            implementation=implementation,
            adapter_id="adapter.incomplete",
            revision=1,
            entrypoint_ref="b" * 64,
            operations=("fit",),
            consumer_support={
                "report_projection": "adapter.report.v1",
                "diagnostic_adapter": None,
                "figure_provider": None,
            },
        )


def test_adapter_contract_cannot_claim_an_undeclared_operation_or_consumer():
    from workbench.capability_factory.adapter_contract import AdapterContract, AdapterContractError

    implementation = _implementation()
    with pytest.raises(AdapterContractError, match="operations"):
        AdapterContract.from_implementation(
            implementation=implementation,
            adapter_id="adapter.invalid-operation",
            revision=1,
            entrypoint_ref="b" * 64,
            operations=("fit", "diagnose"),
            consumer_support=_consumer_support(),
        )

    unsupported = dict(_consumer_support())
    unsupported["figure_provider"] = "adapter.figure.v1"
    implementation_without_figure = _implementation()
    with pytest.raises(AdapterContractError, match="figure_provider"):
        AdapterContract.from_implementation(
            implementation=implementation_without_figure,
            adapter_id="adapter.invalid-consumer",
            revision=1,
            entrypoint_ref="b" * 64,
            operations=("fit",),
            consumer_support=unsupported,
        )


def test_adapter_candidate_factory_emits_typed_candidate_and_empty_validation_bundle(tmp_path):
    from workbench.capability_factory.adapter_contract import (
        AdapterCandidateFactory,
        AdapterSourceGenerator,
    )
    from workbench.capability_factory.validation_contract import ValidationCase

    implementation = _implementation()
    source = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=lambda _context: "def adapter():\n    return None\n",
        output_root=tmp_path / "source",
    )
    generated = AdapterCandidateFactory().generate(
        implementation=implementation,
        adapter_id="adapter.generated",
        adapter_revision=1,
        entrypoint_ref=source.entrypoint_ref,
        operations=("fit", "summarize"),
        consumer_support=_consumer_support(),
        candidate_id="candidate.generated",
        capability_kind="model",
        source_ref=source.source_ref,
        author_lineage_ref="d" * 64,
        validation_bundle_id="validation.generated",
        validation_cases=(
            ValidationCase(
                case_id="case.generated.1",
                fixture_ref="e" * 64,
                fixture_visibility="author_visible",
            ),
        ),
        source_artifact=source,
    )

    assert generated.candidate.source_kind == "generated_adapter"
    assert generated.candidate.status == "submitted"
    assert generated.validation_bundle.evidence == ()
    assert generated.validation_bundle.adapter_ref == generated.adapter.content_digest
    assert generated.promotion_state == "experimental"
    assert generated.source_eligible is False
    assert generated.execution_allowed is False


def test_adapter_candidate_factory_rejects_a_fabricated_source_reference():
    from workbench.capability_factory.adapter_contract import AdapterCandidateFactory, AdapterContractError
    from workbench.capability_factory.validation_contract import ValidationCase

    implementation = _implementation()
    with pytest.raises(AdapterContractError, match="source_artifact is required"):
        AdapterCandidateFactory().generate(
            implementation=implementation,
            adapter_id="adapter.unbound-source",
            adapter_revision=1,
            entrypoint_ref="b" * 64,
            operations=("fit",),
            consumer_support=_consumer_support(),
            candidate_id="candidate.unbound-source",
            capability_kind="model",
            source_ref="c" * 64,
            author_lineage_ref="d" * 64,
            validation_bundle_id="validation.unbound-source",
            validation_cases=(
                ValidationCase(
                    case_id="case.unbound-source",
                    fixture_ref="e" * 64,
                    fixture_visibility="author_visible",
                ),
            ),
        )


def test_adapter_candidate_factory_binds_generated_source_and_entrypoint(tmp_path):
    from workbench.capability_factory.adapter_contract import (
        AdapterCandidateFactory,
        AdapterSourceGenerator,
    )

    from workbench.capability_factory.validation_contract import ValidationCase

    implementation = _implementation()
    source = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=lambda _context: "def adapter():\n    return None\n",
        output_root=tmp_path / "source",
    )
    cases = (
        ValidationCase(
            case_id="case.bound-source",
            fixture_ref="8" * 64,
            fixture_visibility="author_visible",
        ),
    )
    generated = AdapterCandidateFactory().generate(
        implementation=implementation,
        adapter_id="adapter.bound-source",
        adapter_revision=1,
        entrypoint_ref=source.entrypoint_ref,
        operations=("fit",),
        consumer_support=_consumer_support(),
        candidate_id="candidate.bound-source",
        capability_kind="custom.model",
        source_ref=source.source_ref,
        author_lineage_ref="9" * 64,
        validation_bundle_id="validation.bound-source",
        validation_cases=cases,
        source_artifact=source,
    )

    assert generated.candidate.source_ref == source.source_ref
    assert generated.adapter.entrypoint_ref == source.entrypoint_ref
    assert generated.execution_allowed is False


def test_adapter_source_generator_stores_bounded_agent_output_without_executing_it(tmp_path):
    from workbench.capability_factory.adapter_contract import AdapterSourceGenerator

    implementation = _implementation()
    seen = []

    def provider(context):
        seen.append(context)
        return "def fit(input_bundle, parameters):\n    return None\n"

    artifact = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=provider,
        output_root=tmp_path,
    )

    assert artifact.path.read_text(encoding="utf-8").startswith("def fit")
    assert artifact.path.name == f"{artifact.source_ref}.py"
    assert artifact.source_ref != artifact.entrypoint_ref
    assert seen == [
        {
            "profile_ref": implementation.profile_digest,
            "input_schema_ref": implementation.input_schema_digest,
            "operations": list(implementation.operations),
            "implementation_ref": implementation.content_digest,
        }
    ]


def test_adapter_contract_never_grants_execution_capability():
    from workbench.capability_factory.adapter_contract import AdapterContract

    implementation = _implementation()
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.execution-closed",
        revision=1,
        entrypoint_ref="f" * 64,
        operations=("fit",),
        consumer_support=_consumer_support(),
    )

    assert adapter.execution_allowed is False


def test_python_adapter_binding_prepares_a_digest_bound_offline_invocation(tmp_path):
    from workbench.capability_factory.adapter_contract import (
        AdapterContract,
        AdapterSourceGenerator,
        PythonAdapterExecutionBinding,
    )
    from workbench.native_containment.contracts import ContainmentRequest, ResourceBudget
    from workbench.native_containment.policy import ContainmentPolicy

    implementation = _implementation()
    source = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=lambda _context: (
            "def adapter(request):\n"
            "    return {'operation': request['operation'], 'ok': True}\n"
        ),
        output_root=tmp_path / "source",
    )
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.runtime",
        revision=1,
        entrypoint_ref=source.entrypoint_ref,
        operations=("fit",),
        consumer_support=_consumer_support(),
    )
    binding = PythonAdapterExecutionBinding(
        bundle_ref="1" * 64,
        output_namespace_ref="2" * 64,
        adapter=adapter,
        source_artifact=source,
        operation="fit",
        payload={"value": 3},
        input_root=tmp_path / "input",
        output_root=tmp_path / "output",
        interpreter=Path(sys.executable),
    )
    policy = ContainmentPolicy(
        profile_id="darwin-seatbelt-experimental-v1",
        filesystem_mode="sealed_readonly",
        network_mode="disabled",
        process_mode="isolated",
        inherited_descriptors=False,
        dependency_tree_writable=False,
        environment_allowlist={"LANG": "C.UTF-8"},
        locale="C.UTF-8",
        thread_count=1,
        budget=ResourceBudget(10_000, 8_000, 64 * 1024 * 1024, 8, 1_000_000, 100_000),
        allow_weaker_fallback=False,
        resource_enforcement="observed_memory",
    )
    request = ContainmentRequest(
        request_id="request.adapter.runtime",
        attempt_id="attempt.adapter.runtime",
        intent_digest="3" * 64,
        input_bundle_ref=binding.bundle_ref,
        output_namespace_ref=binding.output_namespace_ref,
        policy_digest=policy.content_digest,
        harness_digest="4" * 64,
    )

    spec = binding.prepare(request)

    assert spec.input_root == binding.input_root
    assert spec.output_root == binding.output_root
    assert spec.executable == Path(sys.executable).resolve()
    assert spec.arguments[0:2] == ("-I", "-c")
    assert source.source_ref in spec.arguments[3]
    assert (binding.input_root / f"{source.source_ref}.py").read_bytes() == source.path.read_bytes()
    assert '"operation":"fit"' in (binding.input_root / "request.json").read_text()
    completed = subprocess.run(
        [str(spec.executable), *spec.arguments],
        cwd=spec.output_root,
        env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        check=False,
    )
    assert completed.returncode == 0
    assert (binding.result_path).read_text(encoding="utf-8") == '{"ok":true,"operation":"fit"}'


def test_python_adapter_gateway_rejects_invalid_adapter_output_without_fallback(tmp_path):
    from types import SimpleNamespace

    from workbench.capability_factory.adapter_contract import (
        AdapterContract,
        AdapterSourceGenerator,
        PythonAdapterExecutionBinding,
        PythonAdapterExecutionGateway,
    )
    from workbench.native_containment.contracts import ContainmentReport, ContainmentRequest, ResourceBudget
    from workbench.native_containment.host import CanaryResult
    from workbench.native_containment.policy import ContainmentPolicy

    implementation = _implementation()
    source = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=lambda _context: "def adapter(request):\n    return {'ok': True}\n",
        output_root=tmp_path / "source",
    )
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.gateway",
        revision=1,
        entrypoint_ref=source.entrypoint_ref,
        operations=("fit",),
        consumer_support=_consumer_support(),
    )
    binding = PythonAdapterExecutionBinding(
        bundle_ref="5" * 64,
        output_namespace_ref="6" * 64,
        adapter=adapter,
        source_artifact=source,
        operation="fit",
        payload={},
        input_root=tmp_path / "input",
        output_root=tmp_path / "output",
        interpreter=Path(sys.executable),
    )
    policy = ContainmentPolicy(
        profile_id="darwin-seatbelt-experimental-v1",
        filesystem_mode="sealed_readonly",
        network_mode="disabled",
        process_mode="isolated",
        inherited_descriptors=False,
        dependency_tree_writable=False,
        environment_allowlist={"LANG": "C.UTF-8"},
        locale="C.UTF-8",
        thread_count=1,
        budget=ResourceBudget(10_000, 8_000, 64 * 1024 * 1024, 8, 1_000_000, 100_000),
        allow_weaker_fallback=False,
        resource_enforcement="observed_memory",
    )
    request = ContainmentRequest(
        request_id="request.adapter.gateway",
        attempt_id="attempt.adapter.gateway",
        intent_digest="7" * 64,
        input_bundle_ref=binding.bundle_ref,
        output_namespace_ref=binding.output_namespace_ref,
        policy_digest=policy.content_digest,
        harness_digest="8" * 64,
    )
    canary = CanaryResult(status="supported", reason_code="NATIVE_CONTAINMENT_CANARY_PASSED")
    binding.prepare(request)

    class StubExecutor:
        def __call__(self, current_request, _policy, _canary):
            binding.result_path.write_text("[]", encoding="utf-8")
            return ContainmentReport(
                attempt_id=current_request.attempt_id,
                request_digest=current_request.content_digest,
                status="completed",
                reason_code="NATIVE_CONTAINMENT_COMPLETED",
                assessment_ref="9" * 64,
                output_bundle_ref="a" * 64,
            )

        def spawn(self, *_args):
            return SimpleNamespace(handle_ref="handle.gateway")

        def terminate(self, *_args):
            return None

    report = PythonAdapterExecutionGateway(binding=binding, executor=StubExecutor())(
        request, policy, canary
    )

    assert report.status == "failed"
    assert report.reason_code == "NATIVE_CONTAINMENT_ADAPTER_OUTPUT_INVALID"
    assert report.output_bundle_ref is None
