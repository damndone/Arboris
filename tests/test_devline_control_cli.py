"""Public formal CLI regression tests; legacy devline_memory is not invoked."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).parents[1] / "scripts" / "devline_control.py"
    return subprocess.run(
        [sys.executable, str(script), "--root", str(repo), *args],
        cwd=repo,
        env={"PYTHONPATH": str(Path(__file__).parents[1] / "backend")},
        text=True,
        capture_output=True,
        check=False,
    )


def test_formal_cli_starts_and_verifies_a_line_from_a_repo_relative_objective(tmp_path: Path) -> None:
    (tmp_path / "objective.md").write_text("Freeze a safe integration boundary.\n", encoding="utf-8")

    started = _run(
        tmp_path,
        "start",
        "--line",
        "integration-v173",
        "--objective",
        "objective.md",
        "--baseline-sha",
        "a" * 40,
        "--tag",
        "integration",
        "--affected-path",
        "backend/workbench",
    )

    assert started.returncode == 0, started.stderr
    assert json.loads(started.stdout)["line_id"] == "integration-v173"
    verified = _run(tmp_path, "verify", "--line", "integration-v173")
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["line_id"] == "integration-v173"
    assert not (tmp_path / ".agent" / "development").exists()


def test_repository_instructions_quarantine_legacy_protocol_and_name_formal_cli() -> None:
    instructions = (Path(__file__).parents[1] / "AGENTS.md").read_text(encoding="utf-8")

    assert "scripts/devline_control.py start" in instructions
    assert "rescope-context --line" in instructions
    assert "migration evidence only" in instructions
    assert "scripts/devline_memory.py --root" not in instructions


def test_verify_all_checks_formal_lines_but_reports_quarantined_legacy_lines(tmp_path: Path) -> None:
    (tmp_path / "objective.md").write_text("Freeze a safe integration boundary.\n", encoding="utf-8")
    started = _run(
        tmp_path,
        "start",
        "--line",
        "integration-v173",
        "--objective",
        "objective.md",
        "--baseline-sha",
        "a" * 40,
    )
    assert started.returncode == 0, started.stderr
    legacy = tmp_path / ".agent" / "devlines" / "wo-a"
    legacy.mkdir()
    for name in ("CONTEXT_PACK.md", "RETROSPECTIVE.md", "events.jsonl", "line.json"):
        (legacy / name).write_text("legacy\n", encoding="utf-8")

    verified = _run(tmp_path, "verify", "--all")

    assert verified.returncode == 0, verified.stderr
    result = json.loads(verified.stdout)
    assert result["verified_lines"] == ["integration-v173"]
    assert result["quarantined_legacy_lines"] == ["wo-a"]

    rejected = _run(tmp_path, "archive-events", "--line", "wo-a")
    assert rejected.returncode == 2
    assert not (legacy / "events.jsonl.gz").exists()
    assert (legacy / "events.jsonl").read_bytes() == b"legacy\n"


def test_event_archive_preserves_formal_consumers_and_accepts_new_events(tmp_path: Path) -> None:
    (tmp_path / "objective.md").write_text("Preserve the audit trail.\n", encoding="utf-8")
    line_id = "integration-v173"
    started = _run(tmp_path, "start", "--line", line_id, "--objective", "objective.md", "--baseline-sha", "a" * 40)
    assert started.returncode == 0, started.stderr
    line = tmp_path / ".agent" / "devlines" / line_id
    live = line / "events.jsonl"
    anchor = line / "events.jsonl.anchor"
    archive = line / "events.jsonl.gz"
    retrospective = line / "RETROSPECTIVE.md"
    original, original_anchor, original_report = live.read_bytes(), anchor.read_bytes(), retrospective.read_bytes()

    archived = _run(tmp_path, "archive-events", "--line", line_id)
    assert archived.returncode == 0, archived.stderr
    receipt = json.loads(archived.stdout)
    assert receipt["raw_sha256"] == hashlib.sha256(original).hexdigest()
    assert receipt["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert receipt["archive"] == f".agent/devlines/{line_id}/events.jsonl.gz"
    assert receipt["event_count"] == 1
    assert live.read_bytes() == b""
    assert gzip.decompress(archive.read_bytes()) == original
    assert anchor.read_bytes() == original_anchor
    exported = _run(tmp_path, "read-events", "--line", line_id)
    assert exported.returncode == 0, exported.stderr
    assert exported.stdout.encode("utf-8") == original

    for args in (("verify", "--all"), ("retrospective", "--line", line_id), ("promote", "--all"), ("index", "--all")):
        result = _run(tmp_path, *args)
        assert result.returncode == 0, result.stderr
    assert retrospective.read_bytes() == original_report

    rescoped = _run(tmp_path, "rescope-context", "--line", line_id, "--affected-path", "tests")
    assert rescoped.returncode == 0, rescoped.stderr
    assert json.loads(live.read_bytes().splitlines()[0])["prev_event_sha256"] == receipt["tail_event_sha256"]
    combined = original + live.read_bytes()
    assert _run(tmp_path, "read-events", "--line", line_id).stdout.encode("utf-8") == combined

    archived_again = _run(tmp_path, "archive-events", "--line", line_id)
    assert archived_again.returncode == 0, archived_again.stderr
    assert gzip.decompress(archive.read_bytes()) == combined
    assert live.read_bytes() == b""
    assert _run(tmp_path, "archive-events", "--line", line_id).stdout == archived_again.stdout
    assert _run(tmp_path, "verify", "--all").returncode == 0


def test_promote_all_orchestrates_only_formal_lines(tmp_path: Path) -> None:
    (tmp_path / "objective.md").write_text("Freeze a safe integration boundary.\n", encoding="utf-8")
    started = _run(
        tmp_path,
        "start",
        "--line",
        "integration-v173",
        "--objective",
        "objective.md",
        "--baseline-sha",
        "a" * 40,
    )
    assert started.returncode == 0, started.stderr

    promoted = _run(tmp_path, "promote", "--all")

    assert promoted.returncode == 0, promoted.stderr
    assert json.loads(promoted.stdout)["verified_lines"] == ["integration-v173"]


def test_index_all_records_no_completed_line_as_empty_index(tmp_path: Path) -> None:
    (tmp_path / "objective.md").write_text("Freeze a safe integration boundary.\n", encoding="utf-8")
    started = _run(
        tmp_path,
        "start",
        "--line",
        "integration-v173",
        "--objective",
        "objective.md",
        "--baseline-sha",
        "a" * 40,
    )
    assert started.returncode == 0, started.stderr

    indexed = _run(tmp_path, "index", "--all")

    assert indexed.returncode == 0, indexed.stderr
    result = json.loads(indexed.stdout)
    assert result["indexed_lines"] == []
    assert result["in_progress_lines"] == ["integration-v173"]
    assert (tmp_path / ".agent" / "development-control" / "retrospective-index.jsonl").read_bytes() == b""


def test_completion_append_regenerates_retrospective_and_verify_rejects_a_stale_completed_report(tmp_path: Path) -> None:
    (tmp_path / "objective.md").write_text("Finish a bounded development line.\n", encoding="utf-8")
    started = _run(
        tmp_path,
        "start",
        "--line",
        "integration-v173",
        "--objective",
        "objective.md",
        "--baseline-sha",
        "a" * 40,
    )
    assert started.returncode == 0, started.stderr
    event = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "timestamp": "2026-07-20T01:00:00.000Z",
        "type": "STATE_CHANGE",
        "subtype": "accepted",
        "stage": "integration",
        "cause_status": "known",
        "cause": "all declared work has accepted evidence",
        "evidence": {
            "kind": "test",
            "ref": "tests/test_devline_control_cli.py::test_completion_append_regenerates_retrospective_and_verify_rejects_a_stale_completed_report",
            "sha256": "b" * 64,
            "observed_at": "2026-07-20T01:00:00.000Z",
        },
        "impact": "the completed line has an evidence-bound closing report",
        "preventability": "not_preventable",
        "resolution": "resolved",
        "lesson": "completion must regenerate its derived retrospective",
        "incident_id": str(uuid.uuid4()),
        "lesson_key": "completion-retrospective-binding",
        "links": [],
        "state_from": "INTEGRATION_PENDING",
        "state_to": "COMPLETED",
    }
    (tmp_path / "completion-event.json").write_text(json.dumps(event), encoding="utf-8")

    appended = _run(tmp_path, "append", "--line", "integration-v173", "--event-file", "completion-event.json")

    assert appended.returncode == 0, appended.stderr
    report = tmp_path / ".agent" / "devlines" / "integration-v173" / "RETROSPECTIVE.md"
    assert "COMPLETED" in report.read_text(encoding="utf-8")
    assert _run(tmp_path, "verify", "--line", "integration-v173").returncode == 0
    report.write_text("stale\n", encoding="utf-8")
    assert _run(tmp_path, "verify", "--line", "integration-v173").returncode == 2


def test_rescope_context_cli_accepts_explicit_allowlist_replacement_and_returns_digest_pair(tmp_path: Path) -> None:
    (tmp_path / "objective.md").write_text("Freeze a safe integration boundary.\n", encoding="utf-8")
    started = _run(
        tmp_path,
        "start",
        "--line",
        "integration-v173",
        "--objective",
        "objective.md",
        "--baseline-sha",
        "a" * 40,
        "--affected-path",
        "backend/workbench/models",
    )
    assert started.returncode == 0, started.stderr
    old_manifest = json.loads(started.stdout)["manifest_sha256"]

    rescoped = _run(
        tmp_path,
        "rescope-context",
        "--line",
        "integration-v173",
        "--affected-path",
        "backend/workbench/services",
        "--allow-path",
        "backend/workbench/services/pinned_run_directory.py",
    )

    assert rescoped.returncode == 0, rescoped.stderr
    result = json.loads(rescoped.stdout)
    assert result["old_manifest_sha256"] == old_manifest
    assert result["manifest_sha256"] != old_manifest
    manifest = json.loads(
        (tmp_path / ".agent" / "devlines" / "integration-v173" / "context-pack.manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["request"]["allowed_paths"] == ["backend/workbench/services/pinned_run_directory.py"]
    unsupported = _run(
        tmp_path,
        "rescope-context",
        "--line",
        "integration-v173",
        "--affected-path",
        "backend/workbench/services",
        "--objective",
        "must-not-be-accepted",
    )
    assert unsupported.returncode == 2
