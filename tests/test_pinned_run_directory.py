from __future__ import annotations

import json
import os
import inspect
from pathlib import Path

import pytest


def _representation() -> dict[str, object]:
    return {
        "schema_version": 1,
        "model_type": "linear_mixed_effects",
        "model_options": {
            "subject_id": "subject",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        "model_options_binding": {
            "owner_model_type": "linear_mixed_effects",
            "owner_model_id": "linear_mixed_effects_1",
            "producer_version": "linear_mixed_effects@1.0",
            "input_contract_version": "1.0",
            "normalized_options_hash": "a" * 64,
        },
    }


def _run(tmp_path: Path, run_id: str = "run-1") -> Path:
    run_root = tmp_path / run_id
    run_root.mkdir()
    (run_root / "run_inputs.json").write_text(json.dumps({"executed_payload": _representation()}))
    return run_root


def test_pinned_directory_rejects_unsafe_ids_before_filesystem_access(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import PinnedRunError, open_pinned_run_directory

    for run_id in ("", ".", "..", "a/b", "a\\b", " a", "é", "a\x00b"):
        with pytest.raises(PinnedRunError, match="RUN_ID_INVALID"):
            open_pinned_run_directory(tmp_path, run_id)


def test_pinned_snapshot_and_closed_capability(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import PinnedRunError, open_pinned_run_directory

    _run(tmp_path)
    pinned = open_pinned_run_directory(tmp_path, "run-1")
    with pinned:
        assert pinned.read_run_inputs_snapshot().value == {
            "executed_payload": _representation()
        }
    with pytest.raises(PinnedRunError, match="PINNED_RUN_CLOSED"):
        pinned.read_run_inputs_snapshot()


def test_pinned_capability_exposes_only_fixed_read_operations(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import PinnedRunDirectory, open_pinned_run_directory

    _run(tmp_path)
    with open_pinned_run_directory(tmp_path, "run-1") as pinned:
        assert pinned.read_run_inputs_snapshot().value["executed_payload"] == _representation()
        for forbidden in ("logical_path", "run_root", "read_regular_snapshot", "read_json_snapshot"):
            assert not hasattr(pinned, forbidden)
    public_methods = {name for name, value in inspect.getmembers(PinnedRunDirectory, inspect.isfunction) if not name.startswith("_")}
    assert public_methods == {
        "close",
        "read_execution_seal",
        "read_lmm_index",
        "read_lmm_terminal_packet",
        "read_run_inputs_snapshot",
        "verify_sealed_execution_input",
    }


def test_pinned_reader_does_not_follow_a_child_symlink(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import PinnedRunError, open_pinned_run_directory

    root = _run(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (root / "run_inputs.json").unlink()
    (root / "run_inputs.json").symlink_to(outside)
    with open_pinned_run_directory(tmp_path, "run-1") as pinned:
        with pytest.raises(PinnedRunError, match="PINNED_RUN_SNAPSHOT_INVALID"):
            pinned.read_run_inputs_snapshot()


def test_fixed_snapshot_reads_exact_pre_fstat_size_once_and_rejects_short_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import PinnedRunError, open_pinned_run_directory

    _run(tmp_path)
    calls: list[int] = []
    original_read = module.os.read

    def short_read(fd: int, size: int) -> bytes:
        calls.append(size)
        return original_read(fd, max(0, size - 2))

    expected_size = (tmp_path / "run-1" / "run_inputs.json").stat().st_size
    monkeypatch.setattr(module.os, "read", short_read)
    with open_pinned_run_directory(tmp_path, "run-1") as pinned:
        with pytest.raises(PinnedRunError, match="PINNED_SNAPSHOT_SHORT_READ"):
            pinned.read_run_inputs_snapshot()
    assert calls == [expected_size + 1]


def test_fixed_snapshot_rejects_tail_added_after_pre_fstat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import PinnedRunError, open_pinned_run_directory

    _run(tmp_path)
    original_read = module.os.read

    def appended_tail(fd: int, size: int) -> bytes:
        return original_read(fd, size) + b" "

    monkeypatch.setattr(module.os, "read", appended_tail)
    with open_pinned_run_directory(tmp_path, "run-1") as pinned:
        with pytest.raises(PinnedRunError, match="PINNED_SNAPSHOT_SIZE_CHANGED"):
            pinned.read_run_inputs_snapshot()


def test_executed_input_seal_is_atomic_idempotent_and_divergence_closed(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import (
        PinnedRunError,
        open_pinned_run_directory,
        seal_executed_input_v1,
    )

    _run(tmp_path)
    with open_pinned_run_directory(tmp_path, "run-1") as pinned:
        first = seal_executed_input_v1(pinned, _representation())
        seal_path = tmp_path / "run-1" / "artifacts" / "execution" / "executed_input_v1.json"
        before = seal_path.stat().st_ino
        assert seal_executed_input_v1(pinned, _representation()) == first
        assert seal_path.stat().st_ino == before
        changed = _representation()
        changed["model_options"] = {**changed["model_options"], "random_slope": False}
        with pytest.raises(PinnedRunError, match="EXECUTED_INPUT_SEAL_DIVERGENCE"):
            seal_executed_input_v1(pinned, changed)
        seal_path.write_bytes(b"{}")
        with pytest.raises(PinnedRunError, match="LMM_EXECUTION_BINDING_INVALID"):
            pinned.verify_sealed_execution_input(first)


def test_pinned_root_survives_path_replacement(tmp_path: Path) -> None:
    from workbench.services.pinned_run_directory import open_pinned_run_directory

    root = _run(tmp_path)
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    (replacement / "run_inputs.json").write_text('{"from":"replacement"}')
    with open_pinned_run_directory(tmp_path, "run-1") as pinned:
        moved = tmp_path / "original"
        root.rename(moved)
        (tmp_path / "run-1").symlink_to(replacement, target_is_directory=True)
        assert pinned.read_run_inputs_snapshot().value["executed_payload"] == _representation()


def test_pinned_directory_fails_closed_without_required_os_primitives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.services.pinned_run_directory as module
    from workbench.services.pinned_run_directory import PinnedRunError, open_pinned_run_directory

    monkeypatch.setattr(module, "_O_NOFOLLOW", 0)
    with pytest.raises(PinnedRunError, match="PINNED_RUN_UNSUPPORTED"):
        open_pinned_run_directory(tmp_path, "run-1")
