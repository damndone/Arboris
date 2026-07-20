"""C2 canary protocol tests use only a trusted fixture and fake adapter."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from workbench.frozen_containment_canary import (
    CANARY_ASSERTIONS_V1,
    CanaryAdapterResultV1,
    CanaryAuditStore,
    CanaryFixtureV1,
    CanaryObservationV1,
    run_trusted_canary,
)
from workbench.frozen_containment_c2 import HostInstanceFingerprintV1

from test_frozen_containment_adapters import _admission, _bindings
from test_frozen_containment_c2_policy import _Probe, _sha


def _frame(assertions: dict[str, bool] | None = None) -> bytes:
    payload = {
        "schema_version": "1",
        "assertions": assertions or {name: True for name in CANARY_ASSERTIONS_V1},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded


class _FakeAdapter:
    def __init__(self, result: CanaryAdapterResultV1) -> None:
        self.result = result
        self.calls = 0

    def run_trusted_fixture(self, plan: object, fixture: CanaryFixtureV1) -> CanaryAdapterResultV1:
        self.calls += 1
        assert fixture.fixture_id == "c2-trusted-canary-v1"
        return self.result


def _result(**changes: object) -> CanaryAdapterResultV1:
    value: dict[str, object] = {
        "exit_code": 0,
        "timed_out": False,
        "frame": _frame(),
        "stdout": b"trusted-canary-fixture\n",
        "stderr": b"",
    }
    value.update(changes)
    return CanaryAdapterResultV1(**value)  # type: ignore[arg-type]


def _run(tmp_path: Path, result: CanaryAdapterResultV1):
    policy, admission = _admission()
    fingerprint = HostInstanceFingerprintV1(
        schema_version="1",
        os_family="Linux",
        os_build="6.8.0-test",
        architecture="x86_64",
        backend_name="bubblewrap",
        backend_version="1.2.3",
        backend_identity_sha256=_sha("a"),
        feature_flags=("mount_namespace", "network_namespace", "pid_namespace"),
        observed_monotonic_ns=2,
    )
    adapter = _FakeAdapter(result)
    outcome = run_trusted_canary(
        policy=policy,
        admission=admission,
        host_probe=_Probe(fingerprint),
        bindings=_bindings(),
        adapter=adapter,
        fixture=CanaryFixtureV1(fixture_id="c2-trusted-canary-v1", fixture_sha256=_sha("7")),
        audit_store=CanaryAuditStore(tmp_path / "audit"),
    )
    return outcome, adapter


def test_positive_fake_adapter_canary_emits_parent_audit_receipt_not_evaluation_evidence(tmp_path: Path) -> None:
    outcome, adapter = _run(tmp_path, _result())

    assert outcome.passed is True
    assert outcome.code == "C2_CANARY_PASSED"
    assert outcome.audit_receipt is not None
    assert outcome.audit_receipt.host_fingerprint_sha256
    assert outcome.evaluation_evidence is None
    assert adapter.calls == 1
    assert list((tmp_path / "audit").glob("canary-*.json"))


@pytest.mark.parametrize("assertion", CANARY_ASSERTIONS_V1)
def test_each_required_canary_assertion_must_be_true(tmp_path: Path, assertion: str) -> None:
    assertions = {name: True for name in CANARY_ASSERTIONS_V1}
    assertions[assertion] = False
    outcome, _ = _run(tmp_path, _result(frame=_frame(assertions)))

    assert outcome.passed is False
    assert outcome.code == "C2_CANARY_FAILED"
    assert outcome.audit_receipt is None


@pytest.mark.parametrize(
    "result",
    [
        _result(frame=b""),
        _result(frame=_frame() + b"trailing"),
        _result(frame=struct.pack(">I", 70 * 1024) + b"{}"),
        _result(exit_code=1),
        _result(timed_out=True),
        _result(stdout=b"x" * (1024 * 1024 + 1)),
    ],
)
def test_malformed_timeout_nonzero_or_overflow_fake_results_fail_closed(tmp_path: Path, result: CanaryAdapterResultV1) -> None:
    outcome, _ = _run(tmp_path, result)
    assert outcome.passed is False
    assert outcome.code == "C2_CANARY_FAILED"
    assert outcome.audit_receipt is None


def test_missing_or_extra_or_non_boolean_assertion_is_not_a_canary_pass(tmp_path: Path) -> None:
    missing = {name: True for name in CANARY_ASSERTIONS_V1[:-1]}
    extra = {name: True for name in CANARY_ASSERTIONS_V1} | {"unexpected": True}
    non_boolean = {name: True for name in CANARY_ASSERTIONS_V1} | {CANARY_ASSERTIONS_V1[0]: 1}
    for assertions in (missing, extra, non_boolean):
        outcome, _ = _run(tmp_path, _result(frame=_frame(assertions)))
        assert outcome.code == "C2_CANARY_FAILED"


def test_host_drift_rejects_before_fake_adapter_call(tmp_path: Path) -> None:
    policy, admission = _admission()
    drift = HostInstanceFingerprintV1(
        schema_version="1", os_family="Linux", os_build="6.8.1-test", architecture="x86_64",
        backend_name="bubblewrap", backend_version="1.2.3", backend_identity_sha256=_sha("a"),
        feature_flags=("mount_namespace", "network_namespace", "pid_namespace"), observed_monotonic_ns=2,
    )
    adapter = _FakeAdapter(_result())
    outcome = run_trusted_canary(
        policy=policy, admission=admission, host_probe=_Probe(drift), bindings=_bindings(), adapter=adapter,
        fixture=CanaryFixtureV1(fixture_id="c2-trusted-canary-v1", fixture_sha256=_sha("7")),
        audit_store=CanaryAuditStore(tmp_path / "audit"),
    )
    assert outcome.code == "C2_UNSUPPORTED_HOST"
    assert outcome.audit_receipt is None
    assert adapter.calls == 0


def test_audit_store_never_reuses_a_receipt_and_audit_failure_downgrades_to_rejection(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, _result())
    assert outcome.audit_receipt is not None
    # A second identical fact set would collide; it must never copy an old success receipt.
    second, _ = _run(tmp_path, _result())
    assert second.code == "C2_CANARY_FAILED"
    assert second.audit_receipt is None


def test_audit_reread_failure_never_returns_a_synthesized_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.frozen_containment_canary as canary

    monkeypatch.setattr(canary, "_read_no_follow", lambda *_args: b"different")
    outcome, _ = _run(tmp_path, _result())
    assert outcome.passed is False
    assert outcome.code == "C2_CANARY_FAILED"
    assert outcome.audit_receipt is None


def test_canary_module_does_not_import_c1_or_expose_execution_or_capability() -> None:
    import inspect
    import workbench.frozen_containment_canary as canary

    source = inspect.getsource(canary)
    assert "frozen_containment import" not in source
    assert "subprocess" not in source
    assert "Popen(" not in source
    assert not hasattr(canary, "C2ContainmentExecutor")
    assert not any("capability" in name.casefold() for name in dir(canary) if not name.startswith("_"))
