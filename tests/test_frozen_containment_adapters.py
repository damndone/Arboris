"""Pure C2 adapter plans: deny default data only, never backend invocation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from workbench.frozen_containment_adapters import (
    C2AdapterError,
    DescriptorIdentityV1,
    RoleBindingsV1,
    render_bubblewrap_plan,
    render_seatbelt_plan,
    verify_rendered_plan,
)
from workbench.frozen_containment_c2 import HostInstanceFingerprintV1

from test_frozen_containment_c2_policy import _Probe, _policy, _sha


def _descriptor(role: str, fd: int, path: str, *, digest: str, access: str) -> DescriptorIdentityV1:
    return DescriptorIdentityV1(
        role=role,
        descriptor=fd,
        device=1,
        inode=fd + 100,
        absolute_path=path,
        content_sha256=digest,
        access=access,
    )


def _bindings() -> RoleBindingsV1:
    return RoleBindingsV1(
        backend=_descriptor("backend", 10, "/opt/c2/bwrap", digest=_sha("a"), access="execute"),
        python_interpreter=_descriptor("python", 11, "/opt/c2/python", digest=_sha("b"), access="execute"),
        runner=_descriptor("runner", 12, "/opt/c2/runner.py", digest=_sha("c"), access="read"),
        candidate_snapshot=_descriptor("candidate_snapshot", 20, "/private/c2/candidate", digest=_sha("1"), access="read"),
        evaluator_snapshot=_descriptor("evaluator_snapshot", 21, "/private/c2/evaluator", digest=_sha("2"), access="read"),
        runtime_roots=(_descriptor("runtime_root", 22, "/opt/c2/runtime", digest=_sha("d"), access="read"),),
        fixture_roots=(_descriptor("fixture_root", 23, "/opt/c2/fixtures", digest=_sha("e"), access="read"),),
        child_write_root=_descriptor("child_write_root", 24, "/private/c2/output", digest=_sha("f"), access="write"),
        parent_audit_root=_descriptor("parent_audit_root", 25, "/private/c2/audit", digest=_sha("9"), access="unmounted"),
    )


def _admission(*, backend_name: str = "bubblewrap"):
    policy = _policy().validate()
    if backend_name != "bubblewrap":
        policy = replace(policy, supported_hosts=(replace(policy.supported_hosts[0], backend_name=backend_name),)).validate()
    fingerprint = HostInstanceFingerprintV1(
        schema_version="1",
        os_family="Linux",
        os_build="6.8.0-test",
        architecture="x86_64",
        backend_name=backend_name,
        backend_version="1.2.3",
        backend_identity_sha256=_sha("a"),
        feature_flags=("mount_namespace", "network_namespace", "pid_namespace"),
        observed_monotonic_ns=1,
    )
    return policy, policy.admit_host(_Probe(fingerprint))


def test_rendered_seatbelt_starts_deny_default_and_binds_only_explicit_roles() -> None:
    policy, admission = _admission(backend_name="seatbelt")
    plan = render_seatbelt_plan(policy, admission, _bindings())

    assert plan.profile.splitlines()[0] == "(version 1)"
    assert "(deny default)" in plan.profile
    assert "(allow default)" not in plan.profile
    assert '"/"' not in plan.profile
    assert '"/Users/' not in plan.profile
    assert '"/private/c2/audit"' not in plan.profile
    assert '"/private/c2/candidate"' in plan.profile
    assert '"/private/c2/output"' in plan.profile
    assert plan.argv == ("/dev/fd/10", "-p", plan.profile, "--", "/dev/fd/11", "-B", "-I", "-S", "/dev/fd/12")
    assert plan.network_denied is True
    assert len(plan.template_digest) == 64
    assert len(plan.role_bindings_digest) == 64


def test_rendered_bubblewrap_has_empty_namespace_no_root_or_home_bind_and_fixed_argv() -> None:
    policy, admission = _admission()
    plan = render_bubblewrap_plan(policy, admission, _bindings())

    assert plan.argv[:4] == ("/dev/fd/10", "--die-with-parent", "--unshare-all", "--new-session")
    assert plan.argv[-5:] == ("/dev/fd/11", "-B", "-I", "-S", "/dev/fd/12")
    assert plan.network_unshared is True
    assert all(binding.source_path != "/" for binding in plan.mounts)
    assert all(not binding.source_path.startswith(("/Users/", "/home/", "/root/")) for binding in plan.mounts)
    assert {binding.access for binding in plan.mounts} == {"read", "write"}
    assert all(binding.source_path != "/private/c2/audit" for binding in plan.mounts)


def test_renderer_rejects_a_host_admitted_for_a_different_backend() -> None:
    policy, admission = _admission()
    with pytest.raises(C2AdapterError, match="C2_POLICY_BINDING_MISMATCH"):
        render_seatbelt_plan(policy, admission, _bindings())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda bindings: replace(bindings, candidate_snapshot=None),
        lambda bindings: replace(bindings, child_write_root=replace(bindings.child_write_root, descriptor=20)),
        lambda bindings: replace(bindings, fixture_roots=(_descriptor("fixture_root", 23, "/opt/c2/runtime/nested", digest=_sha("e"), access="read"),)),
        lambda bindings: replace(bindings, runtime_roots=(_descriptor("runtime_root", 22, "/", digest=_sha("d"), access="read"),)),
        lambda bindings: replace(bindings, runtime_roots=(_descriptor("runtime_root", 22, "/opt/c2/runtime", digest=_sha("9"), access="read"),)),
        lambda bindings: replace(bindings, parent_audit_root=replace(bindings.parent_audit_root, access="read")),
    ],
)
def test_role_bindings_reject_omitted_duplicate_overlapping_broad_substituted_or_mounted_audit_roles(mutate: object) -> None:
    policy, admission = _admission()
    with pytest.raises(C2AdapterError, match="C2_POLICY_BINDING_MISMATCH"):
        render_bubblewrap_plan(policy, admission, mutate(_bindings()))  # type: ignore[operator]


def test_any_strict_argv_or_binding_digest_difference_is_rejected_before_any_process_creation() -> None:
    policy, admission = _admission()
    plan = render_bubblewrap_plan(policy, admission, _bindings())
    with pytest.raises(C2AdapterError, match="C2_POLICY_BINDING_MISMATCH"):
        verify_rendered_plan(policy, admission, _bindings(), replace(plan, argv=plan.argv + ("--extra",)))
    with pytest.raises(C2AdapterError, match="C2_POLICY_BINDING_MISMATCH"):
        verify_rendered_plan(policy, admission, _bindings(), replace(plan, role_bindings_digest=_sha("8")))


def test_adapter_module_is_pure_and_does_not_expose_backend_invocation() -> None:
    import inspect
    import workbench.frozen_containment_adapters as adapters

    source = inspect.getsource(adapters)
    assert "subprocess" not in source
    assert "Popen(" not in source
    assert not hasattr(adapters, "execute")
