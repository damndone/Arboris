from __future__ import annotations

import json
import os
import pickle
import threading
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


def _packet(contract: str) -> dict[str, object]:
    return {
        "contract": contract,
        "contract_version": "1.0",
        "producer_version": "linear_mixed_effects@1.0",
        "payload": {"kind": contract},
    }


def _open_admission(tmp_path: Path):
    from workbench.services.pinned_run_directory import (
        _commit_lmm_execution_admission,
        _new_test_lmm_execution_admission,
        open_pinned_run_directory,
        seal_executed_input_v1,
    )

    (tmp_path / "run-1").mkdir()
    pinned = open_pinned_run_directory(tmp_path, "run-1")
    seal = seal_executed_input_v1(pinned, _representation())
    admission = _new_test_lmm_execution_admission(pinned, seal)
    _commit_lmm_execution_admission(admission)
    return pinned, admission


def test_immutable_same_content_retry_reproves_leaf_and_parent_durability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An EEXIST retry may proceed only after its durable-object proof."""

    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import PinnedRunError, _publish_immutable

    pinned, admission = _open_admission(tmp_path)
    parent_fd = pinned._seal_parent_fd()
    original_fsync = module.os.fsync
    original_open = module.os.open
    fsync_calls = 0
    retrying = False
    retry_fsync_identities: list[tuple[int, int]] = []
    leaf_open_flags: list[int] = []

    def fail_only_the_first_parent_fsync(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError("first parent fsync failed")
        if retrying:
            state = os.fstat(fd)
            retry_fsync_identities.append((state.st_dev, state.st_ino))
        original_fsync(fd)

    def record_retry_leaf_open(name: object, flags: int, *args: object, **kwargs: object) -> int:
        if retrying and name == "same-content-retry.json":
            leaf_open_flags.append(flags)
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "fsync", fail_only_the_first_parent_fsync)
    monkeypatch.setattr(module.os, "open", record_retry_leaf_open)
    try:
        with pytest.raises(PinnedRunError, match="LMM_PERSISTENCE_IO_FAILED"):
            _publish_immutable(parent_fd, "same-content-retry.json", b'{"schema_version":1}')

        retrying = True
        _publish_immutable(parent_fd, "same-content-retry.json", b'{"schema_version":1}')

        leaf = tmp_path / "run-1" / "artifacts" / "execution" / "same-content-retry.json"
        parent = leaf.parent
        assert retry_fsync_identities[-2:] == [
            (os.stat(leaf).st_dev, os.stat(leaf).st_ino),
            (os.stat(parent).st_dev, os.stat(parent).st_ino),
        ]
        assert leaf_open_flags
        assert all(flags & module._O_NOFOLLOW for flags in leaf_open_flags)
    finally:
        module._close(parent_fd)
        admission._close_for_test()
        pinned.close()


def test_equal_execution_seal_retry_reproves_leaf_and_parent_durability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing equal seal is not reusable before its fsync proof."""

    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import PinnedRunError, open_pinned_run_directory, seal_executed_input_v1

    (tmp_path / "run-1").mkdir()
    pinned = open_pinned_run_directory(tmp_path, "run-1")
    representation = _representation()
    original_fsync = module.os.fsync
    original_open = module.os.open
    fsync_calls = 0
    retrying = False
    retry_fsync_identities: list[tuple[int, int]] = []
    leaf_open_flags: list[int] = []

    def fail_only_the_first_parent_fsync(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError("first parent fsync failed")
        if retrying:
            state = os.fstat(fd)
            retry_fsync_identities.append((state.st_dev, state.st_ino))
        original_fsync(fd)

    def record_retry_leaf_open(name: object, flags: int, *args: object, **kwargs: object) -> int:
        if retrying and name == "executed_input_v1.json":
            leaf_open_flags.append(flags)
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "fsync", fail_only_the_first_parent_fsync)
    monkeypatch.setattr(module.os, "open", record_retry_leaf_open)
    try:
        with pytest.raises(PinnedRunError, match="EXECUTED_INPUT_SEAL_INVALID"):
            seal_executed_input_v1(pinned, representation)

        retrying = True
        seal = seal_executed_input_v1(pinned, representation)

        leaf = tmp_path / "run-1" / "artifacts" / "execution" / "executed_input_v1.json"
        parent = leaf.parent
        assert retry_fsync_identities == [
            (os.stat(leaf).st_dev, os.stat(leaf).st_ino),
            (os.stat(parent).st_dev, os.stat(parent).st_ino),
        ]
        assert leaf_open_flags
        assert all(flags & module._O_NOFOLLOW for flags in leaf_open_flags)
        assert seal.canonical_bytes
    finally:
        pinned.close()


