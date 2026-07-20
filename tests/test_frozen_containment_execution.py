"""C2 lifecycle/IPC tests use fake canary and no-op launch adapters only."""

from __future__ import annotations

import json
import struct
from dataclasses import replace

import pytest

from workbench.frozen_containment_canary import CanaryAuditReceiptV1, CanaryOutcomeV1
from workbench.frozen_containment_adapters import render_bubblewrap_plan, render_seatbelt_plan
from workbench.frozen_containment_execution import (
    C2ExecutionRequestV1,
    C2LaunchResultV1,
    C2LifecycleError,
    C2ContainmentExecutor,
    TerminationReportV1,
    _CapabilityRegistry,
)

from test_frozen_containment_adapters import _admission, _bindings
from test_frozen_containment_c2_policy import _sha


def _request(**changes: object) -> C2ExecutionRequestV1:
    values: dict[str, object] = {
        "schema_version": "1",
        "candidate_manifest_sha256": _sha("1"),
        "evaluator_manifest_sha256": _sha("2"),
        "output_root_identity_sha256": _sha("3"),
        "deadline_monotonic_ns": 10_000,
    }
    values.update(changes)
    return C2ExecutionRequestV1(**values)  # type: ignore[arg-type]


def _frame(status: str = "passed") -> bytes:
    encoded = json.dumps({"schema_version": "1", "status": status, "measurements": {}}, sort_keys=True, separators=(",", ":")).encode()
    return struct.pack(">I", len(encoded)) + encoded


class _FakeCanary:
    def __init__(self, outcome: CanaryOutcomeV1 | None = None) -> None:
        self.calls = 0
        self.outcome = outcome

    def verify(self, **kwargs: object) -> CanaryOutcomeV1:
        self.calls += 1
        if self.outcome is not None:
            return self.outcome
        policy = kwargs["policy"]
        admission = kwargs["admission"]
        bindings = kwargs["bindings"]
        plan = render_bubblewrap_plan(policy, admission, bindings) if admission.backend_name == "bubblewrap" else render_seatbelt_plan(policy, admission, bindings)
        return CanaryOutcomeV1(
            passed=True,
            code="C2_CANARY_PASSED",
            audit_receipt=CanaryAuditReceiptV1("1", _sha("4"), policy.policy_digest, plan.template_digest, admission.host_fingerprint_sha256, _sha("8")),
            reason="fake accepted fixture",
        )


class _NoopLaunch:
    def __init__(self, result: C2LaunchResultV1 | None = None) -> None:
        self.calls = 0
        self.result = result or C2LaunchResultV1(
            exit_code=0,
            timed_out=False,
            result_frame=_frame(),
            stdout=b"fixture-output",
            stderr=b"",
            termination=TerminationReportV1(False, False, False, True, True),
        )

    def launch(self, **_kwargs: object) -> C2LaunchResultV1:
        self.calls += 1
        return self.result


def _executor(*, canary: _FakeCanary | None = None, launch: _NoopLaunch | None = None, clock=lambda: 1) -> tuple[C2ContainmentExecutor, _FakeCanary, _NoopLaunch]:
    policy, admission = _admission()
    fake_canary = canary or _FakeCanary()
    noop = launch or _NoopLaunch()
    return (
        C2ContainmentExecutor(policy=policy, admission=admission, bindings=_bindings(), canary_verifier=fake_canary, launch_adapter=noop, monotonic_ns=clock),
        fake_canary,
        noop,
    )


def test_executor_requires_a_fresh_accepted_canary_then_returns_only_untrusted_observation() -> None:
    executor, canary, launch = _executor()
    outcome = executor.execute_c2_request(_request())

    assert canary.calls == 1
    assert launch.calls == 1
    assert outcome.code == "C2_EVALUATOR_NONPASSING"
    assert outcome.verdict == "non_passing"
    assert outcome.observation is not None and outcome.observation.status == "passed"
    assert not hasattr(outcome, "capability")


