"""C1 frozen containment: source attribution and static refusal only.

These tests deliberately do not run a candidate.  A passing test here proves
only that the parent can freeze trusted Git content and refuses unsupported
execution hosts; it is never candidate or release evidence.
"""

from __future__ import annotations

import io
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from workbench.frozen_containment import (
    FrozenContainmentService,
    FrozenMaterializationError,
    FrozenMaterializer,
    RuntimePolicy,
    RuntimePolicyError,
    StaticContainmentRejection,
    SupportedHost,
    discover_containment_backend,
    extract_frozen_archive,
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
    )
    return completed.stdout.strip()


def _trusted_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "trusted"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Containment tests")
    (repo / "source.py").write_text("VALUE = 'from-git'\n", encoding="utf-8")
    (repo / "nested").mkdir()
    (repo / "nested" / "fixture.txt").write_text("frozen\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "frozen input")
    return repo, _git(repo, "rev-parse", "HEAD")


def _archive_with(
    member_name: str,
    *,
    kind: bytes = tarfile.REGTYPE,
    content: bytes = b"x",
) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        info = tarfile.TarInfo(member_name)
        info.type = kind
        info.size = len(content) if kind == tarfile.REGTYPE else 0
        archive.addfile(info, io.BytesIO(content) if info.size else None)
    return stream.getvalue()


def _policy(tmp_path: Path) -> RuntimePolicy:
    runtime = tmp_path / "runtime"
    fixture = tmp_path / "fixture"
    snapshot_parent = tmp_path / "frozen-snapshots"
    runner = tmp_path / "runner.py"
    runtime.mkdir(exist_ok=True)
    fixture.mkdir(exist_ok=True)
    snapshot_parent.mkdir(exist_ok=True)
    runner.write_text("# trusted runner\n", encoding="utf-8")
    backend = "seatbelt" if platform.system() == "Darwin" else "bubblewrap"
    return RuntimePolicy(
        schema_version="1.0",
        approved_backends=("seatbelt", "bubblewrap"),
        python_interpreter=Path(sys.executable).resolve(),
        runner=runner,
        runtime_read_roots=(runtime,),
        fixture_read_roots=(fixture,),
        snapshot_parent_root=snapshot_parent,
        max_archive_files=32,
        max_archive_file_bytes=1024,
        max_archive_total_bytes=4096,
        max_archive_path_depth=64,
        supported_hosts=(
            SupportedHost(
                os_name=platform.system(),
                architecture=platform.machine(),
                backend=backend,
                backend_executable=Path("/usr/bin/true"),
                minimum_version=(0,),
                maximum_version=(999,),
            ),
        ),
    )


def _git_binary() -> Path:
    located = shutil.which("git")
    assert located is not None
    return Path(located).resolve(strict=True)


def test_materializer_uses_exact_commit_not_live_dirty_or_ignored_files(tmp_path: Path) -> None:
    repo, commit = _trusted_repo(tmp_path)
    (repo / "source.py").write_text("VALUE = 'live-dirty'\n", encoding="utf-8")
    (repo / "ignored.py").write_text("VALUE = 'ignored'\n", encoding="utf-8")
    materializer = FrozenMaterializer(
        {"workbench": repo},
        git_executable=_git_binary(),
        runtime_policy=_policy(tmp_path).validate(),
    )
    frozen = materializer.materialize("workbench", commit)

    assert (frozen.root / "source.py").read_text(encoding="utf-8") == "VALUE = 'from-git'\n"
    assert not (frozen.root / "ignored.py").exists()
    assert frozen.commit_sha == commit
    assert frozen.tree_sha == _git(repo, "rev-parse", f"{commit}^{{tree}}")
    assert [entry.path for entry in frozen.manifest] == ["nested/fixture.txt", "source.py"]
    assert len(frozen.manifest_digest) == 64
    assert frozen.git_identity.content_sha256
    assert frozen.git_identity.inode > 0


@pytest.mark.parametrize(
    ("member_name", "kind"),
    [
        ("../escape.py", tarfile.REGTYPE),
        ("/absolute.py", tarfile.REGTYPE),
        ("helper.pyc", tarfile.REGTYPE),
        ("link", tarfile.SYMTYPE),
        ("hard", tarfile.LNKTYPE),
        ("pipe", tarfile.FIFOTYPE),
    ],
)
def test_extractor_rejects_hostile_entries_before_they_reach_snapshot(
    tmp_path: Path,
    member_name: str,
    kind: bytes,
) -> None:
    with pytest.raises(FrozenMaterializationError):
        extract_frozen_archive(
            _archive_with(member_name, kind=kind),
            tmp_path / "snapshot",
            max_files=4,
            max_file_bytes=32,
            max_total_bytes=64,
        )


def test_materializer_rejects_noncanonical_commit_and_untrusted_repository(tmp_path: Path) -> None:
    repo, commit = _trusted_repo(tmp_path)
    materializer = FrozenMaterializer(
        {"workbench": repo},
        git_executable=_git_binary(),
        runtime_policy=_policy(tmp_path).validate(),
    )

    with pytest.raises(FrozenMaterializationError):
        materializer.materialize("workbench", commit.upper())
    with pytest.raises(FrozenMaterializationError):
        materializer.materialize("unknown", commit)


def test_materializer_rejects_path_git_fallback_and_uses_policy_archive_limits(tmp_path: Path) -> None:
    repo, commit = _trusted_repo(tmp_path)
    policy = _policy(tmp_path)
    with pytest.raises(FrozenMaterializationError):
        FrozenMaterializer(
            {"workbench": repo},
            git_executable=Path("git"),
            runtime_policy=policy.validate(),
        )

    constrained = RuntimePolicy(
        **{**policy.as_dict(), "max_archive_file_bytes": 1}
    ).validate()
    materializer = FrozenMaterializer(
        {"workbench": repo},
        git_executable=_git_binary(),
        runtime_policy=constrained,
    )
    with pytest.raises(FrozenMaterializationError, match="per-file byte limit"):
        materializer.materialize("workbench", commit)


def test_materializer_revalidates_bound_runtime_policy_before_git_archive(tmp_path: Path) -> None:
    repo, commit = _trusted_repo(tmp_path)
    policy = _policy(tmp_path)
    materializer = FrozenMaterializer(
        {"workbench": repo},
        git_executable=_git_binary(),
        runtime_policy=policy.validate(),
    )
    (tmp_path / "runner.py").write_text("# modified after validation\n", encoding="utf-8")

    with pytest.raises(RuntimePolicyError, match="identity changed"):
        materializer.materialize("workbench", commit)


def test_materializer_rejects_snapshot_root_rename_and_recreation(tmp_path: Path, monkeypatch) -> None:
    import workbench.frozen_containment as frozen

    repo, commit = _trusted_repo(tmp_path)
    materializer = FrozenMaterializer(
        {"workbench": repo},
        git_executable=_git_binary(),
        runtime_policy=_policy(tmp_path).validate(),
    )
    original_extract = frozen.extract_frozen_archive

    def replace_root(archive, destination, **limits):
        destination.rename(destination.with_name(destination.name + "-moved"))
        destination.mkdir()
        return original_extract(archive, destination, **limits)

    monkeypatch.setattr(frozen, "extract_frozen_archive", replace_root)
    with pytest.raises(FrozenMaterializationError, match="snapshot root.*replaced"):
        materializer.materialize("workbench", commit)


def test_runtime_policy_digest_is_deterministic_and_rejects_broad_or_symlink_roots(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path)
    validated = policy.validate()
    assert validated.digest == policy.validate().digest

    broad = RuntimePolicy(
        **{**policy.as_dict(), "runtime_read_roots": (Path("/"),)}
    )
    with pytest.raises(RuntimePolicyError):
        broad.validate()

    unsafe_parent = RuntimePolicy(
        **{**policy.as_dict(), "snapshot_parent_root": Path("/")}
    )
    with pytest.raises(RuntimePolicyError):
        unsafe_parent.validate()

    symlink = tmp_path / "runtime-link"
    symlink.symlink_to(tmp_path / "runtime", target_is_directory=True)
    linked = RuntimePolicy(
        **{**policy.as_dict(), "runtime_read_roots": (symlink,)}
    )
    with pytest.raises(RuntimePolicyError):
        linked.validate()

    unowned = RuntimePolicy(
        **{**policy.as_dict(), "approved_owner_uids": ()}
    )
    with pytest.raises(RuntimePolicyError):
        unowned.validate()

    nested = tmp_path / "runtime" / "nested"
    nested.mkdir()
    overlapping = RuntimePolicy(
        **{**policy.as_dict(), "fixture_read_roots": (nested,)}
    )
    with pytest.raises(RuntimePolicyError, match="overlap"):
        overlapping.validate()

    changed_runner = policy.validate()
    (tmp_path / "runner.py").write_text("# changed trusted runner\n", encoding="utf-8")
    with pytest.raises(RuntimePolicyError, match="identity changed"):
        changed_runner.revalidate()


def test_host_matrix_rejects_backend_outside_approved_os_architecture(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    incompatible = RuntimePolicy(
        **{
            **policy.as_dict(),
            "supported_hosts": (
                SupportedHost(
                    os_name="unsupported-os",
                    architecture="unsupported-arch",
                    backend="seatbelt",
                    backend_executable=Path("/usr/bin/true"),
                    minimum_version=(0,),
                    maximum_version=(999,),
                ),
            ),
        }
    ).validate()
    assert discover_containment_backend(incompatible) is None


def test_backend_discovery_uses_only_policy_declared_absolute_binary_not_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workbench.frozen_containment as frozen

    policy = _policy(tmp_path).validate()
    monkeypatch.setenv("PATH", str(tmp_path / "attacker-bin"))
    monkeypatch.setattr(
        frozen.shutil,
        "which",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PATH lookup is forbidden")),
    )

    class Completed:
        returncode = 0
        stdout = "3.14.0"

    calls: list[list[str]] = []

    def configured_binary_only(argv, **_kwargs):
        calls.append(argv)
        return Completed()

    monkeypatch.setattr(frozen.subprocess, "run", configured_binary_only)
    discovered = discover_containment_backend(policy)

    assert discovered is not None
    assert calls == [["/usr/bin/true", "--version"]]


def test_immutable_guard_rejects_git_or_backend_identity_replacement_before_exec() -> None:
    import dataclasses
    import workbench.frozen_containment as frozen

    executable = Path("/usr/bin/true")
    baseline = frozen._immutable_root_owned_executable(executable, "test executable")
    replaced = dataclasses.replace(baseline, inode=baseline.inode + 1)

    with pytest.raises(FrozenMaterializationError, match="identity changed before path execution"):
        with frozen._immutable_executable_guard(executable, replaced):
            pytest.fail("guard must reject before any executable is started")


def test_runtime_policy_rejects_symlinked_backend_binary(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    link = tmp_path / "backend-link"
    link.symlink_to(Path(sys.executable).resolve())
    bad_host = SupportedHost(
        os_name=platform.system(),
        architecture=platform.machine(),
        backend="seatbelt" if platform.system() == "Darwin" else "bubblewrap",
        backend_executable=link,
        minimum_version=(0,),
        maximum_version=(999,),
    )
    with pytest.raises(RuntimePolicyError, match="symlink"):
        RuntimePolicy(**{**policy.as_dict(), "supported_hosts": (bad_host,)}).validate()


def test_policy_validation_rejects_in_place_runner_change_during_identity_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workbench.frozen_containment as frozen

    policy = _policy(tmp_path)
    real_read = frozen.os.read
    changed = False

    def changing_read(fd: int, size: int) -> bytes:
        nonlocal changed
        chunk = real_read(fd, size)
        if not changed and chunk == b"# trusted runner\n":
            (tmp_path / "runner.py").write_text("# changed runner!\n", encoding="utf-8")
            changed = True
        return chunk

    monkeypatch.setattr(frozen.os, "read", changing_read)
    with pytest.raises(RuntimePolicyError, match="identity changed during read"):
        policy.validate()


def test_policy_validation_rejects_runtime_file_replacement_during_directory_walk(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workbench.frozen_containment as frozen

    runtime_file = tmp_path / "runtime" / "module.py"
    (tmp_path / "runtime").mkdir()
    runtime_file.write_bytes(b"original")
    policy = _policy(tmp_path)
    real_read = frozen.os.read
    changed = False

    def replacing_read(fd: int, size: int) -> bytes:
        nonlocal changed
        chunk = real_read(fd, size)
        if not changed and chunk == b"original":
            replacement = runtime_file.with_suffix(".replacement")
            replacement.write_bytes(b"replaced")
            replacement.replace(runtime_file)
            changed = True
        return chunk

    monkeypatch.setattr(frozen.os, "read", replacing_read)
    with pytest.raises(RuntimePolicyError, match="identity changed during read|renamed or replaced"):
        policy.validate()


def test_extractor_retries_short_writes_until_the_member_is_complete(tmp_path: Path, monkeypatch) -> None:
    import workbench.frozen_containment as frozen

    real_write = frozen.os.write

    def short_write(fd: int, data: bytes) -> int:
        return real_write(fd, data[:1])

    monkeypatch.setattr(frozen.os, "write", short_write)
    destination = tmp_path / "snapshot"
    manifest = extract_frozen_archive(
        _archive_with("payload.txt", content=b"short-write"),
        destination,
        max_files=4,
        max_file_bytes=32,
        max_total_bytes=64,
    )

    assert (destination / "payload.txt").read_bytes() == b"short-write"
    assert manifest[0].byte_size == len(b"short-write")


def test_extractor_counts_empty_directories_and_rejects_excessive_path_depth(tmp_path: Path) -> None:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name in ("one/", "two/", "three/"):
            entry = tarfile.TarInfo(name)
            entry.type = tarfile.DIRTYPE
            archive.addfile(entry)
    with pytest.raises(FrozenMaterializationError, match="member limit"):
        extract_frozen_archive(stream.getvalue(), tmp_path / "members", max_files=2, max_file_bytes=8, max_total_bytes=8)

    deep = "/".join(["d"] * 65) + "/file.py"
    with pytest.raises(FrozenMaterializationError, match="depth"):
        extract_frozen_archive(_archive_with(deep), tmp_path / "deep", max_files=80, max_file_bytes=8, max_total_bytes=8)


def test_cleanup_refuses_replaced_snapshot_root_without_deleting_substitute(tmp_path: Path) -> None:
    import workbench.frozen_containment as frozen

    repo, commit = _trusted_repo(tmp_path)
    materializer = FrozenMaterializer(
        {"workbench": repo},
        git_executable=_git_binary(),
        runtime_policy=_policy(tmp_path).validate(),
    )
    parent = tmp_path / "frozen-snapshots"

    def replace_then_fail(_archive, destination, **_limits):
        destination.rename(destination.with_name(destination.name + "-original"))
        destination.mkdir()
        substitute = destination / "keep.txt"
        substitute.write_text("do not delete", encoding="utf-8")
        raise OSError("forced extraction failure")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(frozen, "extract_frozen_archive", replace_then_fail)
    try:
        with pytest.raises(FrozenMaterializationError, match="retained for audit"):
            materializer.materialize("workbench", commit)
    finally:
        monkeypatch.undo()
    substitutes = list(parent.glob("*/keep.txt"))
    assert len(substitutes) == 1
    assert substitutes[0].read_text(encoding="utf-8") == "do not delete"


def test_archive_shutdown_terminates_then_kills_and_reaps_hung_child() -> None:
    import subprocess as subprocess_module
    import workbench.frozen_containment as frozen

    class HungProcess:
        def __init__(self):
            self.waits = 0
            self.events: list[str] = []

        def poll(self):
            return None

        def terminate(self):
            self.events.append("term")

        def kill(self):
            self.events.append("kill")

        def wait(self, timeout):
            self.waits += 1
            self.events.append(f"wait:{timeout}")
            if self.waits == 1:
                raise subprocess_module.TimeoutExpired("git", timeout)
            return 0

    process = HungProcess()
    frozen._terminate_and_reap(process)
    assert process.events == ["term", "wait:2", "kill", "wait:2"]


def test_unsupported_or_unproven_backend_is_static_rejection_before_capability_issue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, commit = _trusted_repo(tmp_path)
    service = FrozenContainmentService(
        trusted_repositories={"workbench": repo},
        runtime_policy=_policy(tmp_path),
        git_executable=_git_binary(),
    )
    monkeypatch.setattr(service, "discover_backend", lambda: None)

    with pytest.raises(StaticContainmentRejection) as rejected:
        service.prepare_source_only("workbench", commit, "workbench", commit)

    assert rejected.value.code == "UNSUPPORTED_OR_UNPROVEN_BACKEND"
    assert "Popen" not in str(rejected.value)


def test_public_service_has_no_raw_command_execution_entrypoint() -> None:
    forbidden = {"run", "execute", "popen", "run_command", "run_python"}
    public = {name for name in dir(FrozenContainmentService) if not name.startswith("_")}
    assert forbidden.isdisjoint(public)