def test_private_terminal_writer_publishes_one_fixed_packet_and_exact_index_without_legacy_writers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.artifacts as legacy_artifacts
    from workbench.services.pinned_run_directory import _persist_lmm_terminal_packet

    pinned, admission = _open_admission(tmp_path)
    monkeypatch.setattr(legacy_artifacts, "write_json", lambda *args, **kwargs: pytest.fail("legacy write_json called"))
    monkeypatch.setattr(legacy_artifacts, "register_artifact", lambda *args, **kwargs: pytest.fail("legacy register_artifact called"))
    packet = _packet("linear_mixed_effects.result")
    try:
        receipt = _persist_lmm_terminal_packet(admission=admission, packet=packet)
        terminal = tmp_path / "run-1" / "artifacts" / "model_results" / "linear_mixed_effects_1.result.json"
        assert terminal.is_file()
        assert set(path.relative_to(tmp_path / "run-1").as_posix() for path in terminal.parent.rglob("*") if path.is_file()) == {
            "artifacts/model_results/linear_mixed_effects_1.result.json"
        }
        index = json.loads((tmp_path / "run-1" / "artifacts_index.json").read_text())
        assert index["schema_version"] == 1
        assert len(index["artifacts"]) == 1
        record = index["artifacts"][0]
        assert record["artifact_type"] == "model_result_packet"
        assert record["path"] == "artifacts/model_results/linear_mixed_effects_1.result.json"
        assert not hasattr(receipt, "path")
        assert not hasattr(receipt, "digest")
        assert not hasattr(receipt, "record")
        assert not hasattr(receipt, "__dict__")
        assert _persist_lmm_terminal_packet(admission=admission, packet=packet) is receipt
        changed = _packet("linear_mixed_effects.result")
        changed["payload"] = {"kind": "changed"}
        with pytest.raises(Exception, match="LMM_TERMINAL_PERSISTENCE_CONFLICT"):
            _persist_lmm_terminal_packet(admission=admission, packet=changed)
    finally:
        admission._close_for_test()
        pinned.close()


def test_writer_is_admission_gated_and_receipts_are_not_public_capabilities(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedArtifactReceipt,
        PinnedRunError,
        _new_test_lmm_execution_admission,
        _persist_lmm_terminal_packet,
    )

    pinned, admission = _open_admission(tmp_path)
    try:
        assert not hasattr(pinned, "persist_lmm_terminal_packet")
        receipt = _persist_lmm_terminal_packet(admission=admission, packet=_packet("linear_mixed_effects.result"))
        with pytest.raises(TypeError):
            PinnedArtifactReceipt()
        with pytest.raises(TypeError):
            pickle.dumps(receipt)
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _new_test_lmm_execution_admission(pinned, admission._seal_for_test())
        admission._close_for_test()
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _persist_lmm_terminal_packet(admission=admission, packet=_packet("linear_mixed_effects.result"))
        with pytest.raises(PinnedRunError, match="LMM_PERSISTENCE_RECEIPT_INVALID"):
            admission._facade_for_test().receipt_record(receipt)
    finally:
        pinned.close()