def test_missing_or_failed_canary_rejects_before_launch() -> None:
    rejected = CanaryOutcomeV1(False, "C2_CANARY_FAILED", None, "fake failed")
    executor, canary, launch = _executor(canary=_FakeCanary(rejected))
    outcome = executor.execute_c2_request(_request())
    assert outcome.code == "C2_CANARY_FAILED"
    assert outcome.verdict == "non_passing"
    assert canary.calls == 1
    assert launch.calls == 0


def test_stale_or_cross_template_canary_receipt_rejects_before_launch() -> None:
    stale = CanaryOutcomeV1(
        True,
        "C2_CANARY_PASSED",
        CanaryAuditReceiptV1("1", _sha("4"), _sha("5"), _sha("6"), _sha("7"), _sha("8")),
        "stale fake receipt",
    )
    executor, _, launch = _executor(canary=_FakeCanary(stale))
    outcome = executor.execute_c2_request(_request())
    assert outcome.code == "C2_CANARY_FAILED"
    assert outcome.verdict == "non_passing"
    assert launch.calls == 0


@pytest.mark.parametrize(
    "result",
    [
        C2LaunchResultV1(0, False, b"", b"", b"", TerminationReportV1(False, False, False, True, True)),
        C2LaunchResultV1(0, False, _frame() + b"x", b"", b"", TerminationReportV1(False, False, False, True, True)),
        C2LaunchResultV1(0, False, struct.pack(">I", 70 * 1024) + b"{}", b"", b"", TerminationReportV1(False, False, False, True, True)),
        C2LaunchResultV1(0, False, _frame(), b"x" * (1024 * 1024 + 1), b"", TerminationReportV1(False, False, False, True, True)),
        C2LaunchResultV1(0, True, _frame(), b"", b"", TerminationReportV1(True, True, True, True, True)),
        C2LaunchResultV1(0, True, _frame(), b"", b"", TerminationReportV1(True, False, True, True, True)),
    ],
)
def test_bad_ipc_stream_or_termination_never_returns_a_passing_verdict(result: C2LaunchResultV1) -> None:
    executor, _, _ = _executor(launch=_NoopLaunch(result))
    outcome = executor.execute_c2_request(_request())
    assert outcome.code == "C2_LIFECYCLE_FAILED"
    assert outcome.verdict == "non_passing"
    assert outcome.observation is None


def test_private_capability_registry_rejects_replay_expiry_and_cross_binding() -> None:
    executor, _, _ = _executor()
    registry = _CapabilityRegistry(monotonic_ns=lambda: 5)
    policy = executor._policy  # test-only inspection of non-exported lifecycle state
    capability = registry.issue(_request(), policy, _sha("a"), _sha("b"), ttl_ns=10)
    assert "token" not in repr(capability)
    registry.consume(capability, _request(), policy, _sha("a"), _sha("b"))
    with pytest.raises(C2LifecycleError, match="C2_CAPABILITY_REJECTED"):
        registry.consume(capability, _request(), policy, _sha("a"), _sha("b"))
    now = [5]
    expired = _CapabilityRegistry(monotonic_ns=lambda: now[0])
    expired_capability = expired.issue(_request(), policy, _sha("a"), _sha("b"), ttl_ns=10)
    now[0] = 20
    with pytest.raises(C2LifecycleError, match="C2_CAPABILITY_REJECTED"):
        expired.consume(expired_capability, _request(), policy, _sha("a"), _sha("b"))
    wrong = _CapabilityRegistry(monotonic_ns=lambda: 5)
    wrong_capability = wrong.issue(_request(), policy, _sha("a"), _sha("b"), ttl_ns=10)
    with pytest.raises(C2LifecycleError, match="C2_CAPABILITY_REJECTED"):
        wrong.consume(wrong_capability, replace(_request(), candidate_manifest_sha256=_sha("9")), policy, _sha("a"), _sha("b"))


def test_request_has_no_raw_command_environment_or_path_surface_and_module_never_starts_processes() -> None:
    fields = set(C2ExecutionRequestV1.__dataclass_fields__)
    assert not fields & {"command", "argv", "environment", "cwd", "path"}
    import inspect
    import workbench.frozen_containment_execution as execution

    source = inspect.getsource(execution)
    assert "subprocess" not in source
    assert "Popen(" not in source
    assert "sys.executable" not in source
    assert "PATH" not in source
