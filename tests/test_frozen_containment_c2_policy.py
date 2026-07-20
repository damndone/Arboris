"""C2 policy and host eligibility are pure pre-launch checks only."""

from __future__ import annotations

from dataclasses import replace

import pytest

from workbench.frozen_containment_c2 import (
    C2PolicyError,
    HostInstanceFingerprintV1,
    RuntimePolicyC2,
    SupportedHostC2,
    TrustedEvaluatorV1,
    TrustedPathIdentityV1,
    TrustedRuntimeFactsV1,
)


def _sha(character: str) -> str:
    return character * 64


def _path(role: str, path: str, *, owner_uid: int = 0, live_repository: bool = False) -> TrustedPathIdentityV1:
    return TrustedPathIdentityV1(
        role=role,
        path=path,
        device=1,
        inode={"backend": 11, "python": 12, "runner": 13, "runtime": 14, "fixture": 15}[role],
        content_sha256=_sha({"backend": "a", "python": "b", "runner": "c", "runtime": "d", "fixture": "e"}[role]),
        owner_uid=owner_uid,
        mode=0o755 if role in {"backend", "python"} else 0o644,
        ancestor_chain_sha256=_sha("f"),
        ancestor_chain_root_owned=True,
        ancestor_chain_group_or_other_writable=False,
        is_symlink=False,
        is_live_repository=live_repository,
    )


def _host(*, backend_identity: str = _sha("a"), backend_version: str = "1.2.3") -> SupportedHostC2:
    return SupportedHostC2(
        os_family="Linux",
        os_build="6.8.0-test",
        architecture="x86_64",
        backend_name="bubblewrap",
        backend_version=backend_version,
        backend_identity_sha256=backend_identity,
        required_features=("mount_namespace", "network_namespace", "pid_namespace"),
    )


def _evaluator() -> TrustedEvaluatorV1:
    return TrustedEvaluatorV1(
        schema_version="1",
        evaluator_tree_sha="1" * 40,
        evaluator_package_sha256=_sha("2"),
        runner_entrypoint_sha256=_sha("c"),
        fixture_manifest_sha256=_sha("e"),
        interpreter_identity_sha256=_sha("b"),
        runtime_manifest_sha256=_sha("d"),
        integration_sha="5" * 40,
    )


def _policy(**changes: object) -> RuntimePolicyC2:
    values: dict[str, object] = {
        "schema_version": "1",
        "policy_id": "strict-evaluator-v1",
        "integration_sha": "5" * 40,
        "supported_hosts": (_host(),),
        "backend": _path("backend", "/opt/c2/bwrap"),
        "python_interpreter": _path("python", "/opt/c2/python"),
        "runner": _path("runner", "/opt/c2/runner.py"),
        "runtime_read_roots": (_path("runtime", "/opt/c2/runtime"),),
        "fixture_read_roots": (_path("fixture", "/opt/c2/fixtures"),),
        "trusted_evaluator": _evaluator(),
        "max_cpu_seconds": 10,
        "max_memory_bytes": 64 * 1024 * 1024,
        "max_file_bytes": 1024 * 1024,
        "max_open_files": 32,
        "max_processes": 1,
        "max_wall_clock_ms": 20_000,
    }
    values.update(changes)
    return RuntimePolicyC2(**values)  # type: ignore[arg-type]


def _fingerprint(**changes: object) -> HostInstanceFingerprintV1:
    values: dict[str, object] = {
        "schema_version": "1",
        "os_family": "Linux",
        "os_build": "6.8.0-test",
        "architecture": "x86_64",
        "backend_name": "bubblewrap",
        "backend_version": "1.2.3",
        "backend_identity_sha256": _sha("a"),
        "feature_flags": ("mount_namespace", "network_namespace", "pid_namespace"),
        "observed_monotonic_ns": 123,
    }
    values.update(changes)
    return HostInstanceFingerprintV1(**values)  # type: ignore[arg-type]


class _Probe:
    def __init__(self, *fingerprints: HostInstanceFingerprintV1) -> None:
        self._fingerprints = iter(fingerprints)

    def probe_host(self) -> HostInstanceFingerprintV1:
        return next(self._fingerprints)


def _facts(policy: RuntimePolicyC2, **changes: object) -> TrustedRuntimeFactsV1:
    facts = TrustedRuntimeFactsV1(
        backend=policy.backend,
        python_interpreter=policy.python_interpreter,
        runner=policy.runner,
        runtime_read_roots=policy.runtime_read_roots,
        fixture_read_roots=policy.fixture_read_roots,
        trusted_evaluator=policy.trusted_evaluator,
    )
    return replace(facts, **changes)


