"""Pure, deny-default C2 profile renderers.

These values are reviewable plans only.  They do not open descriptors, invoke
an OS backend, or create a process.  The renderer accepts only policy-bound
parent descriptor identities, never caller argv, environment, or raw paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re

from .frozen_containment_c2 import HostAdmissionV1, RuntimePolicyC2


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DYNAMIC_ROLES = frozenset({"candidate_snapshot", "evaluator_snapshot", "child_write_root", "parent_audit_root"})
_STATIC_ROLES = frozenset({"backend", "python", "runner", "runtime_root", "fixture_root"})


class C2AdapterError(RuntimeError):
    """A strict rendered profile did not bind exactly to trusted policy facts."""

    def __init__(self, detail: str):
        super().__init__(f"C2_POLICY_BINDING_MISMATCH: {detail}")
        self.code = "C2_POLICY_BINDING_MISMATCH"
        self.detail = detail


def _fail(detail: str) -> None:
    raise C2AdapterError(detail)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class DescriptorIdentityV1:
    """Parent-created descriptor identity; ``absolute_path`` is not caller input."""

    role: str
    descriptor: int
    device: int
    inode: int
    absolute_path: str
    content_sha256: str
    access: str

    def validate(self) -> None:
        if self.role not in _DYNAMIC_ROLES | _STATIC_ROLES:
            _fail("descriptor role is not allowlisted")
        if not isinstance(self.descriptor, int) or isinstance(self.descriptor, bool) or self.descriptor < 0:
            _fail("descriptor number is invalid")
        if not isinstance(self.device, int) or self.device < 0 or not isinstance(self.inode, int) or self.inode <= 0:
            _fail("descriptor device or inode is invalid")
        if not isinstance(self.absolute_path, str) or not self.absolute_path.startswith("/") or "\x00" in self.absolute_path:
            _fail("descriptor path is not an absolute parent identity")
        if str(PurePosixPath(self.absolute_path)) != self.absolute_path or self.absolute_path == "/":
            _fail("descriptor path is broad or non-canonical")
        if self.absolute_path == "/root" or self.absolute_path.startswith(("/Users/", "/home/", "/root/")):
            _fail("descriptor path is a home path")
        if not isinstance(self.content_sha256, str) or not _SHA256.fullmatch(self.content_sha256):
            _fail("descriptor content digest is invalid")
        if self.access not in {"read", "write", "execute", "unmounted"}:
            _fail("descriptor access is invalid")

    @property
    def proc_path(self) -> str:
        self.validate()
        return f"/dev/fd/{self.descriptor}"

    def canonical(self) -> dict[str, object]:
        self.validate()
        return {
            "role": self.role,
            "descriptor": self.descriptor,
            "device": self.device,
            "inode": self.inode,
            "absolute_path": self.absolute_path,
            "content_sha256": self.content_sha256,
            "access": self.access,
        }


@dataclass(frozen=True)
class RoleBindingsV1:
    """Complete role map supplied by a future parent after descriptor creation."""

    backend: DescriptorIdentityV1 | None
    python_interpreter: DescriptorIdentityV1 | None
    runner: DescriptorIdentityV1 | None
    candidate_snapshot: DescriptorIdentityV1 | None
    evaluator_snapshot: DescriptorIdentityV1 | None
    runtime_roots: tuple[DescriptorIdentityV1, ...]
    fixture_roots: tuple[DescriptorIdentityV1, ...]
    child_write_root: DescriptorIdentityV1 | None
    parent_audit_root: DescriptorIdentityV1 | None

    def validate(self, policy: RuntimePolicyC2) -> None:
        policy.validate()
        fixed = (self.backend, self.python_interpreter, self.runner, self.candidate_snapshot, self.evaluator_snapshot, self.child_write_root, self.parent_audit_root)
        if any(value is None for value in fixed):
            _fail("every required role binding must be present")
        assert self.backend and self.python_interpreter and self.runner
        assert self.candidate_snapshot and self.evaluator_snapshot and self.child_write_root and self.parent_audit_root
        if not self.runtime_roots or not self.fixture_roots:
            _fail("runtime and fixture role bindings must be non-empty")
        expected_static = (
            (self.backend, policy.backend, "backend", "execute"),
            (self.python_interpreter, policy.python_interpreter, "python", "execute"),
            (self.runner, policy.runner, "runner", "read"),
        )
        for bound, expected, role, access in expected_static:
            self._validate_static(bound, expected.path, expected.content_sha256, role, access)
        self._validate_static_roots(self.runtime_roots, policy.runtime_read_roots, "runtime_root")
        self._validate_static_roots(self.fixture_roots, policy.fixture_read_roots, "fixture_root")
        self._validate_dynamic(self.candidate_snapshot, "candidate_snapshot", "read")
        self._validate_dynamic(self.evaluator_snapshot, "evaluator_snapshot", "read")
        self._validate_dynamic(self.child_write_root, "child_write_root", "write")
        self._validate_dynamic(self.parent_audit_root, "parent_audit_root", "unmounted")
        all_bindings = self.all_bindings
        identities = {(binding.descriptor, binding.device, binding.inode) for binding in all_bindings}
        descriptors = {binding.descriptor for binding in all_bindings}
        inode_identities = {(binding.device, binding.inode) for binding in all_bindings}
        if len(identities) != len(all_bindings) or len(descriptors) != len(all_bindings) or len(inode_identities) != len(all_bindings):
            _fail("descriptor identity is duplicated across roles")
        mounted = [binding for binding in all_bindings if binding.access != "unmounted"]
        for index, binding in enumerate(mounted):
            for other in mounted[index + 1 :]:
                if _nested_or_equal(binding.absolute_path, other.absolute_path):
                    _fail("mounted descriptor paths overlap or nest")
        if any(_nested_or_equal(self.parent_audit_root.absolute_path, binding.absolute_path) for binding in mounted):
            _fail("parent audit root may not overlap a child-visible role")

    @staticmethod
    def _validate_static(
        bound: DescriptorIdentityV1, expected_path: str, expected_digest: str, role: str, access: str
    ) -> None:
        bound.validate()
        if (bound.role, bound.access, bound.absolute_path, bound.content_sha256) != (role, access, expected_path, expected_digest):
            _fail(f"{role} descriptor differs from policy-bound identity")

    @classmethod
    def _validate_static_roots(cls, bindings: tuple[DescriptorIdentityV1, ...], expected: tuple[object, ...], role: str) -> None:
        if len(bindings) != len(expected):
            _fail(f"{role} binding count differs from policy")
        for bound, trusted in zip(bindings, expected, strict=True):
            cls._validate_static(bound, trusted.path, trusted.content_sha256, role, "read")

    @staticmethod
    def _validate_dynamic(bound: DescriptorIdentityV1, role: str, access: str) -> None:
        bound.validate()
        if bound.role != role or bound.access != access:
            _fail(f"{role} binding has an invalid role or access mode")

    @property
    def all_bindings(self) -> tuple[DescriptorIdentityV1, ...]:
        assert self.backend and self.python_interpreter and self.runner
        assert self.candidate_snapshot and self.evaluator_snapshot and self.child_write_root and self.parent_audit_root
        return (
            self.backend,
            self.python_interpreter,
            self.runner,
            self.candidate_snapshot,
            self.evaluator_snapshot,
            *self.runtime_roots,
            *self.fixture_roots,
            self.child_write_root,
            self.parent_audit_root,
        )

    @property
    def digest(self) -> str:
        return _digest([binding.canonical() for binding in self.all_bindings])


@dataclass(frozen=True)
class MountBindingV1:
    role: str
    source_descriptor: int
    source_path: str
    target_path: str
    access: str


@dataclass(frozen=True)
class SeatbeltPlanV1:
    adapter: str
    policy_digest: str
    template_digest: str
    role_bindings_digest: str
    profile: str
    argv: tuple[str, ...]
    network_denied: bool


@dataclass(frozen=True)
class BubblewrapPlanV1:
    adapter: str
    policy_digest: str
    template_digest: str
    role_bindings_digest: str
    mounts: tuple[MountBindingV1, ...]
    argv: tuple[str, ...]
    network_unshared: bool


def render_seatbelt_plan(policy: RuntimePolicyC2, admission: HostAdmissionV1, bindings: RoleBindingsV1) -> SeatbeltPlanV1:
    _validate_inputs(policy, admission, bindings, "seatbelt")
    assert bindings.backend and bindings.python_interpreter and bindings.runner
    read_bindings = tuple(binding for binding in bindings.all_bindings if binding.access in {"read", "execute"})
    profile_lines = ["(version 1)", "(deny default)", "(deny network*)"]
    profile_lines.extend(f'(allow file-read* (literal "{binding.absolute_path}"))' for binding in read_bindings)
    profile_lines.append(f'(allow file-write* (literal "{bindings.child_write_root.absolute_path}"))')  # type: ignore[union-attr]
    profile = "\n".join(profile_lines)
    argv = (
        bindings.backend.proc_path,
        "-p",
        profile,
        "--",
        bindings.python_interpreter.proc_path,
        *policy.fixed_python_args,
        bindings.runner.proc_path,
    )
    return SeatbeltPlanV1(
        adapter="seatbelt",
        policy_digest=policy.policy_digest,
        template_digest=_plan_template_digest(policy, admission, bindings, "seatbelt"),
        role_bindings_digest=bindings.digest,
        profile=profile,
        argv=argv,
        network_denied=True,
    )


def render_bubblewrap_plan(policy: RuntimePolicyC2, admission: HostAdmissionV1, bindings: RoleBindingsV1) -> BubblewrapPlanV1:
    _validate_inputs(policy, admission, bindings, "bubblewrap")
    assert bindings.backend and bindings.python_interpreter and bindings.runner
    mounts = tuple(_mount(binding) for binding in bindings.all_bindings if binding.access != "unmounted")
    argv: list[str] = [bindings.backend.proc_path, "--die-with-parent", "--unshare-all", "--new-session", "--unshare-net"]
    for mount in mounts:
        argv.extend(("--bind" if mount.access == "write" else "--ro-bind", mount.source_path, mount.target_path))
    argv.extend(("--", bindings.python_interpreter.proc_path, *policy.fixed_python_args, bindings.runner.proc_path))
    return BubblewrapPlanV1(
        adapter="bubblewrap",
        policy_digest=policy.policy_digest,
        template_digest=_plan_template_digest(policy, admission, bindings, "bubblewrap"),
        role_bindings_digest=bindings.digest,
        mounts=mounts,
        argv=tuple(argv),
        network_unshared=True,
    )


def verify_rendered_plan(
    policy: RuntimePolicyC2, admission: HostAdmissionV1, bindings: RoleBindingsV1, plan: SeatbeltPlanV1 | BubblewrapPlanV1
) -> None:
    if isinstance(plan, SeatbeltPlanV1):
        expected: SeatbeltPlanV1 | BubblewrapPlanV1 = render_seatbelt_plan(policy, admission, bindings)
    elif isinstance(plan, BubblewrapPlanV1):
        expected = render_bubblewrap_plan(policy, admission, bindings)
    else:
        _fail("rendered plan type is not allowlisted")
    if plan != expected:
        _fail("rendered strict plan differs from the policy-bound template")


def _validate_inputs(policy: RuntimePolicyC2, admission: HostAdmissionV1, bindings: RoleBindingsV1, adapter: str) -> None:
    policy.validate()
    if not isinstance(admission, HostAdmissionV1) or (
        admission.policy_digest != policy.policy_digest or admission.template_digest != policy.template_digest
    ):
        _fail("host admission is not bound to the exact policy template")
    if admission.backend_name != adapter:
        _fail("host admission backend does not match the requested strict renderer")
    bindings.validate(policy)


def _mount(binding: DescriptorIdentityV1) -> MountBindingV1:
    target = "/roles/" + binding.role
    return MountBindingV1(
        role=binding.role,
        source_descriptor=binding.descriptor,
        source_path=binding.absolute_path,
        target_path=target,
        access="write" if binding.access == "write" else "read",
    )


def _plan_template_digest(policy: RuntimePolicyC2, admission: HostAdmissionV1, bindings: RoleBindingsV1, adapter: str) -> str:
    return _digest(
        {
            "adapter": adapter,
            "policy_digest": policy.policy_digest,
            "generic_template_digest": policy.template_digest,
            "host_fingerprint_sha256": admission.host_fingerprint_sha256,
            "role_bindings_digest": bindings.digest,
            "fixed_python_args": list(policy.fixed_python_args),
        }
    )


def _nested_or_equal(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    return left_parts[: len(right_parts)] == right_parts or right_parts[: len(left_parts)] == left_parts


__all__ = [
    "BubblewrapPlanV1",
    "C2AdapterError",
    "DescriptorIdentityV1",
    "MountBindingV1",
    "RoleBindingsV1",
    "SeatbeltPlanV1",
    "render_bubblewrap_plan",
    "render_seatbelt_plan",
    "verify_rendered_plan",
]
