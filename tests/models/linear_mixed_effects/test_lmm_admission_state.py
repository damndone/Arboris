from __future__ import annotations

import copy
import json
import os
import pickle
from pathlib import Path

import pytest


def _representation() -> dict[str, object]:
    return {
        "schema_version": 1,
        "model_type": "linear_mixed_effects",
        "model_options": {"subject_id": "subject", "time": "week", "group": "arm"},
        "model_options_binding": {
            "owner_model_type": "linear_mixed_effects",
            "owner_model_id": "linear_mixed_effects_1",
            "producer_version": "linear_mixed_effects@1.0",
            "input_contract_version": "1.0",
            "normalized_options_hash": "a" * 64,
        },
    }


def _provisional(tmp_path: Path):
    from workbench.services.pinned_run_directory import (
        _new_test_lmm_execution_admission,
        open_pinned_run_directory,
        seal_executed_input_v1,
    )

    (tmp_path / "run-1").mkdir()
    pinned = open_pinned_run_directory(tmp_path, "run-1")
    seal = seal_executed_input_v1(pinned, _representation())
    return pinned, _new_test_lmm_execution_admission(pinned, seal), seal


def _diagnostic_packet() -> dict[str, object]:
    return {
        "contract": "linear_mixed_effects.diagnostic",
        "contract_version": "1.0",
        "producer_version": "linear_mixed_effects@1.0",
        "payload": {"code": "LMM_EXECUTION_INPUT_MISMATCH"},
    }


def test_provisional_admission_cannot_be_consumed_until_explicitly_committed(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _commit_lmm_execution_admission,
        _consume_lmm_execution_admission,
    )

    invalidated_root = tmp_path / "invalidated"
    invalidated_root.mkdir()
    pinned, admission, _ = _provisional(invalidated_root)
    try:
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _consume_lmm_execution_admission(admission)
        _commit_lmm_execution_admission(admission)
        assert _consume_lmm_execution_admission(admission)[0] is pinned
    finally:
        admission._close_for_test()
        pinned.close()


def test_execution_admission_rejects_copy_and_pickle_without_affecting_private_registry(
    tmp_path: Path,
) -> None:
    from workbench.services.pinned_run_directory import (
        _commit_lmm_execution_admission,
        _consume_lmm_execution_admission,
    )

    pinned, admission, _ = _provisional(tmp_path)
    try:
        with pytest.raises(TypeError, match="LmmExecutionAdmission is not copyable"):
            copy.copy(admission)
        with pytest.raises(TypeError, match="LmmExecutionAdmission is not copyable"):
            copy.deepcopy(admission)
        with pytest.raises(TypeError, match="LmmExecutionAdmission is not serializable"):
            pickle.dumps(admission)
        _commit_lmm_execution_admission(admission)
        assert _consume_lmm_execution_admission(admission)[0] is pinned
    finally:
        admission._close_for_test()
        pinned.close()


def test_preflight_consumer_accepts_only_the_live_provisional_admission(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _commit_lmm_execution_admission,
        _consume_lmm_provisional_admission_for_preflight,
    )

    pinned, admission, seal = _provisional(tmp_path)
    try:
        consumed_pinned, consumed_seal = _consume_lmm_provisional_admission_for_preflight(admission)
        assert consumed_pinned is pinned
        assert consumed_seal is seal
        _commit_lmm_execution_admission(admission)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(pinned, "_require_open", lambda: pytest.fail("pinned traversal occurred"))
        try:
            with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
                _consume_lmm_provisional_admission_for_preflight(admission)
        finally:
            monkeypatch.undo()
    finally:
        admission._close_for_test()
        pinned.close()


def test_preflight_consumer_rejects_forged_closed_or_invalidated_admissions_before_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _consume_lmm_provisional_admission_for_preflight,
        _invalidate_lmm_execution_admission,
    )

    pinned, admission, _ = _provisional(tmp_path)
    try:
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _consume_lmm_provisional_admission_for_preflight(object())
        admission._close_for_test()
        monkeypatch.setattr(pinned, "_require_open", lambda: pytest.fail("pinned traversal occurred"))
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _consume_lmm_provisional_admission_for_preflight(admission)
        monkeypatch.undo()
    finally:
        pinned.close()

    invalidated_root = tmp_path / "invalidated"
    invalidated_root.mkdir()
    pinned, admission, _ = _provisional(invalidated_root)
    try:
        _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")
        monkeypatch.setattr(pinned, "_require_open", lambda: pytest.fail("pinned traversal occurred"))
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _consume_lmm_provisional_admission_for_preflight(admission)
    finally:
        monkeypatch.undo()
        pinned.close()


