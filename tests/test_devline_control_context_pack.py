"""Safety and determinism tests for devline Context Pack creation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from workbench.development_control import context_pack
from workbench.development_control.context_pack import (
    ContextPackDriftError,
    ContextPackError,
    ContextPackRequest,
    create_context_pack,
    record_context_refresh_required,
    record_context_rescope_required,
    refresh_context_pack,
    rescope_context_pack,
    verify_context_pack,
)
from workbench.development_control.events import validate_event
from workbench.development_control.promotion import PromotionPolicy, promote
from workbench.development_control.retrospective import generate_retrospective


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request(**overrides: object) -> ContextPackRequest:
    values: dict[str, object] = {
        "objective": "Make the integration control plane reproducible.",
        "baseline_sha": "a" * 40,
        "tags": ("lmm", "integration"),
        "affected_paths": ("backend/workbench/models",),
        "lesson_keys": ("stable-result-contract",),
        "allowed_paths": ("backend/workbench/development_control",),
        "protected_paths": ("scripts/gate.sh",),
        "dependencies": ("Python standard library",),
        "tests": ("tests/test_devline_control_context_pack.py",),
        "known_gates": ("focused pytest",),
    }
    values.update(overrides)
    return ContextPackRequest(**values)  # type: ignore[arg-type]


def _write_index(repo: Path, rows: list[dict[str, object]]) -> None:
    directory = repo / ".agent" / "development-control"
    directory.mkdir(parents=True)
    (directory / "retrospective-index.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _history(
    line_id: str,
    completed_at: str,
    summary: str,
    *,
    tags: tuple[str, ...] = ("lmm",),
    paths: tuple[str, ...] = ("backend/workbench/models",),
    lesson_keys: tuple[str, ...] = ("stable-result-contract",),
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "line_id": line_id,
        "completed_at": completed_at,
        "tags": list(tags),
        "affected_paths": list(paths),
        "lesson_keys": list(lesson_keys),
        "summary": summary,
        "summary_sha256": _sha256(summary),
    }


def _promotion_event(number: int) -> dict[str, object]:
    timestamp = f"2026-07-19T12:00:0{number}.000Z"
    return validate_event(
        {
            "schema_version": 1,
            "event_id": f"00000000-0000-4000-8000-00000000000{number}",
            "timestamp": timestamp,
            "type": "FAILURE",
            "subtype": "rule_check",
            "stage": "review",
            "cause_status": "known",
            "cause": "a test rule needs evidence",
            "evidence": {"kind": "test", "ref": "tests/test_context.py", "sha256": "a" * 64, "observed_at": timestamp},
            "impact": "keeps the formal rule set trustworthy",
            "preventability": "preventable",
            "resolution": "resolved",
            "lesson": "validate global rules before freezing them",
            "incident_id": f"00000000-0000-4000-8000-0000000001{number:02d}",
            "lesson_key": "formal-rule-validation",
            "links": [],
        },
        previous_sha256="0" * 64,
    )


def _policy() -> PromotionPolicy:
    return PromotionPolicy(
        lesson_key="formal-rule-validation",
        rule_id="formal-rule-validation",
        kind="mechanical",
        scope="development control",
        enforcement_point="focused pytest",
        false_positive_risk="only this control rule",
        verification_method="run focused pytest",
        test_marker="tests/test_context.py",
    )


def test_create_context_pack_creates_formal_files_and_first_event(tmp_path: Path) -> None:
    _write_index(
        tmp_path,
        [_history("wo-a-agent", "2026-07-18T10:00:00.000Z", "Keep result packets versioned.")],
    )

    result = create_context_pack(tmp_path, "integration-v173", _request())

    line = tmp_path / ".agent" / "devlines" / "integration-v173"
    assert {path.name for path in line.iterdir()} == {
        "RETROSPECTIVE.md",
        "context-pack.manifest.json",
        "context-pack.md",
        "events.jsonl",
        "events.jsonl.anchor",
    }
    assert result.manifest_path == line / "context-pack.manifest.json"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["history"]["selected"][0]["line_id"] == "wo-a-agent"
    event = json.loads((line / "events.jsonl").read_text(encoding="utf-8"))
    assert event["type"] == "STATE_CHANGE"
    assert event["subtype"] == "line_started"
    assert event["evidence"]["sha256"] == result.manifest_sha256
    assert verify_context_pack(tmp_path, "integration-v173").manifest_sha256 == result.manifest_sha256


def test_selection_is_deterministic_and_records_unselected_reasons(tmp_path: Path) -> None:
    rows = [
        _history("older", "2026-07-10T10:00:00.000Z", "older matching summary"),
        _history("newer", "2026-07-11T10:00:00.000Z", "newer matching summary"),
        _history("unrelated", "2026-07-12T10:00:00.000Z", "unrelated", tags=("ui",), paths=("frontend",), lesson_keys=("ui-layout",)),
        _history("too-big-for-budget", "2026-07-13T10:00:00.000Z", "x" * (80 * 1024 - 30)),
    ]
    _write_index(tmp_path, rows)

    create_context_pack(tmp_path, "integration-v173", _request())
    manifest = json.loads(
        (tmp_path / ".agent" / "devlines" / "integration-v173" / "context-pack.manifest.json").read_text(encoding="utf-8")
    )

    assert [item["line_id"] for item in manifest["history"]["selected"]] == ["too-big-for-budget", "newer"]
    assert {item["line_id"]: item["reason"] for item in manifest["history"]["excluded"]} == {
        "older": "byte_budget",
        "unrelated": "no_relevance",
    }
    assert [item["line_id"] for item in manifest["history"]["all_summary_hashes"]] == [
        "newer",
        "older",
        "too-big-for-budget",
        "unrelated",
    ]


@pytest.mark.parametrize(
    ("line_id", "context_request"),
    [
        ("Bad/line", _request()),
        ("integration-v173", _request(objective="")),
        ("integration-v173", _request(baseline_sha="not-a-sha")),
    ],
)
def test_invalid_start_input_fails_before_creating_line(tmp_path: Path, line_id: str, context_request: ContextPackRequest) -> None:
    with pytest.raises(ContextPackError):
        create_context_pack(tmp_path, line_id, context_request)
    assert not (tmp_path / ".agent" / "devlines" / "integration-v173").exists()


def test_rejects_corrupt_or_oversized_history_and_symlinked_control_path(tmp_path: Path) -> None:
    _write_index(tmp_path, [_history("too-large", "2026-07-18T10:00:00.000Z", "x" * (80 * 1024 + 1))])
    with pytest.raises(ContextPackError, match="history summary"):
        create_context_pack(tmp_path, "integration-v173", _request())
    assert not (tmp_path / ".agent" / "devlines" / "integration-v173").exists()

    index = tmp_path / ".agent" / "development-control" / "retrospective-index.jsonl"
    index.unlink()
    target = tmp_path / "outside-index.jsonl"
    target.write_text("", encoding="utf-8")
    index.symlink_to(target)
    with pytest.raises(ContextPackError, match="symlink"):
        create_context_pack(tmp_path, "integration-v173", _request())

    index.unlink()
    index.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ContextPackError, match="retrospective index"):
        create_context_pack(tmp_path, "integration-v173", _request())


def test_rule_drift_requires_explicit_refresh_without_overwriting_pack(tmp_path: Path) -> None:
    directory = tmp_path / ".agent" / "development-control"
    directory.mkdir(parents=True)
    rules = {"schema_version": 1, "rules": []}
    (directory / "global-rules.json").write_text(json.dumps(rules), encoding="utf-8")
    created = create_context_pack(tmp_path, "integration-v173", _request())
    pack = created.context_pack_path.read_bytes()
    manifest = created.manifest_path.read_bytes()

    promote(directory, [_promotion_event(1), _promotion_event(2)], policies=[_policy()])

    with pytest.raises(ContextPackDriftError, match="CONTEXT_REFRESH_REQUIRED"):
        verify_context_pack(tmp_path, "integration-v173")
    assert created.context_pack_path.read_bytes() == pack
    assert created.manifest_path.read_bytes() == manifest


def test_context_pack_rejects_unvalidated_promotion_records(tmp_path: Path) -> None:
    directory = tmp_path / ".agent" / "development-control"
    directory.mkdir(parents=True)
    (directory / "global-rules.json").write_text('{"schema_version":1,"rules":[{"rule_id":"forged"}]}', encoding="utf-8")

    with pytest.raises(ContextPackError, match="global rules"):
        create_context_pack(tmp_path, "integration-v173", _request())


def test_explicit_refresh_records_drift_then_refreshes_pack_and_preserves_objective(tmp_path: Path) -> None:
    directory = tmp_path / ".agent" / "development-control"
    directory.mkdir(parents=True)
    created = create_context_pack(tmp_path, "integration-v173", _request(objective="Keep the true integration baseline reproducible."))
    promote(directory, [_promotion_event(1), _promotion_event(2)], policies=[_policy()])

    with pytest.raises(ContextPackDriftError):
        verify_context_pack(tmp_path, "integration-v173")
    required = record_context_refresh_required(tmp_path, "integration-v173")
    refreshed = refresh_context_pack(tmp_path, "integration-v173")

    assert required.old_manifest_sha256 == created.manifest_sha256
    assert refreshed.manifest_sha256 != created.manifest_sha256
    assert verify_context_pack(tmp_path, "integration-v173") == refreshed
    events = [json.loads(line) for line in (tmp_path / ".agent" / "devlines" / "integration-v173" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [event["subtype"] for event in events] == ["line_started", "context_refresh_required", "context_refreshed"]
    text = generate_retrospective(tmp_path / ".agent" / "devlines", "integration-v173").read_text(encoding="utf-8")
    assert "Keep the true integration baseline reproducible." in text


def test_explicit_rescope_records_old_and_new_manifest_generations_without_mutating_early(tmp_path: Path) -> None:
    created = create_context_pack(
        tmp_path,
        "integration-v173",
        _request(objective="Keep the original evidence and history while correcting scope."),
    )
    original_pack = created.context_pack_path.read_bytes()
    original_manifest = created.manifest_path.read_bytes()
    original = json.loads(original_manifest)

    required = record_context_rescope_required(
        tmp_path,
        "integration-v173",
        affected_paths=("backend/workbench/services", "tests/test_results_service.py"),
        allowed_paths=(
            "backend/workbench/services/pinned_run_directory.py",
            "backend/workbench/engine/packs/linear_mixed_effects",
            "tests/test_pinned_run_directory.py",
        ),
    )

    assert required.old_manifest_sha256 == created.manifest_sha256
    assert required.new_manifest_sha256 != created.manifest_sha256
    assert created.context_pack_path.read_bytes() == original_pack
    assert created.manifest_path.read_bytes() == original_manifest

    rescoped = rescope_context_pack(
        tmp_path,
        "integration-v173",
        affected_paths=("backend/workbench/services", "tests/test_results_service.py"),
        allowed_paths=(
            "backend/workbench/services/pinned_run_directory.py",
            "backend/workbench/engine/packs/linear_mixed_effects",
            "tests/test_pinned_run_directory.py",
        ),
    )

    replacement = json.loads(rescoped.manifest_path.read_text(encoding="utf-8"))
    assert rescoped.manifest_sha256 == required.new_manifest_sha256
    assert replacement["previous_manifest_sha256"] == created.manifest_sha256
    assert replacement["refresh_generation"] == original["refresh_generation"] + 1
    assert replacement["request"]["affected_paths"] == ["backend/workbench/services", "tests/test_results_service.py"]
    assert replacement["request"]["allowed_paths"] == [
        "backend/workbench/services/pinned_run_directory.py",
        "backend/workbench/engine/packs/linear_mixed_effects",
        "tests/test_pinned_run_directory.py",
    ]
    assert replacement["request"]["objective"] == original["request"]["objective"]
    assert replacement["history"] == original["history"]
    assert replacement["rules"] == original["rules"]
    assert verify_context_pack(tmp_path, "integration-v173") == rescoped

    events = [
        json.loads(line)
        for line in (tmp_path / ".agent" / "devlines" / "integration-v173" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["subtype"] for event in events] == ["line_started", "context_rescope_required", "context_rescoped"]
    assert events[-2]["impact"] == {
        "new_allowed_paths": [
            "backend/workbench/services/pinned_run_directory.py",
            "backend/workbench/engine/packs/linear_mixed_effects",
            "tests/test_pinned_run_directory.py",
        ],
        "new_manifest_sha256": rescoped.manifest_sha256,
        "old_allowed_paths": ["backend/workbench/development_control"],
        "old_manifest_sha256": created.manifest_sha256,
    }
    assert events[-1]["impact"] == events[-2]["impact"]


def test_rescope_rejects_non_relative_or_symlinked_paths_before_any_event_or_pack_mutation(tmp_path: Path) -> None:
    created = create_context_pack(tmp_path, "integration-v173", _request())
    original_pack = created.context_pack_path.read_bytes()
    original_manifest = created.manifest_path.read_bytes()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ContextPackError, match="symlink"):
        record_context_rescope_required(
            tmp_path,
            "integration-v173",
            affected_paths=("backend/workbench/services",),
            allowed_paths=("linked/private",),
        )
    with pytest.raises(ContextPackError, match="repository-relative"):
        record_context_rescope_required(tmp_path, "integration-v173", affected_paths=("../outside",))
    with pytest.raises(ContextPackError, match="at least one"):
        record_context_rescope_required(
            tmp_path,
            "integration-v173",
            affected_paths=("backend/workbench/services",),
            allowed_paths=(),
        )
    with pytest.raises(ContextPackError, match="too broad"):
        record_context_rescope_required(
            tmp_path,
            "integration-v173",
            affected_paths=("backend/workbench/services",),
            allowed_paths=("backend",),
        )

    assert created.context_pack_path.read_bytes() == original_pack
    assert created.manifest_path.read_bytes() == original_manifest
    events = (tmp_path / ".agent" / "devlines" / "integration-v173" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 1


def test_rescope_allows_a_concrete_top_level_backend_workbench_file(tmp_path: Path) -> None:
    """Concrete files are safe allowlist entries even at backend/workbench depth."""

    create_context_pack(tmp_path, "integration-v173", _request())

    required = record_context_rescope_required(
        tmp_path,
        "integration-v173",
        affected_paths=("backend/workbench/prediction.py",),
        allowed_paths=("backend/workbench/prediction.py",),
    )
    rescoped = rescope_context_pack(
        tmp_path,
        "integration-v173",
        affected_paths=("backend/workbench/prediction.py",),
        allowed_paths=("backend/workbench/prediction.py",),
    )

    assert rescoped.manifest_sha256 == required.new_manifest_sha256
    manifest = json.loads(rescoped.manifest_path.read_text(encoding="utf-8"))
    assert manifest["request"]["allowed_paths"] == ["backend/workbench/prediction.py"]


def test_rescope_recovers_only_the_already_audited_generation_after_interrupted_publish(tmp_path: Path) -> None:
    created = create_context_pack(tmp_path, "integration-v173", _request())
    required = record_context_rescope_required(
        tmp_path,
        "integration-v173",
        affected_paths=("backend/workbench/services",),
    )
    line = tmp_path / ".agent" / "devlines" / "integration-v173"
    old_manifest = json.loads(line.joinpath("context-pack.manifest.json").read_text(encoding="utf-8"))
    old_manifest.pop("manifest_sha256")
    plan = context_pack._rescope_plan(  # deliberate fault injection: stop after atomic replacement
        tmp_path,
        "integration-v173",
        old_manifest,
        created.manifest_sha256,
        ("backend/workbench/services",),
        None,
    )
    context_pack._atomic_replace_file(line, "context-pack.md", plan.pack)
    context_pack._atomic_replace_file(line, "context-pack.manifest.json", plan.manifest_bytes)

    repeated_required = record_context_rescope_required(
        tmp_path,
        "integration-v173",
        affected_paths=("backend/workbench/services",),
    )
    completed = rescope_context_pack(
        tmp_path,
        "integration-v173",
        affected_paths=("backend/workbench/services",),
    )

    assert repeated_required == required
    assert completed.manifest_sha256 == required.new_manifest_sha256
    events = [
        json.loads(row)
        for row in line.joinpath("events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["subtype"] for event in events] == ["line_started", "context_rescope_required", "context_rescoped"]


def test_rescope_without_allow_path_preserves_the_existing_allowlist(tmp_path: Path) -> None:
    created = create_context_pack(tmp_path, "integration-v173", _request())
    old_manifest = json.loads(created.manifest_path.read_text(encoding="utf-8"))
    record_context_rescope_required(
        tmp_path,
        "integration-v173",
        affected_paths=("backend/workbench/services",),
    )
    rescoped = rescope_context_pack(
        tmp_path,
        "integration-v173",
        affected_paths=("backend/workbench/services",),
    )

    replacement = json.loads(rescoped.manifest_path.read_text(encoding="utf-8"))
    assert replacement["request"]["allowed_paths"] == old_manifest["request"]["allowed_paths"]