def test_diagnostic_is_content_addressed_and_recovery_requires_same_open_terminal_receipt(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _persist_lmm_diagnostic_packet,
        _persist_lmm_recovery_packet,
        _persist_lmm_terminal_packet,
    )

    pinned, admission = _open_admission(tmp_path)
    try:
        diagnostic = _persist_lmm_diagnostic_packet(
            admission=admission,
            packet=_packet("linear_mixed_effects.diagnostic"),
            terminal=None,
        )
        diagnostic_record = admission._facade_for_test().receipt_record(diagnostic)
        assert diagnostic_record["artifact_type"] == "lmm_diagnostic_packet"
        assert diagnostic_record["path"].startswith("artifacts/diagnostics/linear_mixed_effects_1.")
        assert diagnostic_record["path"].endswith(".json")
        terminal = _persist_lmm_terminal_packet(admission=admission, packet=_packet("linear_mixed_effects.result"))
        recovery = _persist_lmm_recovery_packet(
            admission=admission,
            packet=_packet("linear_mixed_effects.recovery_proposal"),
            terminal=terminal,
        )
        recovery_record = admission._facade_for_test().receipt_record(recovery)
        assert recovery_record["artifact_type"] == "lmm_recovery_packet"
        assert recovery_record["inputs"] == [
            f"terminal_artifact_id:{admission._facade_for_test().receipt_record(terminal)['artifact_id']}",
            f"terminal_sha256:{admission._facade_for_test().receipt_record(terminal)['sha256']}",
        ]
        with pytest.raises(PinnedRunError, match="LMM_PERSISTENCE_RECEIPT_INVALID"):
            _persist_lmm_recovery_packet(admission=admission, packet=_packet("linear_mixed_effects.recovery_proposal"), terminal=diagnostic)
    finally:
        admission._close_for_test()
        pinned.close()