def test_preflight_rejects_a_tombstone_that_appears_after_provisional_sealing(tmp_path: Path) -> None:
    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _consume_lmm_provisional_admission_for_preflight,
    )

    pinned, admission, seal = _provisional(tmp_path)
    try:
        module._publish_invalidation_tombstone(pinned, seal, "LMM_EXECUTION_INPUT_MISMATCH")
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_INVALIDATED"):
            _consume_lmm_provisional_admission_for_preflight(admission)
    finally:
        admission._close_for_test()
        pinned.close()


def test_invalidating_after_a_seal_writes_durable_tombstone_before_demoting(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _consume_lmm_execution_admission,
        _consume_lmm_input_blocked_admission,
        _invalidate_lmm_execution_admission,
    )

    pinned, admission, seal = _provisional(tmp_path)
    try:
        blocked = _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")
        tombstone = tmp_path / "run-1" / "artifacts" / "execution" / f"invalidated_input_v1.{seal.digest}.json"
        assert json.loads(tombstone.read_text()) == {
            "schema_version": 1,
            "run_id": "run-1",
            "seal_digest": seal.digest,
            "reason_code": "LMM_EXECUTION_INPUT_MISMATCH",
        }
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _consume_lmm_execution_admission(admission)
        assert _consume_lmm_input_blocked_admission(blocked) is pinned
    finally:
        admission._close_for_test()
        pinned.close()


def test_reopen_after_durable_invalidation_cannot_readmit_same_run_and_seal(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _invalidate_lmm_execution_admission,
        _new_test_lmm_execution_admission,
        open_pinned_run_directory,
        seal_executed_input_v1,
    )

    pinned, admission, _ = _provisional(tmp_path)
    try:
        _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")
    finally:
        admission._close_for_test()
        pinned.close()

    reopened = open_pinned_run_directory(tmp_path, "run-1")
    try:
        seal = seal_executed_input_v1(reopened, _representation())
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_INVALIDATED"):
            _new_test_lmm_execution_admission(reopened, seal)
    finally:
        reopened.close()


def test_symlinked_invalidation_path_is_not_treated_as_an_absent_tombstone(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _new_test_lmm_execution_admission,
    )

    pinned, admission, seal = _provisional(tmp_path)
    try:
        admission._close_for_test()
        target = tmp_path / "outside.json"
        target.write_text("{}")
        execution = tmp_path / "run-1" / "artifacts" / "execution"
        (execution / f"invalidated_input_v1.{seal.digest}.json").symlink_to(target)
        with pytest.raises(PinnedRunError, match="LMM_INVALIDATION_TOMBSTONE_INVALID"):
            _new_test_lmm_execution_admission(pinned, seal)
    finally:
        pinned.close()


def test_failed_tombstone_fsync_does_not_demote_or_mint_blocked_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _consume_lmm_execution_admission,
        _invalidate_lmm_execution_admission,
    )

    pinned, admission, _ = _provisional(tmp_path)
    try:
        monkeypatch.setattr(module.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("no sync")))
        with pytest.raises(PinnedRunError, match="LMM_INVALIDATION_TOMBSTONE_INVALID"):
            _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _consume_lmm_execution_admission(admission)
    finally:
        admission._close_for_test()
        pinned.close()


