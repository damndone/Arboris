"""Hostile-output C2 ingestion tests; no candidate or real host is run."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from workbench.frozen_containment_execution import CandidateObservationV1
from workbench.frozen_containment_ingestion import (
    EvaluatorVerdictV1,
    IngestionAuditStore,
    OutputPolicyV1,
    ParentOutputRootV1,
    ingest_and_evaluate,
    open_parent_output_root,
)


class _Evaluator:
    def __init__(self, passed: bool) -> None:
        self.passed = passed
        self.calls = 0

    def evaluate(self, *, observation: CandidateObservationV1, output_manifest: tuple[object, ...]) -> bool:
        self.calls += 1
        return self.passed


def _policy(*, allowed_files: tuple[str, ...] = ("result.json",), forbidden: tuple[tuple[int, int], ...] = ()) -> OutputPolicyV1:
    return OutputPolicyV1(allowed_files=allowed_files, max_file_bytes=1024, max_total_bytes=2048, forbidden_identities=forbidden)


def _observation(status: str = "passed") -> CandidateObservationV1:
    return CandidateObservationV1("1", status, ())


def _root(tmp_path: Path) -> ParentOutputRootV1:
    path = tmp_path / "output"
    path.mkdir()
    return open_parent_output_root(path)


def _ingest(tmp_path: Path, root: ParentOutputRootV1, evaluator: _Evaluator, *, policy: OutputPolicyV1 | None = None):
    return ingest_and_evaluate(
        observation=_observation(),
        output_root=root,
        output_policy=policy or _policy(),
        parent_evaluator=evaluator,
        audit_store=IngestionAuditStore(tmp_path / "audit"),
    )


def test_parent_fixture_failure_overrides_candidate_passed_and_publishes_no_success_receipt(tmp_path: Path) -> None:
    root = _root(tmp_path)
    os.write(os.open("result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root.descriptor), b"{}")
    evaluator = _Evaluator(False)
    outcome = _ingest(tmp_path, root, evaluator)
    assert outcome.verdict == "non_passing"
    assert outcome.code == "C2_EVALUATOR_NONPASSING"
    assert outcome.audit_receipt is None
    assert evaluator.calls == 1
    root.close()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "unexpected", "oversized"])
def test_hostile_output_entries_reject_before_parent_evaluator(tmp_path: Path, kind: str) -> None:
    root = _root(tmp_path)
    output = tmp_path / "output"
    if kind == "symlink":
        (output / "result.json").symlink_to(tmp_path / "outside")
    elif kind == "hardlink":
        source = tmp_path / "source"
        source.write_bytes(b"{}")
        os.link(source, output / "result.json")
    elif kind == "unexpected":
        (output / "junit.xml").write_text("<passed/>", encoding="utf-8")
    else:
        (output / "result.json").write_bytes(b"x" * 1025)
    evaluator = _Evaluator(True)
    outcome = _ingest(tmp_path, root, evaluator)
    assert outcome.verdict == "non_passing"
    assert outcome.code == "C2_INGESTION_FAILED"
    assert outcome.audit_receipt is None
    assert evaluator.calls == 0
    root.close()


def test_forbidden_source_runtime_fixture_inode_alias_rejects(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = tmp_path / "fixture"
    source.write_bytes(b"{}")
    identity = os.stat(source)
    os.link(source, tmp_path / "output" / "result.json")
    evaluator = _Evaluator(True)
    outcome = _ingest(tmp_path, root, evaluator, policy=_policy(forbidden=((identity.st_dev, identity.st_ino),)))
    assert outcome.code == "C2_INGESTION_FAILED"
    assert evaluator.calls == 0
    root.close()


def test_parent_output_descriptor_survives_path_replacement_without_following_replacement(tmp_path: Path) -> None:
    root = _root(tmp_path)
    old_output = tmp_path / "output"
    old_output.rename(tmp_path / "moved-output")
    old_output.mkdir()
    (old_output / "result.json").write_bytes(b"attacker replacement")
    os.write(os.open("result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root.descriptor), b"{}")
    evaluator = _Evaluator(True)
    outcome = _ingest(tmp_path, root, evaluator)
    assert outcome.verdict == "passed"
    assert outcome.code == "C2_EVALUATOR_PASSED"
    assert outcome.audit_receipt is not None
    root.close()


def test_audit_reread_failure_is_nonpassing_with_null_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.frozen_containment_ingestion as ingestion

    root = _root(tmp_path)
    os.write(os.open("result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root.descriptor), b"{}")
    monkeypatch.setattr(ingestion, "_read_no_follow", lambda *_args: b"different")
    outcome = _ingest(tmp_path, root, _Evaluator(True))
    assert outcome.verdict == "non_passing"
    assert outcome.code == "C2_INGESTION_FAILED"
    assert outcome.audit_receipt is None
    root.close()


def test_audit_collision_never_reuses_or_overwrites_a_passing_receipt(tmp_path: Path) -> None:
    root = _root(tmp_path)
    descriptor = os.open("result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root.descriptor)
    os.write(descriptor, b"{}")
    os.close(descriptor)
    store = IngestionAuditStore(tmp_path / "audit")
    evaluator = _Evaluator(True)
    first = ingest_and_evaluate(observation=_observation(), output_root=root, output_policy=_policy(), parent_evaluator=evaluator, audit_store=store)
    second = ingest_and_evaluate(observation=_observation(), output_root=root, output_policy=_policy(), parent_evaluator=evaluator, audit_store=store)
    assert first.verdict == "passed" and first.audit_receipt is not None
    assert second.verdict == "non_passing"
    assert second.code == "C2_INGESTION_FAILED"
    assert second.audit_receipt is None
    root.close()


def test_ingestion_module_does_not_import_candidate_or_start_processes() -> None:
    import inspect
    import workbench.frozen_containment_ingestion as ingestion

    source = inspect.getsource(ingestion)
    assert "subprocess" not in source
    assert "Popen(" not in source
    assert "importlib" not in source