def test_preexisting_writer_token_is_never_reaped_and_blocks_before_packet_or_index_write(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import PinnedRunError, _persist_lmm_terminal_packet

    pinned, admission = _open_admission(tmp_path)
    token = tmp_path / "run-1" / ".lmm_pinned_v1.admission.lock"
    token.write_bytes(b"other live owner")
    try:
        with pytest.raises(PinnedRunError, match="LMM_PERSISTENCE_BUSY"):
            _persist_lmm_terminal_packet(admission=admission, packet=_packet("linear_mixed_effects.result"))
        assert token.read_bytes() == b"other live owner"
        assert not (tmp_path / "run-1" / "artifacts" / "model_results" / "linear_mixed_effects_1.result.json").exists()
        assert not (tmp_path / "run-1" / "artifacts_index.json").exists()
    finally:
        token.unlink()
        admission._close_for_test()
        pinned.close()


def test_preexisting_fixed_terminal_slot_with_different_bytes_never_overwrites_or_indexes(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import PinnedRunError, _persist_lmm_terminal_packet

    pinned, admission = _open_admission(tmp_path)
    slot = tmp_path / "run-1" / "artifacts" / "model_results" / "linear_mixed_effects_1.result.json"
    slot.parent.mkdir(parents=True)
    slot.write_bytes(b'{"untrusted":true}')
    try:
        with pytest.raises(PinnedRunError, match="LMM_TERMINAL_PERSISTENCE_CONFLICT"):
            _persist_lmm_terminal_packet(admission=admission, packet=_packet("linear_mixed_effects.result"))
        assert slot.read_bytes() == b'{"untrusted":true}'
        assert not (tmp_path / "run-1" / "artifacts_index.json").exists()
    finally:
        admission._close_for_test()
        pinned.close()


def test_all_full_admission_publications_hold_the_registry_lock_through_descriptor_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A demotion cannot interleave between the final recheck and publication."""

    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import (
        _persist_lmm_diagnostic_packet,
        _persist_lmm_recovery_packet,
        _persist_lmm_terminal_packet,
    )

    class TrackingLock:
        def __init__(self) -> None:
            self._lock = threading.RLock()
            self.depth = 0

        def __enter__(self):
            self._lock.acquire()
            self.depth += 1
            return self

        def __exit__(self, *args: object) -> None:
            self.depth -= 1
            self._lock.release()

    pinned, admission = _open_admission(tmp_path)
    lock = TrackingLock()
    original_writer_directory = module._writer_directory

    def assert_locked(*args: object, **kwargs: object) -> int:
        assert lock.depth > 0, "descriptor traversal ran after the admission lock was released"
        return original_writer_directory(*args, **kwargs)

    monkeypatch.setattr(module, "_ADMISSION_LOCK", lock)
    monkeypatch.setattr(module, "_writer_directory", assert_locked)
    try:
        terminal = _persist_lmm_terminal_packet(admission=admission, packet=_packet("linear_mixed_effects.result"))
        _persist_lmm_diagnostic_packet(
            admission=admission,
            packet=_packet("linear_mixed_effects.diagnostic"),
            terminal=terminal,
        )
        _persist_lmm_recovery_packet(
            admission=admission,
            packet=_packet("linear_mixed_effects.recovery_proposal"),
            terminal=terminal,
        )
    finally:
        admission._close_for_test()
        pinned.close()


def test_demoted_admission_cannot_publish_terminal_or_recovery_after_invalidation(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _invalidate_lmm_execution_admission,
        _persist_lmm_recovery_packet,
        _persist_lmm_terminal_packet,
    )

    pinned, admission = _open_admission(tmp_path)
    # `_open_admission` is committed for normal facade tests; construct a
    # separate provisional capability for this demotion boundary.
    admission._close_for_test()
    from workbench.services.pinned_run_directory import _new_test_lmm_execution_admission
    provisional = _new_test_lmm_execution_admission(pinned, admission._seal_for_test())
    try:
        _invalidate_lmm_execution_admission(provisional, "LMM_EXECUTION_INPUT_MISMATCH")
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _persist_lmm_terminal_packet(admission=provisional, packet=_packet("linear_mixed_effects.result"))
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_REQUIRED"):
            _persist_lmm_recovery_packet(
                admission=provisional,
                packet=_packet("linear_mixed_effects.recovery_proposal"),
                terminal=object(),
            )
        assert not (tmp_path / "run-1" / "artifacts" / "model_results").exists()
        assert not (tmp_path / "run-1" / "artifacts" / "recovery").exists()
    finally:
        provisional._close_for_test()
        pinned.close()


def test_writer_and_demotion_attempt_are_linearized_at_the_registry_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A demotion request cannot pass a paused committed publication."""

    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        _invalidate_lmm_execution_admission,
        _persist_lmm_terminal_packet,
    )

    pinned, admission = _open_admission(tmp_path)
    writer_entered = threading.Event()
    release_writer = threading.Event()
    demotion_started = threading.Event()
    demotion_done = threading.Event()
    outcomes: dict[str, object] = {}
    original_writer_directory = module._writer_directory

    def paused_writer_directory(*args: object, **kwargs: object) -> int:
        writer_entered.set()
        assert release_writer.wait(2), "test writer was not released"
        return original_writer_directory(*args, **kwargs)

    monkeypatch.setattr(module, "_writer_directory", paused_writer_directory)

    def write_terminal() -> None:
        try:
            outcomes["terminal"] = _persist_lmm_terminal_packet(
                admission=admission, packet=_packet("linear_mixed_effects.result")
            )
        except BaseException as exc:  # test thread handoff
            outcomes["terminal_error"] = exc

    def try_demote() -> None:
        demotion_started.set()
        try:
            _invalidate_lmm_execution_admission(admission, "LMM_EXECUTION_INPUT_MISMATCH")
        except BaseException as exc:  # test thread handoff
            outcomes["demotion_error"] = exc
        finally:
            demotion_done.set()

    writer = threading.Thread(target=write_terminal)
    writer.start()
    assert writer_entered.wait(2)
    demoter = threading.Thread(target=try_demote)
    demoter.start()
    assert demotion_started.wait(2)
    assert not demotion_done.wait(0.05), "demotion interleaved into a locked publication"
    release_writer.set()
    writer.join(2)
    demoter.join(2)
    try:
        assert "terminal" in outcomes
        assert isinstance(outcomes.get("demotion_error"), PinnedRunError)
        assert "LMM_EXECUTION_BINDING_REQUIRED" in str(outcomes["demotion_error"])
        assert not list((tmp_path / "run-1" / "artifacts" / "execution").glob("invalidated_input_v1.*.json"))
    finally:
        admission._close_for_test()
        pinned.close()