def test_policy_is_immutable_and_has_parent_built_fixed_python_template() -> None:
    policy = _policy().validate()
    assert policy.fixed_python_args == ("-B", "-I", "-S")
    assert policy.template_digest == _policy().validate().template_digest
    with pytest.raises(AttributeError):
        policy.policy_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("probe", "code"),
    [
        (_fingerprint(os_family="Darwin"), "C2_UNSUPPORTED_HOST"),
        (_fingerprint(architecture="aarch64"), "C2_UNSUPPORTED_HOST"),
        (_fingerprint(feature_flags=("mount_namespace",)), "C2_UNSUPPORTED_HOST"),
        (_fingerprint(backend_version="9.9.9"), "C2_TRUST_IDENTITY_MISMATCH"),
        (_fingerprint(backend_identity_sha256=_sha("9")), "C2_TRUST_IDENTITY_MISMATCH"),
    ],
)
def test_host_admission_is_exact_and_returns_structured_prelaunch_codes(
    probe: HostInstanceFingerprintV1, code: str
) -> None:
    with pytest.raises(C2PolicyError, match=code):
        _policy().admit_host(_Probe(probe))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda policy: replace(policy, runtime_read_roots=(_path("runtime", "/"),)),
        lambda policy: replace(policy, runtime_read_roots=(_path("runtime", "/Users/unsafe/runtime"),)),
        lambda policy: replace(policy, runtime_read_roots=(_path("runtime", "/opt/c2/runtime", live_repository=True),)),
        lambda policy: replace(policy, runtime_read_roots=(replace(_path("runtime", "/opt/c2/runtime"), is_symlink=True),)),
        lambda policy: replace(policy, fixture_read_roots=(_path("fixture", "/opt/c2/runtime/nested"),)),
        lambda policy: replace(policy, runtime_read_roots=(_path("runtime", "/opt/c2/runtime", owner_uid=501),)),
        lambda policy: replace(policy, caller_command=("python", "candidate.py")),
        lambda policy: replace(policy, caller_environment={"PYTHONPATH": "/unsafe"}),
    ],
)
def test_invalid_or_ambient_policy_inputs_fail_closed_before_admission(mutate: object) -> None:
    with pytest.raises(C2PolicyError, match="C2_POLICY_INVALID"):
        mutate(_policy()).validate()  # type: ignore[operator]


def test_revalidation_rejects_changed_backend_python_runner_or_parent_chain() -> None:
    policy = _policy().validate()
    for facts in (
        _facts(policy, backend=replace(policy.backend, content_sha256=_sha("9"))),
        _facts(policy, python_interpreter=replace(policy.python_interpreter, content_sha256=_sha("9"))),
        _facts(policy, runner=replace(policy.runner, content_sha256=_sha("9"))),
        _facts(policy, runner=replace(policy.runner, ancestor_chain_sha256=_sha("9"))),
    ):
        with pytest.raises(C2PolicyError, match="C2_TRUST_IDENTITY_MISMATCH"):
            policy.revalidate_trust(facts)


def test_admission_binding_requires_same_policy_template_and_fresh_reprobe() -> None:
    policy = _policy().validate()
    admission = policy.admit_host(_Probe(_fingerprint()))
    assert admission.host_fingerprint_sha256 == _fingerprint().digest
    policy.reprobe_before_launch(_Probe(_fingerprint(observed_monotonic_ns=999)), admission)
    with pytest.raises(C2PolicyError, match="C2_UNSUPPORTED_HOST"):
        policy.reprobe_before_launch(_Probe(_fingerprint(os_build="6.8.1-test")), admission)
    with pytest.raises(C2PolicyError, match="C2_TRUST_IDENTITY_MISMATCH"):
        policy.reprobe_before_launch(_Probe(_fingerprint()), replace(admission, template_digest=_sha("9")))


def test_malformed_probe_and_evaluator_binding_fail_closed() -> None:
    malformed = _fingerprint(backend_identity_sha256="not-a-digest")
    with pytest.raises(C2PolicyError, match="C2_UNSUPPORTED_HOST"):
        _policy().admit_host(_Probe(malformed))
    with pytest.raises(C2PolicyError, match="C2_POLICY_INVALID"):
        _policy(trusted_evaluator=replace(_evaluator(), integration_sha="6" * 40)).validate()