def test_retry_after_parent_fsync_failure_reproves_existing_tombstone_before_demoting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed first publication may be retried only after durable re-proof.

    The retry takes the ``EEXIST`` path.  It must not merely re-read the
    canonical bytes: it must open the fixed leaf without following links,
    fsync that existing leaf, fsync its directory, and only then perform the
    canonical re-read that allows the provisional capability to be demoted.
    """

    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _consume_lmm_input_blocked_admission,
        _invalidate_lmm_execution_admission,
    )

    pinned, admission, seal = _provisional(tmp_path)
    original_fsync = module.os.fsync
    original_open = module.os.open
    fsync_calls = 0
    retry_fsync_identities: list[tuple[int, int]] = []
    leaf_open_flags: list[int] = []
    retrying = False

    def fail_only_the_first_parent_fsync(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError("first parent fsync failed")
        if retrying:
            stat_result = os.fstat(fd)
            retry_fsync_identities.append((stat_result.st_dev, stat_result.st_ino))
        original_fsync(fd)

    def record_retry_leaf_open(name: object, flags: int, *args: object, **kwargs: object) -> int:
        if retrying and name == f"invalidated_input_v1.{seal.digest}.json":
            leaf_open_flags.append(flags)
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "fsync", fail_only_the_first_parent_fsync)
    monkeypatch.setattr(module.os, "open", record_retry_leaf_open)
    try:
        with pytest.raises(PinnedRunError, match="LMM_INVALIDATION_TOMBSTONE_INVALID"):
            _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")

        retrying = True
        blocked = _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")

        tombstone = tmp_path / "run-1" / "artifacts" / "execution" / f"invalidated_input_v1.{seal.digest}.json"
        parent = tombstone.parent
        assert retry_fsync_identities == [
            (os.stat(tombstone).st_dev, os.stat(tombstone).st_ino),
            (os.stat(parent).st_dev, os.stat(parent).st_ino),
        ]
        assert leaf_open_flags
        assert all(flags & module._O_NOFOLLOW for flags in leaf_open_flags)
        assert _consume_lmm_input_blocked_admission(blocked) is pinned
    finally:
        admission._close_for_test()
        pinned.close()


def test_forged_or_closed_blocked_admission_is_rejected_before_pinned_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _consume_lmm_input_blocked_admission,
        _invalidate_lmm_execution_admission,
    )

    pinned, admission, _ = _provisional(tmp_path)
    try:
        blocked = _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")
        blocked._close_for_test()
        monkeypatch.setattr(pinned, "_require_open", lambda: pytest.fail("pinned traversal occurred"))
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _consume_lmm_input_blocked_admission(blocked)
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _consume_lmm_input_blocked_admission(object())
    finally:
        admission._close_for_test()
        pinned.close()


def test_blocked_admission_publishes_exactly_one_diagnostic_and_no_terminal_result(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        _invalidate_lmm_execution_admission,
        _persist_lmm_input_blocked_diagnostic,
    )

    pinned, admission, _ = _provisional(tmp_path)
    try:
        blocked = _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")
        receipt = _persist_lmm_input_blocked_diagnostic(admission=blocked, packet=_diagnostic_packet())
        assert not hasattr(receipt, "path")
        index = json.loads((tmp_path / "run-1" / "artifacts_index.json").read_text())
        assert [record["artifact_type"] for record in index["artifacts"]] == ["lmm_diagnostic_packet"]
        record = index["artifacts"][0]
        assert record["path"].startswith("artifacts/diagnostics/linear_mixed_effects_1.")
        assert (tmp_path / "run-1" / record["path"]).is_file()
        assert not (tmp_path / "run-1" / "artifacts" / "model_results").exists()
        assert not (tmp_path / "run-1" / "artifacts" / "recovery").exists()
        assert not hasattr(blocked, "seal")
        with pytest.raises(TypeError):
            pickle.dumps(blocked)
    finally:
        admission._close_for_test()
        pinned.close()


def test_blocked_admission_replay_and_terminal_writer_are_rejected_without_mutation(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _invalidate_lmm_execution_admission,
        _persist_lmm_input_blocked_diagnostic,
        _persist_lmm_terminal_packet,
    )

    pinned, admission, _ = _provisional(tmp_path)
    try:
        blocked = _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")
        _persist_lmm_input_blocked_diagnostic(admission=blocked, packet=_diagnostic_packet())
        index_before = (tmp_path / "run-1" / "artifacts_index.json").read_bytes()
        with pytest.raises(PinnedRunError, match="LMM_INPUT_BLOCKED_DIAGNOSTIC_CONSUMED"):
            _persist_lmm_input_blocked_diagnostic(admission=blocked, packet=_diagnostic_packet())
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _persist_lmm_terminal_packet(admission=blocked, packet={
                "contract": "linear_mixed_effects.result",
                "contract_version": "1.0",
                "producer_version": "linear_mixed_effects@1.0",
                "payload": {"status": "complete"},
            })
        assert (tmp_path / "run-1" / "artifacts_index.json").read_bytes() == index_before
    finally:
        admission._close_for_test()
        pinned.close()


def test_forged_closed_or_tombstone_replaced_blocked_admission_fails_before_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _invalidate_lmm_execution_admission,
        _persist_lmm_input_blocked_diagnostic,
    )

    pinned, admission, seal = _provisional(tmp_path)
    try:
        blocked = _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _persist_lmm_input_blocked_diagnostic(admission=object(), packet=_diagnostic_packet())
        with pytest.raises(TypeError):
            module._LmmInputBlockedAdmission(object(), pinned, "not-a-tombstone", (0, 0, "x", "0" * 64))
        tombstone = tmp_path / "run-1" / "artifacts" / "execution" / f"invalidated_input_v1.{seal.digest}.json"
        tombstone.write_bytes(b"{}")
        monkeypatch.setattr(pinned, "_open_or_create_directory", lambda *_: pytest.fail("storage traversal occurred"))
        with pytest.raises(PinnedRunError, match="LMM_INVALIDATION_TOMBSTONE_INVALID"):
            _persist_lmm_input_blocked_diagnostic(admission=blocked, packet=_diagnostic_packet())
        assert not (tmp_path / "run-1" / "artifacts_index.json").exists()
        blocked._close_for_test()
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _persist_lmm_input_blocked_diagnostic(admission=blocked, packet=_diagnostic_packet())
    finally:
        admission._close_for_test()
        pinned.close()
