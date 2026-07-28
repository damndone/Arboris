from __future__ import annotations

import sys
import hashlib
from pathlib import Path


def _policy():
    from workbench.native_containment.contracts import ResourceBudget
    from workbench.native_containment.policy import ContainmentPolicy

    return ContainmentPolicy(
        profile_id="darwin-seatbelt-experimental-v1",
        filesystem_mode="sealed_readonly",
        network_mode="disabled",
        process_mode="isolated",
        inherited_descriptors=False,
        dependency_tree_writable=False,
        environment_allowlist={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        locale="C.UTF-8",
        thread_count=1,
        budget=ResourceBudget(10_000, 8_000, 64 * 1024 * 1024, 8, 1_000_000, 100_000),
        allow_weaker_fallback=False,
        resource_enforcement="observed_memory",
    )


def _request(policy):
    from workbench.native_containment.contracts import ContainmentRequest

    return ContainmentRequest(
        request_id="request.executor",
        attempt_id="attempt.executor",
        intent_digest="a" * 64,
        input_bundle_ref="b" * 64,
        output_namespace_ref="c" * 64,
        policy_digest=policy.content_digest,
        harness_digest="d" * 64,
    )


def _spec(request, root: Path):
    from workbench.native_containment.executor_darwin import DarwinExecutionSpec

    input_root = root / "input"
    output_root = root / "output"
    input_root.mkdir()
    output_root.mkdir()
    return DarwinExecutionSpec(
        input_bundle_ref=request.input_bundle_ref,
        output_namespace_ref=request.output_namespace_ref,
        executable=Path(sys.executable),
        executable_digest=hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
        arguments=("-I", "-c", "print('ok')"),
        input_root=input_root,
        output_root=output_root,
    )


class _FakeProcess:
    pid = 4242
    returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_experimental_executor_returns_output_bound_to_request_and_canary(tmp_path):
    from workbench.native_containment.executor_darwin import DarwinExperimentalExecutor
    from workbench.native_containment.host import CanaryResult

    policy = _policy()
    request = _request(policy)
    canary = CanaryResult(
        status="supported",
        reason_code="NATIVE_CONTAINMENT_CANARY_PASSED",
    )
    spec = _spec(request, tmp_path)
    calls = []

    def process_factory(argv, **kwargs):
        calls.append((argv, kwargs))
        return _FakeProcess()

    executor = DarwinExperimentalExecutor(
        resolver=lambda current: spec if current == request else None,
        assessment_ref="e" * 64,
        process_factory=process_factory,
        process_snapshot=lambda _pid: None,
    )

    report = executor(request, policy, canary)

    assert report.status == "completed"
    assert report.attempt_id == request.attempt_id
    assert report.request_digest == request.content_digest
    assert report.assessment_ref == "e" * 64
    assert report.output_bundle_ref
    assert calls and calls[0][0][0] == "/usr/bin/sandbox-exec"


def test_experimental_executor_does_not_run_without_supported_canary(tmp_path):
    from workbench.native_containment.executor_darwin import DarwinExperimentalExecutor
    from workbench.native_containment.host import CanaryResult

    policy = _policy()
    request = _request(policy)
    spec = _spec(request, tmp_path)
    calls = []

    executor = DarwinExperimentalExecutor(
        resolver=lambda _current: spec,
        assessment_ref="e" * 64,
        process_factory=lambda *_args, **_kwargs: calls.append(True),
        process_snapshot=lambda _pid: (1, 0),
    )

    report = executor(
        request,
        policy,
        CanaryResult.unsupported("NATIVE_CONTAINMENT_CANARY_FAILED"),
    )

    assert report.status == "unsupported"
    assert report.reason_code == "NATIVE_CONTAINMENT_CANARY_FAILED"
    assert calls == []


def test_experimental_executor_terminates_when_observed_memory_exceeds_budget(tmp_path):
    from workbench.native_containment.executor_darwin import DarwinExperimentalExecutor
    from workbench.native_containment.host import CanaryResult

    policy = _policy()
    request = _request(policy)
    spec = _spec(request, tmp_path)
    process = _FakeProcess()
    process.returncode = None

    executor = DarwinExperimentalExecutor(
        resolver=lambda _current: spec,
        assessment_ref="e" * 64,
        process_factory=lambda *_args, **_kwargs: process,
        process_snapshot=lambda _pid: (1, policy.budget.memory_bytes + 1),
    )

    report = executor(
        request,
        policy,
        CanaryResult(status="supported", reason_code="NATIVE_CONTAINMENT_CANARY_PASSED"),
    )

    assert report.status == "failed"
    assert report.reason_code == "NATIVE_CONTAINMENT_MEMORY_LIMIT_OBSERVED"
    assert process.returncode == -9


def test_experimental_executor_reuses_one_spawned_handle_for_the_same_attempt(tmp_path):
    from workbench.native_containment.executor_darwin import DarwinExperimentalExecutor
    from workbench.native_containment.host import CanaryResult

    policy = _policy()
    request = _request(policy)
    canary = CanaryResult(status="supported", reason_code="NATIVE_CONTAINMENT_CANARY_PASSED")
    spec = _spec(request, tmp_path)
    processes = []

    def process_factory(*_args, **_kwargs):
        process = _FakeProcess()
        processes.append(process)
        return process

    executor = DarwinExperimentalExecutor(
        resolver=lambda _current: spec,
        assessment_ref=canary.content_digest,
        process_factory=process_factory,
        process_snapshot=lambda _pid: None,
    )

    first = executor.spawn(request, policy, canary)
    second = executor.spawn(request, policy, canary)
    report = executor.collect(first)

    assert first is second
    assert first.handle_ref == second.handle_ref
    assert len(processes) == 1
    assert report.status == "completed"


def test_experimental_executor_termination_is_idempotent_and_terminal(tmp_path):
    from workbench.native_containment.executor_darwin import DarwinExperimentalExecutor
    from workbench.native_containment.host import CanaryResult

    policy = _policy()
    request = _request(policy)
    canary = CanaryResult(status="supported", reason_code="NATIVE_CONTAINMENT_CANARY_PASSED")
    spec = _spec(request, tmp_path)
    process = _FakeProcess()
    process.returncode = None
    executor = DarwinExperimentalExecutor(
        resolver=lambda _current: spec,
        assessment_ref=canary.content_digest,
        process_factory=lambda *_args, **_kwargs: process,
        process_snapshot=lambda _pid: (1, 0),
    )

    spawned = executor.spawn(request, policy, canary)
    first = executor.terminate(spawned)
    second = executor.terminate(spawned)

    assert first == second
    assert first.status == "failed"
    assert first.reason_code == "NATIVE_CONTAINMENT_TERMINATED"
    assert process.returncode == -9
