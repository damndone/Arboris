"""P7 browser-acceptance infrastructure derives its denominator from production."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


_PROTOCOL_TOKENS = (
    "operation.multi_step",
    "model.genesis",
    "capability_id",
)


def test_current_p7_acceptance_denominator_is_deliberately_pinned() -> None:
    """A red count means registration scope changed and this record needs review."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    operation_ids = p7_pack_registry.operation_ids()
    pack_families = {
        p7_pack_registry.get(operation_id).pack_family
        for operation_id in operation_ids
    }
    assert (len(operation_ids), len(pack_families)) == (64, 18)


class _InjectedRegistry:
    def __init__(self, base: object, operation: object) -> None:
        self._base = base
        self._operation = operation

    def operation_ids(self) -> tuple[str, ...]:
        return tuple(sorted((*self._base.operation_ids(), self._operation.operation_id)))

    def get(self, operation_id: str) -> object:
        if operation_id == self._operation.operation_id:
            return self._operation
        return self._base.get(operation_id)


def _fake_operation(operation_id: str = "future.robust_location") -> object:
    return SimpleNamespace(
        operation_id=operation_id,
        pack_family="future_robust",
        input_mode="typed",
        request_schema=SimpleNamespace(
            required_bindings=("values",),
            binding_shapes={"values": "column"},
            required_options=(),
            option_shapes={},
            option_enums={},
        ),
    )


def test_matrix_keys_equal_live_registry_and_prompts_are_user_language() -> None:
    """A registry addition changes the matrix; no protocol vocabulary leaks to users."""

    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.qa.p7_acceptance import build_acceptance_matrix

    rows = build_acceptance_matrix(registry=p7_pack_registry)
    assert {row.operation_id for row in rows} == set(p7_pack_registry.operation_ids())
    assert len(rows) == len(p7_pack_registry.operation_ids())
    for row in rows:
        prompt = row.prompt.casefold()
        assert prompt.strip()
        assert all(token not in prompt for token in _PROTOCOL_TOKENS)
        assert row.pack_family == p7_pack_registry.get(row.operation_id).pack_family
        assert row.fixture_profile.status in {"ready", "blocked"}
        assert row.expected_contract.parent_operation_id == "operation.multi_step"
        assert row.expected_contract.child_operation_id == row.operation_id
        assert row.expected_contract.requires_visible_user_confirmation is True


def test_injected_registry_operation_adds_a_blocked_row_without_a_second_list() -> None:
    """Dependency injection makes a future declaration expose hard-coded projection bugs."""

    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.qa.p7_acceptance import build_acceptance_matrix

    live_keys = {
        row.operation_id for row in build_acceptance_matrix(registry=p7_pack_registry)
    }
    injected = _InjectedRegistry(p7_pack_registry, _fake_operation())
    rows = build_acceptance_matrix(registry=injected)
    injected_keys = {row.operation_id for row in rows}

    assert injected_keys == set(injected.operation_ids())
    assert injected_keys != live_keys
    future = next(row for row in rows if row.operation_id == "future.robust_location")
    assert future.fixture_profile.status == "blocked"
    assert future.fixture_profile.blocker_code == "missing_fixture"
    assert future.fixture_profile.required_bindings == ("values",)


def test_caller_fixture_profile_can_make_one_derived_row_ready() -> None:
    """Fixture readiness is supplied separately without changing the denominator."""

    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.qa.p7_acceptance import build_acceptance_matrix

    rows = build_acceptance_matrix(
        registry=p7_pack_registry,
        fixture_profiles={
            "missingness.profile": {
                "status": "ready",
                "fixture_id": "survey_missingness_v1",
                "source": "generated_example",
            }
        },
    )
    selected = next(row for row in rows if row.operation_id == "missingness.profile")
    assert selected.fixture_profile.status == "ready"
    assert selected.fixture_profile.fixture_id == "survey_missingness_v1"
    assert selected.fixture_profile.blocker_code is None


def test_family_batches_cover_every_live_operation_and_injected_family() -> None:
    """Family packets are a registry projection, never a second operation list."""

    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.qa.p7_acceptance import (
        build_acceptance_batches,
        build_acceptance_matrix,
    )

    live_batches = build_acceptance_batches(
        build_acceptance_matrix(registry=p7_pack_registry)
    )
    assert {
        operation_id
        for batch in live_batches
        for operation_id in batch.operation_ids
    } == set(p7_pack_registry.operation_ids())
    assert len({batch.pack_family for batch in live_batches}) == len(live_batches)
    assert all(
        token not in batch.prompt.casefold()
        for batch in live_batches
        for token in _PROTOCOL_TOKENS
    )

    injected = _InjectedRegistry(p7_pack_registry, _fake_operation())
    injected_batches = build_acceptance_batches(
        build_acceptance_matrix(registry=injected)
    )
    future = next(
        batch for batch in injected_batches if batch.pack_family == "future_robust"
    )
    assert future.operation_ids == ("future.robust_location",)
    assert future.status == "blocked"
    assert future.blocker_code == "incomplete_family_fixture"


def test_family_fixture_catalog_expands_from_live_family_membership() -> None:
    """One family fixture makes all live members ready without naming them twice."""

    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.qa.p7_acceptance import (
        build_acceptance_batches,
        build_acceptance_matrix,
        resolve_fixture_catalog,
    )

    profiles = resolve_fixture_catalog(
        registry=p7_pack_registry,
        catalog={
            "families": {
                "missing_data": {
                    "status": "ready",
                    "fixture_id": "missing_data_browser_v1",
                    "source": "generated_example",
                }
            }
        },
    )
    rows = build_acceptance_matrix(
        registry=p7_pack_registry,
        fixture_profiles=profiles,
    )
    expected_ids = {
        operation_id
        for operation_id in p7_pack_registry.operation_ids()
        if p7_pack_registry.get(operation_id).pack_family == "missing_data"
    }
    assert set(profiles) == expected_ids
    batch = next(
        item
        for item in build_acceptance_batches(rows)
        if item.pack_family == "missing_data"
    )
    assert set(batch.operation_ids) == expected_ids
    assert batch.status == "ready"
    assert batch.fixture_id == "missing_data_browser_v1"

    injected = _InjectedRegistry(p7_pack_registry, _fake_operation())
    injected_profiles = resolve_fixture_catalog(
        registry=injected,
        catalog={
            "families": {
                "future_robust": {
                    "status": "ready",
                    "fixture_id": "future_browser_v1",
                    "source": "generated_example",
                }
            }
        },
    )
    assert set(injected_profiles) == {"future.robust_location"}

    with pytest.raises(ValueError, match="unregistered pack family"):
        resolve_fixture_catalog(
            registry=p7_pack_registry,
            catalog={
                "families": {
                    "guessed_family": {
                        "status": "ready",
                        "fixture_id": "bad",
                        "source": "generated_example",
                    }
                }
            },
        )


def _manifest(tmp_path, **overrides):
    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.qa.p7_acceptance import RatePolicy, build_acceptance_manifest

    values = {
        "registry": p7_pack_registry,
        "git_head": "a" * 40,
        "dirty_digest": "b" * 64,
        "provider": "deepseek",
        "model": "deepseek-v4",
        "rate_policy": RatePolicy(capacity=2, refill_per_second=0.5),
        "created_at": "2026-08-09T12:00:00Z",
        "fixture_profiles": {
            "missingness.profile": {
                "status": "ready",
                "fixture_id": "survey_missingness_v1",
                "source": "generated_example",
            }
        },
    }
    values.update(overrides)
    return build_acceptance_manifest(**values)


def _ready_manifest(tmp_path):
    return _manifest(
        tmp_path,
        fixture_profiles={
            "diagnostics.vif": {
                "status": "ready",
                "fixture_id": "design_frame_v1",
                "source": "generated_example",
            },
            "missingness.profile": {
                "status": "ready",
                "fixture_id": "survey_missingness_v1",
                "source": "generated_example",
            },
        },
    )


def _ready_family_manifest(*families: str, capacity: int = 2):
    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.qa.p7_acceptance import (
        RatePolicy,
        build_acceptance_manifest,
        resolve_fixture_catalog,
    )

    catalog = {
        "families": {
            family: {
                "status": "ready",
                "fixture_id": f"{family}_browser_v1",
                "source": "generated_example",
            }
            for family in families
        }
    }
    return build_acceptance_manifest(
        registry=p7_pack_registry,
        git_head="a" * 40,
        dirty_digest="b" * 64,
        provider="deepseek",
        model="deepseek-v4",
        rate_policy=RatePolicy(capacity=capacity, refill_per_second=0.5),
        created_at="2026-08-09T12:00:00Z",
        fixture_profiles=resolve_fixture_catalog(
            registry=p7_pack_registry,
            catalog=catalog,
        ),
    )


def _completion_evidence(operation_id: str, *, authority=None):
    from workbench.qa.p7_acceptance import CompletionEvidence

    parent_id = "operation_record_parent_1"
    child_id = f"operation_record_child_{operation_id.replace('.', '_')}"
    artifact_id = f"artifact_{operation_id.replace('.', '_')}"
    manifest_digest = authority.manifest_digest if authority else "a" * 64
    submission_id = authority.submission_id if authority else "submission:test"
    attempt_no = authority.attempt_no if authority else 1
    attempt_started_at = authority.attempt_started_at if authority else 100.0
    fixture_id = authority.fixture_id if authority else "fixture_test"
    prompt_sha256 = authority.prompt_sha256 if authority else "b" * 64
    provider = authority.provider if authority else "deepseek"
    model = authority.model if authority else "deepseek-v4"
    operation_ids_digest = (
        authority.operation_ids_digest if authority else "c" * 64
    )
    project_root = authority.project_root if authority else "generated_example"
    revision_recorded_at = datetime.fromtimestamp(
        float(attempt_started_at) + 0.1,
        tz=timezone.utc,
    ).isoformat()
    confirmation_recorded_at = datetime.fromtimestamp(
        float(attempt_started_at) + 0.2,
        tz=timezone.utc,
    ).isoformat()
    return CompletionEvidence(
        evidence_kind="browser_visible_agent",
        manifest_digest=manifest_digest,
        submission_id=submission_id,
        attempt_no=attempt_no,
        attempt_started_at=attempt_started_at,
        fixture_id=fixture_id,
        prompt_sha256=prompt_sha256,
        provider=provider,
        model=model,
        submission_operation_ids_digest=operation_ids_digest,
        project_root=project_root,
        source_run_id="run_source_1",
        source_node_ref="stage:raw",
        source_artifact_id="raw.csv",
        source_artifact_sha256="d" * 64,
        option_revision_recorded_at=revision_recorded_at,
        confirmation_recorded_at=confirmation_recorded_at,
        workflow_plan_fingerprint="sha256:" + "e" * 64,
        agent_session_id="agent_chain_session_1",
        parent_operation_id="operation.multi_step",
        parent_record_id=parent_id,
        parent_record_status="completed",
        parent_record_durable=True,
        child_operation_id=operation_id,
        child_record_id=child_id,
        child_parent_record_id=parent_id,
        child_record_status="completed",
        child_record_durable=True,
        confirmation_id="visible_confirmation_1",
        confirmation_surface="browser",
        confirmation_actor="user",
        confirmation_session_id="agent_chain_session_1",
        confirmation_parent_record_id=parent_id,
        nested_result_status="completed",
        nested_result_parent_record_id=parent_id,
        nested_result_child_record_id=child_id,
        nested_artifact_id=artifact_id,
        artifact_id=artifact_id,
        artifact_sha256="e" * 64,
        artifact_provenance_id="provenance_record_1",
        artifact_producer_record_id=child_id,
    )


def _acceptance_prompt(operation_ids: tuple[str, ...]) -> str:
    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.qa.p7_acceptance import (
        build_acceptance_batches,
        build_acceptance_matrix,
    )

    normalized = tuple(sorted(operation_ids))
    rows = build_acceptance_matrix(registry=p7_pack_registry)
    if len(normalized) == 1:
        return next(
            row.prompt for row in rows if row.operation_id == normalized[0]
        )
    batches = build_acceptance_batches(rows)
    return next(
        batch.prompt for batch in batches if batch.operation_ids == normalized
    )


def _completion_authority_for_fixture(
    project_root: Path,
    operation_ids: tuple[str, ...],
    *,
    attempt_started_at: float = 100.0,
):
    from workbench.qa.p7_acceptance import CompletionAuthority

    normalized = tuple(sorted(operation_ids))
    prompt = _acceptance_prompt(normalized)
    return CompletionAuthority(
        manifest_digest="a" * 64,
        submission_id="submission:acceptance",
        attempt_no=1,
        attempt_started_at=attempt_started_at,
        fixture_id="browser_fixture_v1",
        prompt=prompt,
        prompt_sha256="b" * 64,
        provider="deepseek",
        model="deepseek-v4",
        operation_ids=normalized,
        operation_ids_digest="c" * 64,
        project_root=str(project_root),
    )


def _write_notebook_chain_fixture(
    root: Path,
    *,
    operation_id: str = "missingness.profile",
    operation_ids: tuple[str, ...] | None = None,
    recorded_after: float | None = None,
) -> tuple[Path, object, Path]:
    from workbench.qa.notebook_acceptance_evidence import (
        BrowserConfirmationObservation,
    )
    from workbench.agent.p7_pack_registry import p7_pack_registry

    notebook_id = "nb_acceptance"
    option_id = "opt_acceptance"
    trace_id = "trace_acceptance"
    workflow_id = "workflow_acceptance"
    operations = operation_ids or (operation_id,)
    if not operations or len(set(operations)) != len(operations):
        raise ValueError("fixture operations must be non-empty and unique")
    step_ids = {
        candidate: (
            "target_step"
            if len(operations) == 1
            else f"target_step_{index}"
        )
        for index, candidate in enumerate(operations, start=1)
    }
    run_id = "notebook_source_acceptance"
    artifact_ids = {
        candidate: (
            "workflow_p7_acceptance"
            if len(operations) == 1
            else f"workflow_p7_acceptance_{index}"
        )
        for index, candidate in enumerate(operations, start=1)
    }
    receipt_id = "notebook_workflow_result_acceptance"
    if recorded_after is None:
        revision_at = "2026-08-09T12:00:02+00:00"
        selection_at = "2026-08-09T12:00:03+00:00"
        confirmation_at = "2026-08-09T12:00:04+00:00"
    else:
        revision_at = datetime.fromtimestamp(
            recorded_after + 0.001, tz=timezone.utc
        ).isoformat()
        selection_at = datetime.fromtimestamp(
            recorded_after + 0.002, tz=timezone.utc
        ).isoformat()
        confirmation_at = datetime.fromtimestamp(
            recorded_after + 0.003, tz=timezone.utc
        ).isoformat()
    source_bytes = b"row,value\n1,10\n2,20\n"
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    prompt = _acceptance_prompt(tuple(sorted(operations)))
    target = {
        "run_id": run_id,
        "node_ref": "stage:raw",
        "artifact_id": "raw.csv",
    }
    preconditions = {
        "context_fingerprint": "source-context-acceptance",
        "source_artifact_fingerprint": source_sha,
    }

    def declared_placeholder(shape: str) -> object:
        return {
            "any": None,
            "array": [],
            "boolean": False,
            "column": "row",
            "column_or_columns": "row",
            "columns": ["row"],
            "integer": 1,
            "nullable_string": None,
            "number": 1.0,
            "object": {},
            "string": "value",
        }[shape]

    def operation_spec(candidate: str) -> dict[str, object]:
        declaration = p7_pack_registry.get(candidate)
        schema = declaration.request_schema
        bindings = {
            name: declared_placeholder(schema.binding_shapes[name])
            for name in schema.required_bindings
        }
        options = {
            name: (
                schema.option_enums[name][0]
                if name in schema.option_enums
                else declared_placeholder(schema.option_shapes[name])
            )
            for name in schema.required_options
        }
        return {
            "input_mode": declaration.input_mode,
            "column_bindings": bindings,
            "options": options,
        }

    operation_specs = {
        candidate: operation_spec(candidate)
        for candidate in operations
    }

    def workflow_hash(value: object) -> str:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    compiled_steps: list[dict[str, object]] = []
    step_fingerprints: dict[str, str] = {}
    for candidate in operations:
        step_id = step_ids[candidate]
        spec = {
            **operation_specs[candidate],
            "source_artifact_fingerprint": source_sha,
        }
        identity = {
            "schema_version": "workflow.v1",
            "step_id": step_id,
            "operation_id": candidate,
            "operation_version": "v1",
            "depends_on": [],
            "dependency_fingerprints": [],
            "spec": spec,
            "expected_artifacts": [],
        }
        fingerprint = workflow_hash(identity)
        step_fingerprints[candidate] = fingerprint
        compiled_steps.append(
            {
                "step_id": step_id,
                "operation_id": candidate,
                "operation_version": "v1",
                "depends_on": [],
                "spec": spec,
                "expected_artifacts": [],
                "fingerprint": fingerprint,
            }
        )
    workflow_plan_fingerprint = workflow_hash(
        {
            "schema_version": "workflow.v1",
            "workflow_template": "agent-composed-v1",
            "target": target,
            "steps": compiled_steps,
        }
    )

    def write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def write_jsonl(path: Path, values: list[object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(
                json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
                for value in values
            ),
            encoding="utf-8",
        )

    source_path = root / "runs" / run_id / "raw_snapshot" / "raw.csv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source_bytes)

    notebook_path = root / "notebooks" / notebook_id / "notebook.jsonl"
    write_jsonl(
        notebook_path,
        [
            {
                "record_type": "notebook",
                "notebook_id": notebook_id,
                "projection_source": {
                    "kind": "dataset",
                    "workflow_source": {
                        "run_id": run_id,
                        "node_ref": "stage:raw",
                        "artifact_id": "raw.csv",
                        "source_sha256": source_sha,
                    },
                },
            },
            {
                "record_type": "notebook_state",
                "reason": "set_focus",
                "user_focus": {"goal": prompt},
            },
            {
                "record_type": "notebook_state",
                "reason": "trace_started",
                "trace_id": trace_id,
            },
        ],
    )
    option_path = root / "notebooks" / notebook_id / "options" / f"{option_id}.jsonl"
    write_jsonl(
        option_path,
        [
            {
                "record_type": "revision",
                "option_id": option_id,
                "option_revision": 1,
                "recorded_at": revision_at,
                "typed_proposal": {
                    "operation_id": "operation.multi_step",
                    "target": target,
                    "preconditions": preconditions,
                    "changes": {
                        "steps": [
                            {
                                "step_id": step_ids[candidate],
                                "operation_id": candidate,
                                "spec": operation_specs[candidate],
                            }
                            for candidate in operations
                        ]
                    },
                },
            },
            {
                "record_type": "lifecycle",
                "option_id": option_id,
                "option_revision": 1,
                "actor": "user",
                "reason": "user_selected",
                "from_status": "proposed",
                "to_status": "selected",
                "recorded_at": selection_at,
            },
            {
                "record_type": "lifecycle",
                "option_id": option_id,
                "option_revision": 1,
                "actor": "user",
                "reason": "workflow_confirmed",
                "from_status": "materialized",
                "to_status": "executing",
                "recorded_at": confirmation_at,
            },
            {
                "record_type": "execution",
                "option_id": option_id,
                "option_revision": 1,
                "workflow_id": workflow_id,
                "workflow_plan_fingerprint": workflow_plan_fingerprint,
            },
            {
                "record_type": "execution_result",
                "option_id": option_id,
                "option_revision": 1,
                "committed": True,
                "execution_status": "succeeded",
                "artifact_validation": {
                    "validation_status": "passed",
                    "issues": [],
                },
                "workflow_execution": {
                    "workflow_id": workflow_id,
                    "plan_fingerprint": workflow_plan_fingerprint,
                    "status": "completed",
                },
            },
        ],
    )
    write_jsonl(
        root / "agent-events" / f"{trace_id}.jsonl",
        [
            {
                "event_type": "user.decision.recorded/v1",
                "payload": {
                    "payload": {
                        "decision": "selected",
                        "option_id": option_id,
                        "option_revision": 1,
                    }
                },
            },
            {
                "event_type": "option.execution.completed/v1",
                "payload": {
                    "payload": {
                        "execution_status": "succeeded",
                        "option_id": option_id,
                        "option_revision": 1,
                    }
                },
            },
            {
                "event_type": "artifact_contract.validation.completed/v1",
                "payload": {
                    "payload": {
                        "validation_status": "passed",
                        "option_id": option_id,
                        "option_revision": 1,
                    }
                },
            },
        ],
    )
    write_jsonl(
        root / "workbench" / "workflows" / f"{workflow_id}.jsonl",
        [
            {
                "record_type": "workflow_state",
                "workflow_id": workflow_id,
                "plan_fingerprint": workflow_plan_fingerprint,
                "status": "completed",
                "steps": {
                    step_ids[candidate]: {
                        "step_id": step_ids[candidate],
                        "fingerprint": step_fingerprints[candidate],
                        "status": "completed",
                        "artifact_ids": [artifact_ids[candidate]],
                        "error": None,
                    }
                    for candidate in operations
                },
            }
        ],
    )
    artifact_shas: dict[str, str] = {}
    for candidate in operations:
        p7_artifact = {
            "schema_version": "workbench.workflow.p7-pack/v1",
            "source": {
                "run_id": run_id,
                "node_ref": "stage:raw",
                "artifact_id": "raw.csv",
                "sha256": source_sha,
                "workflow_id": workflow_id,
                "workflow_step_id": step_ids[candidate],
                "workflow_step_fingerprint": step_fingerprints[candidate],
                "operation_id": candidate,
                "pack_family": "missing_data",
            },
            "result": {
                "operation_id": candidate,
                "status": "completed",
                "evidence_digest": "3" * 64,
            },
        }
        artifact_path = (
            root
            / "runs"
            / run_id
            / "artifacts"
            / "p7_analysis"
            / f"{artifact_ids[candidate]}.json"
        )
        write_json(artifact_path, p7_artifact)
        artifact_shas[candidate] = hashlib.sha256(
            artifact_path.read_bytes()
        ).hexdigest()
    receipt = {
        "schema_version": "workbench.notebook.workflow-result/v1",
        "workflow": {
            "workflow_id": workflow_id,
            "plan_fingerprint": workflow_plan_fingerprint,
            "status": "completed",
            "source": {
                "run_id": run_id,
                "node_ref": "stage:raw",
                "artifact_id": "raw.csv",
            },
            "p7_capability_ids": list(operations),
        },
        "output_artifacts": [
            {
                "artifact_id": artifact_ids[candidate],
                "artifact_type": "p7_analysis",
                "sha256": artifact_shas[candidate],
                "step": candidate,
            }
            for candidate in operations
        ],
    }
    receipt_path = (
        root
        / "runs"
        / run_id
        / "artifacts"
        / "notebook_workflow_results"
        / f"{receipt_id}.json"
    )
    write_json(receipt_path, receipt)
    receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    write_json(
        root / "runs" / run_id / "artifacts_index.json",
        {
            "schema_version": "1.0",
            "artifacts": [
                {
                    "artifact_id": "raw.csv",
                    "path": "raw_snapshot/raw.csv",
                    "artifact_type": "raw_dataset",
                    "step": "ingestion",
                    "sha256": source_sha,
                    "inputs": [],
                },
                *[
                    {
                        "artifact_id": artifact_ids[candidate],
                        "path": (
                            "artifacts/p7_analysis/"
                            f"{artifact_ids[candidate]}.json"
                        ),
                        "artifact_type": "p7_analysis",
                        "step": candidate,
                        "sha256": artifact_shas[candidate],
                        "inputs": ["raw.csv"],
                    }
                    for candidate in operations
                ],
                {
                    "artifact_id": receipt_id,
                    "path": f"artifacts/notebook_workflow_results/{receipt_id}.json",
                    "artifact_type": "notebook_workflow_result",
                    "step": "notebook.workflow.result",
                    "sha256": receipt_sha,
                    "inputs": [artifact_ids[candidate] for candidate in operations],
                },
            ],
        },
    )
    browser_snapshot = root / "qa" / "browser-confirmation.html"
    browser_snapshot.parent.mkdir(parents=True, exist_ok=True)
    browser_snapshot.write_bytes(
        b'<main><button aria-label="Confirm plan">Confirm plan</button></main>\n'
    )
    observation = BrowserConfirmationObservation.create(
        browser_session_id="browser_session_acceptance",
        notebook_id=notebook_id,
        option_id=option_id,
        option_revision=1,
        confirmation_recorded_at=confirmation_at,
        observed_url=(
            "http://127.0.0.1:5189/workbench?project_root=" + str(root)
        ),
        confirmation_control_name="Confirm plan",
        dom_snapshot_sha256=hashlib.sha256(browser_snapshot.read_bytes()).hexdigest(),
    )
    return root, observation, browser_snapshot


def test_manifest_is_write_once_and_freezes_all_live_rows(tmp_path) -> None:
    """A changed manifest requires a new path; updating this guard is deliberate."""

    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.qa.p7_acceptance import (
        ManifestConflictError,
        load_acceptance_manifest,
        write_once_manifest,
    )

    path = tmp_path / "p7-manifest.json"
    manifest = _manifest(tmp_path)
    written = write_once_manifest(path, manifest)
    original = path.read_bytes()

    assert write_once_manifest(path, manifest) == written
    assert path.read_bytes() == original
    loaded = load_acceptance_manifest(path, registry=p7_pack_registry)
    assert loaded == manifest
    assert {row.operation_id for row in loaded.rows} == set(
        p7_pack_registry.operation_ids()
    )
    assert loaded.provider == "deepseek"
    assert loaded.model == "deepseek-v4"
    assert loaded.rate_policy.capacity == 2
    assert loaded.manifest_digest

    changed = _manifest(tmp_path, model="different-model")
    with pytest.raises(ManifestConflictError, match="different content"):
        write_once_manifest(path, changed)
    assert path.read_bytes() == original


def test_interrupted_manifest_publish_is_recoverable_and_never_partial(
    tmp_path,
    monkeypatch,
) -> None:
    """The immutable run authority appears only after all bytes are durable."""

    import workbench.qa.p7_acceptance as acceptance

    manifest = _ready_manifest(tmp_path)
    path = tmp_path / "manifest.json"
    original_write = acceptance.os.write
    calls = 0

    def interrupt_after_partial_write(descriptor, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(descriptor, payload[: max(1, len(payload) // 2)])
        raise InterruptedError("simulated manifest write interruption")

    monkeypatch.setattr(acceptance.os, "write", interrupt_after_partial_write)
    interrupted = False
    try:
        acceptance.write_once_manifest(path, manifest)
    except InterruptedError:
        interrupted = True
    partial_manifest_was_visible = path.exists()

    monkeypatch.setattr(acceptance.os, "write", original_write)
    recovery_error = None
    recovered_digest = None
    try:
        acceptance.write_once_manifest(path, manifest)
        recovered_digest = acceptance.load_acceptance_manifest(
            path,
            verify_registry=False,
        ).manifest_digest
    except Exception as error:  # noqa: BLE001 - the tuple records any unsafe recovery.
        recovery_error = f"{type(error).__name__}: {error}"

    assert (
        interrupted,
        partial_manifest_was_visible,
        recovery_error,
        recovered_digest,
    ) == (True, False, None, manifest.manifest_digest)


def test_manifest_rejects_registry_git_and_file_drift(tmp_path) -> None:
    """Frozen authority must fail closed when declarations or context move."""

    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.qa.p7_acceptance import (
        ManifestDriftError,
        load_acceptance_manifest,
        registry_digest,
        write_once_manifest,
    )

    path = tmp_path / "p7-manifest.json"
    manifest = _manifest(tmp_path)
    write_once_manifest(path, manifest)
    injected = _InjectedRegistry(p7_pack_registry, _fake_operation())
    assert registry_digest(injected) != registry_digest(p7_pack_registry)

    with pytest.raises(ManifestDriftError, match="registry"):
        load_acceptance_manifest(path, registry=injected)
    with pytest.raises(ManifestDriftError, match="git HEAD"):
        load_acceptance_manifest(
            path, registry=p7_pack_registry, expected_git_head="c" * 40
        )
    with pytest.raises(ManifestDriftError, match="dirty digest"):
        load_acceptance_manifest(
            path, registry=p7_pack_registry, expected_dirty_digest="d" * 64
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["provider"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestDriftError, match="content digest"):
        load_acceptance_manifest(path, registry=p7_pack_registry)


def test_attempt_ledger_is_append_only_hash_chained_and_retry_is_new_attempt(
    tmp_path,
) -> None:
    """Retries extend immutable history instead of replacing attempt one."""

    from workbench.qa.p7_acceptance import AttemptLedger

    ledger_path = tmp_path / "attempts.jsonl"
    ledger = AttemptLedger(ledger_path, _ready_manifest(tmp_path))
    first = ledger.start_attempt("missingness.profile", occurred_at=100.0)
    first_bytes = ledger_path.read_bytes()
    running = ledger.record_status(
        "missingness.profile", 1, "running", occurred_at=100.5
    )
    failed = ledger.record_status(
        "missingness.profile",
        1,
        "failed",
        occurred_at=101.0,
        reason_code="provider_error",
        reason_detail="Visible provider failure; no automatic retry.",
    )
    retry = ledger.retry("missingness.profile", occurred_at=103.0)
    events = ledger.events()

    assert ledger_path.read_bytes().startswith(first_bytes)
    assert first.sequence_no == 1
    assert first.attempt_no == 1
    assert first.retry_of is None
    assert running.attempt_no == failed.attempt_no == 1
    assert retry.attempt_no == 2
    assert retry.retry_of == 1
    assert [event.sequence_no for event in events] == [1, 2, 3, 4]
    assert events[0].previous_hash is None
    for previous, current in zip(events, events[1:]):
        assert current.previous_hash == previous.record_hash
        assert current.record_hash != previous.record_hash


def test_attempt_ledger_rejects_tampering_and_manifest_drift(tmp_path) -> None:
    """Changing a prior event or its manifest authority invalidates the ledger."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    path = tmp_path / "attempts.jsonl"
    manifest = _ready_manifest(tmp_path)
    ledger = AttemptLedger(path, manifest)
    ledger.start_attempt("missingness.profile", occurred_at=100.0)

    line = json.loads(path.read_text(encoding="utf-8"))
    line["status"] = "completed"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    with pytest.raises(AttemptLedgerError, match="hash"):
        ledger.events()

    clean_path = tmp_path / "manifest-drift-attempts.jsonl"
    AttemptLedger(clean_path, manifest).start_attempt(
        "missingness.profile", occurred_at=100.0
    )
    changed = _manifest(
        tmp_path,
        model="another-model",
        fixture_profiles={
            "diagnostics.vif": {
                "status": "ready",
                "fixture_id": "design_frame_v1",
                "source": "generated_example",
            },
            "missingness.profile": {
                "status": "ready",
                "fixture_id": "survey_missingness_v1",
                "source": "generated_example",
            },
        },
    )
    with pytest.raises(AttemptLedgerError, match="manifest"):
        AttemptLedger(clean_path, changed).events()


def test_resume_reopens_confirmation_reconciles_running_and_skips_terminal(
    tmp_path,
) -> None:
    """Resume returns the active row without resubmitting it, then skips terminal rows."""

    from workbench.qa.p7_acceptance import AttemptLedger

    ledger = AttemptLedger(tmp_path / "attempts.jsonl", _ready_manifest(tmp_path))
    first_choice = ledger.next_admission(now=100.0)
    assert first_choice.row is not None
    first_id = first_choice.row.operation_id

    ledger.start_attempt(first_id, occurred_at=100.0)
    while_awaiting = ledger.next_admission(now=100.0)
    assert while_awaiting.row is not None
    assert while_awaiting.row.operation_id == first_id
    assert while_awaiting.action == "reopen_confirmation"
    assert while_awaiting.attempt_no == 1
    assert while_awaiting.requires_provider_admission is False

    ledger.record_status(first_id, 1, "running", occurred_at=100.1)
    while_running = ledger.next_admission(now=100.1)
    assert while_running.row is not None
    assert while_running.row.operation_id == first_id
    assert while_running.action == "reconcile_running"
    assert while_running.attempt_no == 1
    assert while_running.requires_provider_admission is False

    authority = ledger.completion_authority(first_id)
    ledger.record_status(
        first_id,
        1,
        "completed",
        occurred_at=100.2,
        evidence=_completion_evidence(first_id, authority=authority),
    )
    after_terminal = ledger.next_admission(now=100.2)
    assert after_terminal.row is not None
    assert after_terminal.row.operation_id != first_id
    assert after_terminal.action == "submit"
    assert after_terminal.attempt_no is None
    assert after_terminal.requires_provider_admission is True
    assert ledger.states()[first_id].status == "completed"


def test_first_start_freezes_operation_mode_and_manifest_derived_scope(
    tmp_path,
) -> None:
    """The first durable start freezes how and what this runner will cover."""

    from workbench.qa.p7_acceptance import AttemptLedger

    manifest = _ready_manifest(tmp_path)
    ledger = AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    ledger.start_attempt("missingness.profile", occurred_at=100.0)

    control = ledger.run_control()
    expected_scope = tuple(
        sorted(
            row.operation_id
            for row in manifest.rows
            if row.fixture_profile.status == "ready"
        )
    )
    assert (control.mode, control.scope_ids) == ("operation", expected_scope)


def test_interrupted_run_control_publish_is_recoverable_and_never_partial(
    tmp_path,
    monkeypatch,
) -> None:
    """A crash-like write interruption exposes either no control or a whole one."""

    import workbench.qa.p7_acceptance as acceptance

    ledger = acceptance.AttemptLedger(
        tmp_path / "attempts.jsonl",
        _ready_manifest(tmp_path),
    )
    original_write = acceptance.os.write
    calls = 0

    def interrupt_after_partial_write(descriptor, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(descriptor, payload[: max(1, len(payload) // 2)])
        raise InterruptedError("simulated control write interruption")

    monkeypatch.setattr(acceptance.os, "write", interrupt_after_partial_write)
    interrupted = False
    try:
        ledger.start_attempt("missingness.profile", occurred_at=100.0)
    except InterruptedError:
        interrupted = True
    partial_control_was_visible = ledger.control_path.exists()

    monkeypatch.setattr(acceptance.os, "write", original_write)
    recovery_error = None
    recovered_status = None
    try:
        recovered_status = ledger.start_attempt(
            "missingness.profile", occurred_at=100.0
        ).status
    except Exception as error:  # noqa: BLE001 - the tuple records any unsafe recovery.
        recovery_error = f"{type(error).__name__}: {error}"

    assert (
        interrupted,
        partial_control_was_visible,
        recovery_error,
        recovered_status,
    ) == (True, False, None, "awaiting_confirmation")


def test_operation_mode_cannot_switch_to_family_batches_after_terminal_state(
    tmp_path,
) -> None:
    """A terminal single item does not authorize changing the frozen run mode."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    manifest = _ready_family_manifest("missing_data", "categorical", capacity=2)
    ledger = AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    operation_id = next(
        row.operation_id
        for row in manifest.rows
        if row.pack_family == "missing_data"
    )
    ledger.start_attempt(operation_id, occurred_at=100.0)
    ledger.record_status(
        operation_id,
        1,
        "failed",
        occurred_at=100.1,
        reason_code="visible_failure",
    )

    with pytest.raises(AttemptLedgerError, match="frozen in operation mode"):
        ledger.start_batch("categorical", occurred_at=100.2)


def test_family_batch_mode_cannot_switch_to_single_items_after_terminal_state(
    tmp_path,
) -> None:
    """A terminal family submission does not authorize splitting later work."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    manifest = _ready_family_manifest("missing_data", "categorical", capacity=2)
    ledger = AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    ledger.start_batch("missing_data", occurred_at=100.0)
    ledger.record_batch_status(
        "missing_data",
        "failed",
        occurred_at=100.1,
        reason_code="visible_failure",
    )
    operation_id = next(
        row.operation_id
        for row in manifest.rows
        if row.pack_family == "categorical"
    )

    with pytest.raises(AttemptLedgerError, match="frozen in family_batch mode"):
        ledger.start_attempt(operation_id, occurred_at=100.2)


def test_resume_api_cannot_switch_away_from_frozen_operation_mode(tmp_path) -> None:
    """Resume must not advertise family work for an operation-mode ledger."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    manifest = _ready_family_manifest("missing_data", "categorical", capacity=2)
    ledger = AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    operation_id = next(
        row.operation_id
        for row in manifest.rows
        if row.pack_family == "missing_data"
    )
    ledger.start_attempt(operation_id, occurred_at=100.0)
    ledger.record_status(
        operation_id,
        1,
        "failed",
        occurred_at=100.1,
        reason_code="visible_failure",
    )

    with pytest.raises(AttemptLedgerError, match="frozen in operation mode"):
        ledger.next_batch_admission(now=100.2)


def test_resume_api_cannot_switch_away_from_frozen_family_batch_mode(
    tmp_path,
) -> None:
    """Resume must not advertise single-item work for a family-mode ledger."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    manifest = _ready_family_manifest("missing_data", "categorical", capacity=2)
    ledger = AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    ledger.start_batch("missing_data", occurred_at=100.0)
    ledger.record_batch_status(
        "missing_data",
        "failed",
        occurred_at=100.1,
        reason_code="visible_failure",
    )

    with pytest.raises(AttemptLedgerError, match="frozen in family_batch mode"):
        ledger.next_admission(now=100.2)


def test_persisted_progress_cannot_outlive_or_bypass_its_run_control(
    tmp_path,
) -> None:
    """Missing mode authority is a visible recovery error, never a fresh run."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    ledger = AttemptLedger(tmp_path / "attempts.jsonl", _ready_manifest(tmp_path))
    ledger.start_attempt("missingness.profile", occurred_at=100.0)
    ledger.control_path.unlink()

    with pytest.raises(AttemptLedgerError, match="run control is missing"):
        ledger.next_admission(now=100.1)


def test_run_control_mode_must_match_the_first_durable_record_shape(tmp_path) -> None:
    """A self-consistent replacement control cannot reinterpret prior progress."""

    import workbench.qa.p7_acceptance as acceptance

    manifest = _ready_family_manifest("missing_data", "categorical", capacity=2)
    ledger = acceptance.AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    operation_id = next(
        row.operation_id
        for row in manifest.rows
        if row.pack_family == "missing_data"
    )
    ledger.start_attempt(operation_id, occurred_at=100.0)

    replacement = json.loads(ledger.control_path.read_text(encoding="utf-8"))
    replacement["mode"] = "family_batch"
    replacement["scope_ids"] = sorted(
        batch.pack_family
        for batch in acceptance.build_acceptance_batches(manifest.rows)
        if batch.status == "ready"
    )
    unsigned = {
        key: value
        for key, value in replacement.items()
        if key != "control_digest"
    }
    replacement["control_digest"] = acceptance._sha256(unsigned)
    ledger.control_path.write_text(
        json.dumps(replacement, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(acceptance.AttemptLedgerError, match="first durable record"):
        ledger.events()


def test_family_batch_is_one_admission_with_independent_operation_records(
    tmp_path,
) -> None:
    """One visible family submission starts every child atomically but costs one token."""

    from workbench.qa.p7_acceptance import AttemptLedger, RateLimitError

    ledger = AttemptLedger(
        tmp_path / "attempts.jsonl",
        _ready_family_manifest("missing_data", "categorical", capacity=1),
    )
    started = ledger.start_batch("missing_data", occurred_at=100.0)
    expected = {
        row.operation_id
        for row in ledger.manifest.rows
        if row.pack_family == "missing_data"
    }

    assert {event.operation_id for event in started} == expected
    assert len({event.submission_id for event in started}) == 1
    assert all(event.attempt_no == 1 for event in started)
    assert all(event.status == "awaiting_confirmation" for event in started)
    resumed = ledger.next_batch_admission(now=100.1)
    assert resumed.batch is not None
    assert resumed.batch.pack_family == "missing_data"
    assert resumed.action == "reopen_confirmation"
    assert resumed.requires_provider_admission is False

    running = ledger.record_batch_status(
        "missing_data", "running", occurred_at=100.2
    )
    assert {event.operation_id for event in running} == expected
    assert ledger.next_batch_admission(now=100.3).action == "reconcile_running"

    authority = ledger.completion_authority(next(iter(expected)))
    evidence = {
        operation_id: _completion_evidence(operation_id, authority=authority)
        for operation_id in expected
    }
    completed = ledger.record_batch_status(
        "missing_data",
        "completed",
        occurred_at=100.4,
        evidence_by_operation=evidence,
    )
    assert {event.operation_id for event in completed} == expected
    assert all(
        ledger.states()[operation_id].status == "completed"
        for operation_id in expected
    )

    with pytest.raises(RateLimitError):
        ledger.start_batch("categorical", occurred_at=100.4)


def test_single_resume_refuses_to_split_an_active_family_submission(tmp_path) -> None:
    """The single-item API cannot return one child from a shared browser batch."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    ledger = AttemptLedger(
        tmp_path / "attempts.jsonl",
        _ready_family_manifest("missing_data"),
    )
    ledger.start_batch("missing_data", occurred_at=100.0)

    with pytest.raises(AttemptLedgerError, match="family batch"):
        ledger.next_admission(now=100.1)


def test_family_batch_appends_one_recoverable_transaction_record(tmp_path) -> None:
    """A crash can leave a rejected partial line, never a valid partial family batch."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    ledger = AttemptLedger(
        tmp_path / "attempts.jsonl",
        _ready_family_manifest("missing_data"),
    )
    started = ledger.start_batch("missing_data", occurred_at=100.0)
    lines = ledger.path.read_bytes().splitlines()
    assert len(lines) == 1
    transaction = json.loads(lines[0])
    assert transaction["record_type"] == "batch_transaction"
    assert len(transaction["events"]) == len(started)
    assert transaction["transaction_hash"]

    original = ledger.path.read_bytes()
    ledger.path.write_bytes(original[:-1])
    with pytest.raises(AttemptLedgerError, match="truncated final record"):
        ledger.events()


def test_interrupted_completion_append_preserves_running_progress_without_pass(
    tmp_path,
    monkeypatch,
) -> None:
    """A partial completion write cannot hide prior progress or create a pass."""

    import workbench.qa.p7_acceptance as acceptance

    manifest = _ready_manifest(tmp_path)
    ledger = acceptance.AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    operation_id = "missingness.profile"
    ledger.start_attempt(operation_id, occurred_at=100.0)
    ledger.record_status(operation_id, 1, "running", occurred_at=100.1)
    authority = ledger.completion_authority(operation_id)
    evidence = _completion_evidence(operation_id, authority=authority)
    durable_prefix = ledger.path.read_bytes()
    original_write = acceptance.os.write
    calls = 0

    def interrupt_after_partial_write(descriptor, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(descriptor, payload[: max(1, len(payload) // 2)])
        raise InterruptedError("simulated completion append interruption")

    monkeypatch.setattr(acceptance.os, "write", interrupt_after_partial_write)
    interrupted = False
    try:
        ledger.record_status(
            operation_id,
            1,
            "completed",
            occurred_at=100.2,
            evidence=evidence,
        )
    except InterruptedError:
        interrupted = True
    monkeypatch.setattr(acceptance.os, "write", original_write)

    recovery_error = None
    recovered_status = None
    try:
        recovered = acceptance.AttemptLedger(ledger.path, manifest)
        recovered_status = recovered.states()[operation_id].status
    except Exception as error:  # noqa: BLE001 - the tuple records unsafe recovery.
        recovery_error = f"{type(error).__name__}: {error}"

    assert (
        interrupted,
        ledger.path.read_bytes() == durable_prefix,
        recovery_error,
        recovered_status,
    ) == (True, True, None, "running")


def test_family_batch_completion_requires_one_shared_visible_parent(tmp_path) -> None:
    """A batch cannot be assembled from unrelated successful Notebook proposals."""

    from workbench.qa.p7_acceptance import AttemptLedger, CompletionEvidenceError

    ledger = AttemptLedger(
        tmp_path / "attempts.jsonl",
        _ready_family_manifest("missing_data"),
    )
    started = ledger.start_batch("missing_data", occurred_at=100.0)
    operation_ids = [event.operation_id for event in started]
    authority = ledger.completion_authority(operation_ids[0])
    evidence = {
        operation_id: _completion_evidence(operation_id, authority=authority)
        for operation_id in operation_ids
    }
    divergent_id = operation_ids[-1]
    divergent = evidence[divergent_id]
    evidence[divergent_id] = replace(
        divergent,
        parent_record_id="different_parent_record",
        child_parent_record_id="different_parent_record",
        confirmation_parent_record_id="different_parent_record",
        nested_result_parent_record_id="different_parent_record",
    )

    with pytest.raises(CompletionEvidenceError, match="same visible parent"):
        ledger.record_batch_status(
            "missing_data",
            "completed",
            occurred_at=100.1,
            evidence_by_operation=evidence,
        )

    assert all(
        ledger.states()[operation_id].status == "awaiting_confirmation"
        for operation_id in operation_ids
    )


def test_family_batch_retry_preserves_first_attempt_and_retries_as_one_submission(
    tmp_path,
) -> None:
    """A failed first family attempt remains immutable when the family is retried."""

    from workbench.qa.p7_acceptance import AttemptLedger

    ledger = AttemptLedger(
        tmp_path / "attempts.jsonl",
        _ready_family_manifest("missing_data"),
    )
    first = ledger.start_batch("missing_data", occurred_at=100.0)
    first_bytes = ledger.path.read_bytes()
    failed = ledger.record_batch_status(
        "missing_data",
        "failed",
        occurred_at=100.1,
        reason_code="provider_error",
        reason_detail="Visible first-attempt failure.",
    )
    retried = ledger.retry_batch("missing_data", occurred_at=103.0)

    assert ledger.path.read_bytes().startswith(first_bytes)
    assert {event.operation_id for event in retried} == {
        event.operation_id for event in first
    }
    assert all(event.attempt_no == 2 and event.retry_of == 1 for event in retried)
    assert len({event.submission_id for event in failed}) == 1
    assert len({event.submission_id for event in retried}) == 1
    assert retried[0].submission_id != first[0].submission_id


def test_operation_mode_cannot_retry_a_family_as_one_batch(tmp_path) -> None:
    """Retry cannot reinterpret independent attempts as a family submission."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    manifest = _ready_family_manifest("missing_data", capacity=10)
    ledger = AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    operation_ids = tuple(
        row.operation_id
        for row in manifest.rows
        if row.pack_family == "missing_data"
    )
    for offset, operation_id in enumerate(operation_ids):
        started_at = 100.0 + offset
        ledger.start_attempt(operation_id, occurred_at=started_at)
        ledger.record_status(
            operation_id,
            1,
            "failed",
            occurred_at=started_at + 0.1,
            reason_code="visible_failure",
        )

    with pytest.raises(AttemptLedgerError, match="frozen in operation mode"):
        ledger.retry_batch("missing_data", occurred_at=110.0)


def test_family_batch_mode_cannot_retry_one_child_as_a_single_item(tmp_path) -> None:
    """Retry cannot split one failed family submission into independent work."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    manifest = _ready_family_manifest("missing_data", capacity=2)
    ledger = AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    failed = ledger.start_batch("missing_data", occurred_at=100.0)
    ledger.record_batch_status(
        "missing_data",
        "failed",
        occurred_at=100.1,
        reason_code="visible_failure",
    )

    with pytest.raises(AttemptLedgerError, match="frozen in family_batch mode"):
        ledger.retry(failed[0].operation_id, occurred_at=101.0)


def test_completion_evidence_cannot_replay_across_submissions_or_retries(
    tmp_path,
) -> None:
    """Each first attempt and retry owns a fresh causal evidence authority."""

    from workbench.qa.p7_acceptance import AttemptLedger, CompletionEvidenceError

    manifest = _ready_manifest(tmp_path)
    first_ledger = AttemptLedger(tmp_path / "first.jsonl", manifest)
    first_start = first_ledger.start_attempt(
        "missingness.profile", occurred_at=100.0
    )
    first_authority = first_ledger.completion_authority("missingness.profile")
    evidence = _completion_evidence(
        "missingness.profile",
        authority=first_authority,
    )
    first_ledger.record_status(
        "missingness.profile",
        first_start.attempt_no,
        "failed",
        occurred_at=101.0,
        reason_code="first_attempt_failed",
    )
    retry = first_ledger.retry("missingness.profile", occurred_at=103.0)

    with pytest.raises(CompletionEvidenceError, match="submission authority"):
        first_ledger.record_status(
            "missingness.profile",
            retry.attempt_no,
            "completed",
            occurred_at=104.0,
            evidence=evidence,
        )

    second_ledger = AttemptLedger(tmp_path / "second.jsonl", manifest)
    second = second_ledger.start_attempt(
        "missingness.profile", occurred_at=200.0
    )
    assert second.submission_id != first_start.submission_id
    with pytest.raises(CompletionEvidenceError, match="submission authority"):
        second_ledger.record_status(
            "missingness.profile",
            second.attempt_no,
            "completed",
            occurred_at=201.0,
            evidence=evidence,
        )


def test_completion_evidence_cannot_claim_records_from_the_future(tmp_path) -> None:
    """A completion event cannot authenticate browser records created after itself."""

    from workbench.qa.p7_acceptance import AttemptLedger, CompletionEvidenceError

    ledger = AttemptLedger(tmp_path / "attempts.jsonl", _ready_manifest(tmp_path))
    ledger.start_attempt("missingness.profile", occurred_at=100.0)
    authority = ledger.completion_authority("missingness.profile")
    evidence = replace(
        _completion_evidence("missingness.profile", authority=authority),
        option_revision_recorded_at="1970-01-01T00:01:40.100000+00:00",
        confirmation_recorded_at="1970-01-01T00:03:20+00:00",
    )

    with pytest.raises(CompletionEvidenceError, match="later than completion event"):
        ledger.record_status(
            "missingness.profile",
            1,
            "completed",
            occurred_at=150.0,
            evidence=evidence,
        )


def test_blocked_fixture_is_counted_and_cannot_start(tmp_path) -> None:
    """A typed blocker stays in the denominator and cannot become a silent skip."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    manifest = _manifest(
        tmp_path,
        fixture_profiles={
            "missingness.profile": {
                "status": "blocked",
                "fixture_id": "optional_mice_fixture",
                "source": "generated_example",
                "blocker_code": "optional_dependency",
                "blocker_detail": "The optional package is unavailable.",
            }
        },
    )
    ledger = AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    state = ledger.states()["missingness.profile"]
    assert state.status == "blocked"
    assert state.reason_code == "optional_dependency"
    with pytest.raises(AttemptLedgerError, match="fixture is blocked"):
        ledger.start_attempt("missingness.profile", occurred_at=100.0)
    assert ledger.events() == ()


def test_new_attempt_cannot_orphan_an_active_browser_attempt(tmp_path) -> None:
    """Only the resumed active row may advance until it reaches a terminal state."""

    from workbench.qa.p7_acceptance import AttemptLedger, AttemptLedgerError

    ledger = AttemptLedger(tmp_path / "attempts.jsonl", _ready_manifest(tmp_path))
    ledger.start_attempt("diagnostics.vif", occurred_at=100.0)

    with pytest.raises(AttemptLedgerError, match="active browser attempt"):
        ledger.start_attempt("missingness.profile", occurred_at=100.1)

    assert [event.operation_id for event in ledger.events()] == ["diagnostics.vif"]


def test_token_bucket_reports_next_admission_without_sleep_or_retry() -> None:
    """Rate control returns a timestamp and performs no wait or retry itself."""

    from workbench.qa.p7_acceptance import RatePolicy, token_bucket_admission

    policy = RatePolicy(capacity=2, refill_per_second=0.5)
    decision = token_bucket_admission(
        policy,
        admitted_at=(0.0, 0.0),
        now=1.0,
    )
    assert decision.admitted is False
    assert decision.next_admission_at == pytest.approx(2.0)
    assert decision.tokens_after == pytest.approx(0.5)

    later = token_bucket_admission(policy, admitted_at=(0.0, 0.0), now=2.0)
    assert later.admitted is True
    assert later.next_admission_at == pytest.approx(2.0)
    assert later.tokens_after == pytest.approx(0.0)


def test_next_packets_wait_when_the_frozen_rate_policy_denies_admission(
    tmp_path,
) -> None:
    """A visible packet is not permission to call the provider before admission."""

    from workbench.qa.p7_acceptance import AttemptLedger, RatePolicy

    single = AttemptLedger(
        tmp_path / "single.jsonl",
        _manifest(
            tmp_path,
            rate_policy=RatePolicy(capacity=1, refill_per_second=0.5),
            fixture_profiles={
                "diagnostics.vif": {
                    "status": "ready",
                    "fixture_id": "shared_browser_v1",
                    "source": "generated_example",
                },
                "missingness.profile": {
                    "status": "ready",
                    "fixture_id": "shared_browser_v1",
                    "source": "generated_example",
                },
            },
        ),
    )
    single.start_attempt("diagnostics.vif", occurred_at=100.0)
    single.record_status(
        "diagnostics.vif",
        1,
        "failed",
        occurred_at=100.1,
        reason_code="visible_failure",
    )
    single_wait = single.next_admission(now=100.1)
    assert single_wait.row is not None
    assert single_wait.row.operation_id == "missingness.profile"
    assert single_wait.rate.admitted is False
    assert single_wait.action == "wait"
    assert single_wait.requires_provider_admission is False

    batch = AttemptLedger(
        tmp_path / "batch.jsonl",
        _ready_family_manifest("missing_data", "model_diagnostics", capacity=1),
    )
    batch.start_batch("model_diagnostics", occurred_at=200.0)
    batch.record_batch_status(
        "model_diagnostics",
        "failed",
        occurred_at=200.1,
        reason_code="visible_failure",
    )
    batch_wait = batch.next_batch_admission(now=200.1)
    assert batch_wait.batch is not None
    assert batch_wait.batch.pack_family == "missing_data"
    assert batch_wait.rate.admitted is False
    assert batch_wait.action == "wait"
    assert batch_wait.requires_provider_admission is False


def test_cli_rejects_caller_supplied_rate_clock_overrides(tmp_path) -> None:
    """The production runner owns wall-clock admission; callers cannot time-travel."""

    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            str(root / ".venv/bin/python"),
            str(root / "scripts/p7_acceptance_runner.py"),
            "next",
            "--manifest",
            str(tmp_path / "missing.json"),
            "--attempts",
            str(tmp_path / "attempts.jsonl"),
            "--now",
            "100",
        ],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 2
    assert "unrecognized arguments: --now 100" in completed.stderr


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_rate_policy_rejects_non_finite_values(value: float) -> None:
    """Non-finite rate state is rejected before it can enter a manifest."""

    from workbench.qa.p7_acceptance import RatePolicy

    with pytest.raises(ValueError, match="finite"):
        RatePolicy(capacity=1, refill_per_second=value)
    with pytest.raises(ValueError, match="finite"):
        RatePolicy(capacity=1, refill_per_second=1.0, cost_per_attempt=value)


def test_workspace_dirty_digest_tracks_bytes_not_only_status_paths(tmp_path) -> None:
    """Changing bytes under the same porcelain status must change manifest authority."""

    from workbench.qa.p7_acceptance import workspace_dirty_digest

    repository = tmp_path / "repository"
    repository.mkdir()

    def git(*arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    git("config", "user.email", "acceptance@example.invalid")
    git("config", "user.name", "Acceptance Test")
    tracked = repository / "tracked.txt"
    tracked.write_text("baseline\n", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-qm", "baseline")

    clean = workspace_dirty_digest(repository)
    tracked.write_text("first mutation\n", encoding="utf-8")
    first_tracked = workspace_dirty_digest(repository)
    tracked.write_text("second mutation\n", encoding="utf-8")
    second_tracked = workspace_dirty_digest(repository)

    assert clean != first_tracked
    assert first_tracked != second_tracked

    untracked = repository / "untracked.txt"
    untracked.write_text("first untracked bytes\n", encoding="utf-8")
    first_untracked = workspace_dirty_digest(repository)
    untracked.write_text("second untracked bytes\n", encoding="utf-8")
    second_untracked = workspace_dirty_digest(repository)

    assert first_untracked != second_untracked


def test_artifact_only_evidence_cannot_be_recorded_as_completed(tmp_path) -> None:
    """An artifact or Notebook record cannot impersonate the visible Agent chain."""

    from dataclasses import replace

    from workbench.qa.p7_acceptance import (
        AttemptLedger,
        CompletionEvidenceError,
        validate_completion_evidence,
    )

    manifest = _ready_manifest(tmp_path)
    row = next(
        row for row in manifest.rows if row.operation_id == "missingness.profile"
    )
    with pytest.raises(CompletionEvidenceError, match="browser-visible Agent"):
        validate_completion_evidence(
            row,
            replace(
                _completion_evidence(row.operation_id),
                evidence_kind="artifact_only",
            ),
        )
    with pytest.raises(CompletionEvidenceError, match="browser-visible Agent"):
        validate_completion_evidence(
            row,
            {
                "evidence_kind": "artifact_only",
                "artifact_id": "artifact_missingness",
                "artifact_sha256": "e" * 64,
            },
        )

    ledger = AttemptLedger(tmp_path / "attempts.jsonl", manifest)
    ledger.start_attempt("missingness.profile", occurred_at=100.0)
    with pytest.raises(CompletionEvidenceError, match="browser-visible Agent"):
        ledger.record_status(
            "missingness.profile",
            1,
            "completed",
            occurred_at=100.1,
            evidence={
                "evidence_kind": "notebook",
                "artifact_id": "artifact_missingness",
                "artifact_sha256": "e" * 64,
            },
        )
    assert ledger.states()["missingness.profile"].status == "awaiting_confirmation"


def test_completed_evidence_requires_exact_parent_child_confirmation_and_provenance(
    tmp_path,
) -> None:
    """Every completion identity is part of the acceptance contract."""

    from dataclasses import replace

    from workbench.qa.p7_acceptance import (
        CompletionEvidenceError,
        validate_completion_evidence,
    )

    manifest = _ready_manifest(tmp_path)
    row = next(
        row for row in manifest.rows if row.operation_id == "missingness.profile"
    )
    evidence = _completion_evidence(row.operation_id)
    assert validate_completion_evidence(row, evidence) == evidence

    for mutation, match in (
        (replace(evidence, parent_operation_id="direct.adapter"), "parent"),
        (replace(evidence, child_operation_id="diagnostics.vif"), "child"),
        (replace(evidence, confirmation_surface="api"), "confirmation"),
        (replace(evidence, child_record_durable=False), "durable"),
        (replace(evidence, nested_result_status="failed"), "nested result"),
        (replace(evidence, artifact_sha256="not-a-sha"), "artifact"),
    ):
        with pytest.raises(CompletionEvidenceError, match=match):
            validate_completion_evidence(row, mutation)

    jointly_empty_ids = replace(
        evidence,
        parent_record_id=None,
        child_record_id=None,
        child_parent_record_id=None,
        confirmation_id=None,
        confirmation_parent_record_id=None,
        nested_result_parent_record_id=None,
        nested_result_child_record_id=None,
        artifact_producer_record_id=None,
    )
    with pytest.raises(CompletionEvidenceError, match="identity"):
        validate_completion_evidence(row, jointly_empty_ids)


def test_witness_attested_completion_requires_provider_verification_and_is_labeled(
    tmp_path,
) -> None:
    """A signed provider envelope needs an independently collected result chain."""

    from workbench.qa.p7_acceptance import AttemptLedger, CompletionEvidenceError
    from workbench.qa.witness import (
        BrowserWitnessAttestation,
        WitnessChallenge,
    )

    class TestVerifier:
        human_identity_verified = True

        def verify(self, *, key_id: str, payload: bytes, signature: str) -> bool:
            expected = hashlib.sha256(
                b"test-only-secret:"
                + key_id.encode("utf-8")
                + b":"
                + payload
            ).hexdigest()
            return signature == expected

    ledger = AttemptLedger(
        tmp_path / "attempts.jsonl",
        _ready_manifest(tmp_path),
        witness_verifier=TestVerifier(),
    )
    ledger.start_attempt("missingness.profile", occurred_at=100.0)
    authority = ledger.completion_authority("missingness.profile")
    challenge = WitnessChallenge.create(
        manifest_digest=authority.manifest_digest,
        submission_id=authority.submission_id,
        attempt_no=authority.attempt_no,
        operation_ids_digest=authority.operation_ids_digest,
        notebook_id="nb_acceptance",
        option_id="opt_acceptance",
        option_revision=1,
        attempt_started_at=authority.attempt_started_at,
        issued_at=authority.attempt_started_at,
        expires_at=authority.attempt_started_at + 86400.0,
    )
    placeholder = BrowserWitnessAttestation.create(
        challenge=challenge,
        browser_session_id="browser_session_acceptance",
        confirmation_recorded_at="1970-01-01T00:01:40.200000+00:00",
        observed_url="http://127.0.0.1:5189/notebook?project_root=%2Ftmp%2Fproject",
        confirmation_control_name="Confirm workflow",
        dom_snapshot_sha256="d" * 64,
        durable_chain_sha256="e" * 64,
        key_id="test-witness-key",
        signature="placeholder",
    )
    signature = hashlib.sha256(
        b"test-only-secret:test-witness-key:" + placeholder.signing_payload()
    ).hexdigest()
    attestation = BrowserWitnessAttestation.create(
        challenge=challenge,
        browser_session_id=placeholder.browser_session_id,
        confirmation_recorded_at=placeholder.confirmation_recorded_at,
        observed_url=placeholder.observed_url,
        confirmation_control_name=placeholder.confirmation_control_name,
        dom_snapshot_sha256=placeholder.dom_snapshot_sha256,
        durable_chain_sha256=placeholder.durable_chain_sha256,
        key_id=placeholder.key_id,
        signature=signature,
    )
    evidence = replace(
        _completion_evidence("missingness.profile", authority=authority),
        evidence_kind="browser_witness_attested",
        confirmation_id=attestation.attestation_digest,
        witness_attestation=attestation.to_dict(),
    )

    with pytest.raises(
        CompletionEvidenceError,
        match="independently collected durable result chain",
    ):
        ledger.record_status(
            "missingness.profile",
            1,
            "completed",
            occurred_at=101.0,
            evidence=evidence,
        )

    evidence = replace(
        evidence,
        durable_chain_sha256=attestation.durable_chain_sha256,
    )
    ledger.record_status(
        "missingness.profile",
        1,
        "completed",
        occurred_at=101.0,
        evidence=evidence,
    )
    state = ledger.states()["missingness.profile"]
    assert ledger.events()[-1].evidence.witness_trust_level == "human_identity_verified"
    assert state.trust_level == "human_identity_verified"
    assert state.verification_status == "VERIFIED"


def test_replayed_witness_trust_cannot_be_promoted_by_editing_the_ledger(
    tmp_path,
) -> None:
    """A local ledger rewrite cannot upgrade a provider trust decision."""

    from workbench.qa.p7_acceptance import (
        AttemptLedger,
        AttemptLedgerError,
        _canonical_json,
        _sha256,
    )
    from workbench.qa.witness import BrowserWitnessAttestation, WitnessChallenge

    class TestVerifier:
        human_identity_verified = False

        def verify(self, *, key_id: str, payload: bytes, signature: str) -> bool:
            expected = hashlib.sha256(
                b"test-only-secret:"
                + key_id.encode("utf-8")
                + b":"
                + payload
            ).hexdigest()
            return signature == expected

    ledger = AttemptLedger(
        tmp_path / "attempts.jsonl",
        _ready_manifest(tmp_path),
        witness_verifier=TestVerifier(),
    )
    ledger.start_attempt("missingness.profile", occurred_at=100.0)
    authority = ledger.completion_authority("missingness.profile")
    challenge = WitnessChallenge.create(
        manifest_digest=authority.manifest_digest,
        submission_id=authority.submission_id,
        attempt_no=authority.attempt_no,
        operation_ids_digest=authority.operation_ids_digest,
        notebook_id="nb_acceptance",
        option_id="opt_acceptance",
        option_revision=1,
        attempt_started_at=authority.attempt_started_at,
        issued_at=authority.attempt_started_at,
        expires_at=authority.attempt_started_at + 86400.0,
    )
    placeholder = BrowserWitnessAttestation.create(
        challenge=challenge,
        browser_session_id="browser_session_acceptance",
        confirmation_recorded_at="1970-01-01T00:01:40.200000+00:00",
        observed_url="http://127.0.0.1:5189/notebook?project_root=%2Ftmp%2Fproject",
        confirmation_control_name="Confirm workflow",
        dom_snapshot_sha256="d" * 64,
        durable_chain_sha256="e" * 64,
        key_id="test-witness-key",
        signature="placeholder",
    )
    signature = hashlib.sha256(
        b"test-only-secret:test-witness-key:" + placeholder.signing_payload()
    ).hexdigest()
    attestation = BrowserWitnessAttestation.create(
        challenge=challenge,
        browser_session_id=placeholder.browser_session_id,
        confirmation_recorded_at=placeholder.confirmation_recorded_at,
        observed_url=placeholder.observed_url,
        confirmation_control_name=placeholder.confirmation_control_name,
        dom_snapshot_sha256=placeholder.dom_snapshot_sha256,
        durable_chain_sha256=placeholder.durable_chain_sha256,
        key_id=placeholder.key_id,
        signature=signature,
    )
    evidence = replace(
        _completion_evidence("missingness.profile", authority=authority),
        evidence_kind="browser_witness_attested",
        confirmation_id=attestation.attestation_digest,
        durable_chain_sha256=attestation.durable_chain_sha256,
        witness_attestation=attestation.to_dict(),
    )
    ledger.record_status(
        "missingness.profile",
        1,
        "completed",
        occurred_at=101.0,
        evidence=evidence,
    )

    events = ledger.events()
    persisted = replace(
        events[-1],
        evidence=replace(
            events[-1].evidence,
            witness_trust_level="human_identity_verified",
        ),
        record_hash="pending",
    )
    persisted = replace(persisted, record_hash=_sha256(persisted._unsigned_dict()))
    ledger.path.write_bytes(
        _canonical_json(events[0].to_dict()) + _canonical_json(persisted.to_dict())
    )

    reloaded = AttemptLedger(
        ledger.path,
        ledger.manifest,
        witness_verifier=TestVerifier(),
    )
    with pytest.raises(AttemptLedgerError, match="trust level"):
        reloaded.states()


def test_witness_challenge_is_derived_from_the_active_submission(tmp_path) -> None:
    """The external witness receives a challenge bound to one active option."""

    from workbench.qa.p7_acceptance import AttemptLedger

    ledger = AttemptLedger(tmp_path / "attempts.jsonl", _ready_manifest(tmp_path))
    ledger.start_attempt("missingness.profile", occurred_at=100.0)

    challenge = ledger.witness_challenge(
        "missingness.profile",
        notebook_id="nb_acceptance",
        option_id="opt_acceptance",
        option_revision=1,
    )

    assert challenge.manifest_digest == ledger.manifest.manifest_digest
    assert challenge.option_id == "opt_acceptance"
    assert challenge.submission_id == ledger.completion_authority(
        "missingness.profile"
    ).submission_id


def test_notebook_evidence_collector_verifies_the_durable_browser_chain(
    tmp_path,
) -> None:
    """Completion evidence is collected from real journals and artifact bytes."""

    from workbench.qa.notebook_acceptance_evidence import (
        collect_notebook_completion_evidence,
    )

    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    authority = _completion_authority_for_fixture(
        project_root, ("missingness.profile",)
    )
    evidence = collect_notebook_completion_evidence(
        project_root=project_root,
        operation_id="missingness.profile",
        notebook_id="nb_acceptance",
        option_id="opt_acceptance",
        option_revision=1,
        observation=observation,
        browser_snapshot=browser_snapshot,
        authority=authority,
    )

    assert evidence.evidence_kind == "browser_visible_agent"
    assert evidence.agent_session_id == "trace_acceptance"
    assert evidence.parent_operation_id == "operation.multi_step"
    assert evidence.child_operation_id == "missingness.profile"
    assert evidence.confirmation_surface == "browser"
    assert evidence.confirmation_actor == "user"
    assert evidence.parent_record_durable is True
    assert evidence.child_record_durable is True
    assert evidence.nested_result_status == "completed"
    assert evidence.artifact_id == "workflow_p7_acceptance"
    assert len(evidence.artifact_sha256) == 64


@pytest.mark.parametrize(
    ("relative_path", "mutation", "message"),
    [
        (
            "notebooks/nb_acceptance/options/opt_acceptance.jsonl",
            lambda text: text.replace(
                '"operation_id":"operation.multi_step"',
                '"operation_id":"direct.adapter"',
                1,
            ),
            "parent operation",
        ),
        (
            "notebooks/nb_acceptance/options/opt_acceptance.jsonl",
            lambda text: text.replace(
                '"actor":"user","from_status":"materialized","option_id":"opt_acceptance","option_revision":1,"reason":"workflow_confirmed"',
                '"actor":"system","from_status":"materialized","option_id":"opt_acceptance","option_revision":1,"reason":"workflow_confirmed"',
                1,
            ),
            "browser confirmation",
        ),
        (
            "workbench/workflows/workflow_acceptance.jsonl",
            lambda text: text.replace('"status":"completed"', '"status":"running"', 1),
            "workflow terminal",
        ),
        (
            "runs/notebook_source_acceptance/artifacts/p7_analysis/workflow_p7_acceptance.json",
            lambda text: text.replace(
                '"operation_id":"missingness.profile"',
                '"operation_id":"diagnostics.vif"',
                1,
            ),
            "artifact hash",
        ),
    ],
)
def test_notebook_evidence_collector_fails_closed_on_durable_chain_drift(
    tmp_path,
    relative_path: str,
    mutation,
    message: str,
) -> None:
    """A broken parent, confirmation, child terminal, or artifact fails closed."""

    from workbench.qa.notebook_acceptance_evidence import (
        NotebookAcceptanceEvidenceError,
        collect_notebook_completion_evidence,
    )

    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    authority = _completion_authority_for_fixture(
        project_root, ("missingness.profile",)
    )
    target = project_root / relative_path
    original = target.read_text(encoding="utf-8")
    changed = mutation(original)
    assert changed != original
    target.write_text(changed, encoding="utf-8")

    with pytest.raises(NotebookAcceptanceEvidenceError, match=message):
        collect_notebook_completion_evidence(
            project_root=project_root,
            operation_id="missingness.profile",
            notebook_id="nb_acceptance",
            option_id="opt_acceptance",
            option_revision=1,
            observation=observation,
            browser_snapshot=browser_snapshot,
            authority=authority,
        )


def test_notebook_evidence_collector_rejects_a_chain_from_an_older_submission(
    tmp_path,
) -> None:
    """Durable success from attempt one cannot satisfy a later retry authority."""

    from datetime import datetime, timezone

    from workbench.qa.notebook_acceptance_evidence import (
        NotebookAcceptanceEvidenceError,
        collect_notebook_completion_evidence,
    )

    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    later_attempt = datetime(2026, 8, 9, 12, 0, 5, tzinfo=timezone.utc).timestamp()
    authority = _completion_authority_for_fixture(
        project_root,
        ("missingness.profile",),
        attempt_started_at=later_attempt,
    )

    with pytest.raises(
        NotebookAcceptanceEvidenceError,
        match="option revision predates the active acceptance submission",
    ):
        collect_notebook_completion_evidence(
            project_root=project_root,
            operation_id="missingness.profile",
            notebook_id="nb_acceptance",
            option_id="opt_acceptance",
            option_revision=1,
            observation=observation,
            browser_snapshot=browser_snapshot,
            authority=authority,
        )


@pytest.mark.parametrize(
    ("relative_path", "mutation", "message"),
    [
        (
            "notebooks/nb_acceptance/options/opt_acceptance.jsonl",
            lambda text: text.replace(
                '"steps":[{"operation_id":"missingness.profile"',
                '"steps":[{"operation_id":"diagnostics.vif","spec":{"column_bindings":{},"options":{}},"step_id":"extra_step"},{"operation_id":"missingness.profile"',
                1,
            ),
            "operations do not exactly match",
        ),
        (
            "runs/notebook_source_acceptance/artifacts/notebook_workflow_results/notebook_workflow_result_acceptance.json",
            lambda text: text.replace(
                '"p7_capability_ids":["missingness.profile"]',
                '"p7_capability_ids":["diagnostics.vif","missingness.profile"]',
                1,
            ),
            "completed workflow receipt",
        ),
        (
            "runs/notebook_source_acceptance/artifacts/notebook_workflow_results/notebook_workflow_result_acceptance.json",
            lambda text: text.replace(
                '"node_ref":"stage:raw"',
                '"node_ref":"stage:other"',
                1,
            ),
            "completed workflow receipt",
        ),
    ],
)
def test_notebook_evidence_collector_rejects_overbroad_or_drifted_receipts(
    tmp_path,
    relative_path: str,
    mutation,
    message: str,
) -> None:
    """An extra child or loosely matching receipt cannot prove the frozen request."""

    from workbench.qa.notebook_acceptance_evidence import (
        NotebookAcceptanceEvidenceError,
        collect_notebook_completion_evidence,
    )

    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    authority = _completion_authority_for_fixture(
        project_root, ("missingness.profile",)
    )
    target = project_root / relative_path
    original = target.read_text(encoding="utf-8")
    changed = mutation(original)
    assert changed != original
    target.write_text(changed, encoding="utf-8")
    if "notebook_workflow_result" in relative_path:
        index_path = project_root / "runs/notebook_source_acceptance/artifacts_index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        receipt_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        for entry in index["artifacts"]:
            if entry["artifact_id"] == "notebook_workflow_result_acceptance":
                entry["sha256"] = receipt_sha
        index_path.write_text(
            json.dumps(index, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    with pytest.raises(NotebookAcceptanceEvidenceError, match=message):
        collect_notebook_completion_evidence(
            project_root=project_root,
            operation_id="missingness.profile",
            notebook_id="nb_acceptance",
            option_id="opt_acceptance",
            option_revision=1,
            observation=observation,
            browser_snapshot=browser_snapshot,
            authority=authority,
        )


def test_notebook_evidence_collector_rejects_a_mismatched_browser_snapshot(
    tmp_path,
) -> None:
    """Observation metadata cannot stand in for the captured visible DOM bytes."""

    from workbench.qa.notebook_acceptance_evidence import (
        NotebookAcceptanceEvidenceError,
        collect_notebook_completion_evidence,
    )

    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    authority = _completion_authority_for_fixture(
        project_root, ("missingness.profile",)
    )
    browser_snapshot.write_bytes(b"different visible DOM\n")

    with pytest.raises(
        NotebookAcceptanceEvidenceError,
        match="browser DOM snapshot hash does not match",
    ):
        collect_notebook_completion_evidence(
            project_root=project_root,
            operation_id="missingness.profile",
            notebook_id="nb_acceptance",
            option_id="opt_acceptance",
            option_revision=1,
            observation=observation,
            browser_snapshot=browser_snapshot,
            authority=authority,
        )


def test_notebook_evidence_collector_rejects_self_certified_dom_without_control(
    tmp_path,
) -> None:
    """Rehashing unrelated DOM cannot impersonate a visible confirmation control."""

    from workbench.qa.notebook_acceptance_evidence import (
        BrowserConfirmationObservation,
        NotebookAcceptanceEvidenceError,
        collect_notebook_completion_evidence,
    )

    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    browser_snapshot.write_bytes(b"<main><p>No confirmation UI here</p></main>\n")
    forged = BrowserConfirmationObservation.create(
        browser_session_id=observation.browser_session_id,
        notebook_id=observation.notebook_id,
        option_id=observation.option_id,
        option_revision=observation.option_revision,
        confirmation_recorded_at=observation.confirmation_recorded_at,
        observed_url=observation.observed_url,
        confirmation_control_name=observation.confirmation_control_name,
        dom_snapshot_sha256=hashlib.sha256(browser_snapshot.read_bytes()).hexdigest(),
    )
    authority = _completion_authority_for_fixture(
        project_root, ("missingness.profile",)
    )

    with pytest.raises(
        NotebookAcceptanceEvidenceError,
        match="visible confirmation control",
    ):
        collect_notebook_completion_evidence(
            project_root=project_root,
            operation_id="missingness.profile",
            notebook_id="nb_acceptance",
            option_id="opt_acceptance",
            option_revision=1,
            observation=forged,
            browser_snapshot=browser_snapshot,
            authority=authority,
        )


def test_notebook_evidence_collector_hashes_the_declared_source_artifact(
    tmp_path,
) -> None:
    """Source provenance must bind real bytes, not matching caller-authored metadata."""

    from workbench.qa.notebook_acceptance_evidence import (
        NotebookAcceptanceEvidenceError,
        collect_notebook_completion_evidence,
    )

    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    source_path = (
        project_root
        / "runs/notebook_source_acceptance/raw_snapshot/raw.csv"
    )
    source_path.write_bytes(b"tampered source bytes\n")
    authority = _completion_authority_for_fixture(
        project_root, ("missingness.profile",)
    )

    with pytest.raises(
        NotebookAcceptanceEvidenceError,
        match="source artifact hash",
    ):
        collect_notebook_completion_evidence(
            project_root=project_root,
            operation_id="missingness.profile",
            notebook_id="nb_acceptance",
            option_id="opt_acceptance",
            option_revision=1,
            observation=observation,
            browser_snapshot=browser_snapshot,
            authority=authority,
        )


def test_notebook_evidence_collector_recomputes_the_workflow_plan(
    tmp_path,
) -> None:
    """Matching plan labels cannot replace a fingerprint derived from proposal content."""

    from workbench.qa.notebook_acceptance_evidence import (
        NotebookAcceptanceEvidenceError,
        collect_notebook_completion_evidence,
    )

    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    option_path = (
        project_root
        / "notebooks/nb_acceptance/options/opt_acceptance.jsonl"
    )
    original = option_path.read_text(encoding="utf-8")
    changed = original.replace(
        '"operation_id":"missingness.profile","spec":',
        '"expected_artifacts":["p7_analysis"],"operation_id":"missingness.profile","spec":',
        1,
    )
    assert changed != original
    option_path.write_text(changed, encoding="utf-8")
    authority = _completion_authority_for_fixture(
        project_root, ("missingness.profile",)
    )

    with pytest.raises(
        NotebookAcceptanceEvidenceError,
        match="workflow plan fingerprint",
    ):
        collect_notebook_completion_evidence(
            project_root=project_root,
            operation_id="missingness.profile",
            notebook_id="nb_acceptance",
            option_id="opt_acceptance",
            option_revision=1,
            observation=observation,
            browser_snapshot=browser_snapshot,
            authority=authority,
        )


def test_notebook_evidence_collector_binds_terminal_step_fingerprint(
    tmp_path,
) -> None:
    """A completed step must be the exact step compiled from the confirmed option."""

    from workbench.qa.notebook_acceptance_evidence import (
        NotebookAcceptanceEvidenceError,
        collect_notebook_completion_evidence,
    )

    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    workflow_path = project_root / "workbench/workflows/workflow_acceptance.jsonl"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    workflow["steps"]["target_step"]["fingerprint"] = "sha256:" + "9" * 64
    workflow_path.write_text(
        json.dumps(workflow, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    authority = _completion_authority_for_fixture(
        project_root, ("missingness.profile",)
    )

    with pytest.raises(
        NotebookAcceptanceEvidenceError,
        match="workflow step fingerprint",
    ):
        collect_notebook_completion_evidence(
            project_root=project_root,
            operation_id="missingness.profile",
            notebook_id="nb_acceptance",
            option_id="opt_acceptance",
            option_revision=1,
            observation=observation,
            browser_snapshot=browser_snapshot,
            authority=authority,
        )


def test_notebook_evidence_collector_binds_artifact_step_fingerprint(
    tmp_path,
) -> None:
    """Reindexed artifact bytes still must come from the confirmed workflow step."""

    from workbench.qa.notebook_acceptance_evidence import (
        NotebookAcceptanceEvidenceError,
        collect_notebook_completion_evidence,
    )

    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    run_root = project_root / "runs/notebook_source_acceptance"
    artifact_path = (
        run_root
        / "artifacts/p7_analysis/workflow_p7_acceptance.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["source"]["workflow_step_fingerprint"] = "sha256:" + "8" * 64
    artifact_path.write_text(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    artifact_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    for entry in index["artifacts"]:
        if entry["artifact_id"] == "workflow_p7_acceptance":
            entry["sha256"] = artifact_sha
    receipt_path = (
        run_root
        / "artifacts/notebook_workflow_results/notebook_workflow_result_acceptance.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["output_artifacts"][0]["sha256"] = artifact_sha
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    for entry in index["artifacts"]:
        if entry["artifact_id"] == "notebook_workflow_result_acceptance":
            entry["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    index_path.write_text(
        json.dumps(index, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    authority = _completion_authority_for_fixture(
        project_root, ("missingness.profile",)
    )

    with pytest.raises(
        NotebookAcceptanceEvidenceError,
        match="artifact workflow step fingerprint",
    ):
        collect_notebook_completion_evidence(
            project_root=project_root,
            operation_id="missingness.profile",
            notebook_id="nb_acceptance",
            option_id="opt_acceptance",
            option_revision=1,
            observation=observation,
            browser_snapshot=browser_snapshot,
            authority=authority,
        )


def test_cli_builds_browser_work_packets_without_provider_or_auto_confirmation(
    tmp_path,
) -> None:
    """The CLI coordinates human-visible work but never performs it automatically."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    root = Path(__file__).resolve().parents[1]
    python = root / ".venv" / "bin" / "python"
    runner = root / "scripts" / "p7_acceptance_runner.py"
    manifest = tmp_path / "manifest.json"
    attempts = tmp_path / "attempts.jsonl"
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(
        json.dumps(
            {
                "missingness.profile": {
                    "status": "ready",
                    "fixture_id": "survey_missingness_v1",
                    "source": "generated_example",
                }
            }
        ),
        encoding="utf-8",
    )

    def run(*arguments: str) -> dict[str, object]:
        completed = subprocess.run(
            [str(python), str(runner), *arguments],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(completed.stdout)

    mismatched = subprocess.run(
        [
            str(python),
            str(runner),
            "init",
            "--manifest",
            str(tmp_path / "mismatched-manifest.json"),
            "--git-head",
            "0" * 40,
            "--provider",
            "deepseek",
            "--model",
            "deepseek-v4",
            "--refill-per-second",
            "1",
        ],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )
    assert mismatched.returncode == 2
    assert "does not match the current checkout" in mismatched.stderr
    assert not (tmp_path / "mismatched-manifest.json").exists()

    initialized = run(
        "init",
        "--manifest",
        str(manifest),
        "--fixture-catalog",
        str(fixtures),
        "--provider",
        "deepseek",
        "--model",
        "deepseek-v4",
        "--capacity",
        "2",
        "--refill-per-second",
        "0.5",
        "--created-at",
        "2026-08-09T12:00:00Z",
    )
    assert initialized["total_rows"] == len(p7_pack_registry.operation_ids())
    assert initialized["ready"] == 1
    assert initialized["blocked"] == len(p7_pack_registry.operation_ids()) - 1

    status = run(
        "status", "--manifest", str(manifest), "--attempts", str(attempts)
    )
    assert status["counts"]["pending"] == 1
    assert status["counts"]["blocked"] == len(p7_pack_registry.operation_ids()) - 1
    assert not attempts.exists()

    next_item = run(
        "next",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
    )
    assert next_item["row"]["operation_id"] == "missingness.profile"
    assert next_item["provider_called"] is False
    assert next_item["confirmation_performed"] is False
    assert "start-attempt before submitting" in next_item["row"]["next_action"]
    assert all(
        token not in next_item["row"]["prompt"].casefold()
        for token in _PROTOCOL_TOKENS
    )
    assert not attempts.exists()

    started = run(
        "start-attempt",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--operation-id",
        "missingness.profile",
    )
    assert started["attempt"]["attempt_no"] == 1
    assert started["attempt"]["status"] == "awaiting_confirmation"
    assert started["provider_called"] is False
    assert started["confirmation_performed"] is False
    assert "Admission is durable" in started["row"]["next_action"]

    active_next = run(
        "next",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
    )
    assert active_next["row"]["operation_id"] == "missingness.profile"
    assert active_next["action"] == "reopen_confirmation"
    assert active_next["attempt_no"] == 1
    assert active_next["requires_provider_admission"] is False

    recorded = run(
        "record",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--operation-id",
        "missingness.profile",
        "--attempt-no",
        "1",
        "--status",
        "failed",
        "--reason-code",
        "provider_error",
        "--reason-detail",
        "Visible upstream failure.",
    )
    assert recorded["attempt"]["status"] == "failed"

    retried = run(
        "retry",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--operation-id",
        "missingness.profile",
    )
    assert retried["attempt"]["attempt_no"] == 2
    assert retried["attempt"]["retry_of"] == 1
    assert retried["provider_called"] is False


def test_cli_batches_one_live_family_without_a_handwritten_operation_list(
    tmp_path,
) -> None:
    """The batch CLI emits and records one family submission without calling an LLM."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    root = Path(__file__).resolve().parents[1]
    python = root / ".venv" / "bin" / "python"
    runner = root / "scripts" / "p7_acceptance_runner.py"
    manifest = tmp_path / "manifest.json"
    attempts = tmp_path / "attempts.jsonl"
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(
        json.dumps(
            {
                "families": {
                    "missing_data": {
                        "status": "ready",
                        "fixture_id": "missing_data_browser_v1",
                        "source": "generated_example",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def run(*arguments: str) -> dict[str, object]:
        completed = subprocess.run(
            [str(python), str(runner), *arguments],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(completed.stdout)

    run(
        "init",
        "--manifest",
        str(manifest),
        "--fixture-catalog",
        str(fixtures),
        "--provider",
        "deepseek",
        "--model",
        "deepseek-v4",
        "--capacity",
        "1",
        "--refill-per-second",
        "1",
        "--created-at",
        "2026-08-09T12:00:00Z",
    )
    next_batch = run(
        "next-batch",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
    )
    expected_ids = {
        operation_id
        for operation_id in p7_pack_registry.operation_ids()
        if p7_pack_registry.get(operation_id).pack_family == "missing_data"
    }
    assert next_batch["batch"]["pack_family"] == "missing_data"
    assert set(next_batch["batch"]["operation_ids"]) == expected_ids
    assert next_batch["provider_called"] is False
    assert next_batch["confirmation_performed"] is False
    assert "start-batch before submitting" in next_batch["batch"]["next_action"]

    started = run(
        "start-batch",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--pack-family",
        "missing_data",
    )
    assert {event["operation_id"] for event in started["attempts"]} == expected_ids
    assert len({event["submission_id"] for event in started["attempts"]}) == 1
    assert "Admission is durable" in started["batch"]["next_action"]

    failed = run(
        "record-batch",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--pack-family",
        "missing_data",
        "--status",
        "failed",
        "--reason-code",
        "provider_error",
        "--reason-detail",
        "Visible first attempt failed.",
    )
    assert {event["status"] for event in failed["attempts"]} == {"failed"}

    retried = run(
        "retry-batch",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--pack-family",
        "missing_data",
    )
    assert {event["attempt_no"] for event in retried["attempts"]} == {2}
    assert {event["retry_of"] for event in retried["attempts"]} == {1}


def test_cli_collects_every_family_child_from_one_durable_notebook_chain(
    tmp_path,
) -> None:
    """One browser confirmation proves each batch child against durable records."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    root = Path(__file__).resolve().parents[1]
    python = root / ".venv" / "bin" / "python"
    runner = root / "scripts" / "p7_acceptance_runner.py"
    manifest = tmp_path / "manifest.json"
    attempts = tmp_path / "attempts.jsonl"
    fixtures = tmp_path / "fixtures.json"
    operation_ids = tuple(
        operation_id
        for operation_id in p7_pack_registry.operation_ids()
        if p7_pack_registry.get(operation_id).pack_family == "missing_data"
    )
    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project",
        operation_ids=operation_ids,
    )
    observation_path = tmp_path / "browser-observation.json"
    fixtures.write_text(
        json.dumps(
            {
                "families": {
                    "missing_data": {
                        "status": "ready",
                        "fixture_id": "missing_data_browser_v1",
                        "source": str(project_root),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    observation_path.write_text(
        json.dumps(observation.to_dict()),
        encoding="utf-8",
    )

    def execute(*arguments: str) -> dict[str, object]:
        completed = subprocess.run(
            [str(python), str(runner), *arguments],
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        return json.loads(completed.stdout)

    execute(
        "init",
        "--manifest",
        str(manifest),
        "--fixture-catalog",
        str(fixtures),
        "--provider",
        "deepseek",
        "--model",
        "deepseek-v4",
        "--capacity",
        "1",
        "--refill-per-second",
        "1",
        "--created-at",
        "2026-08-09T12:00:00Z",
    )
    started = execute(
        "start-batch",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--pack-family",
        "missing_data",
    )
    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        project_root,
        operation_ids=operation_ids,
        recorded_after=started["attempts"][0]["occurred_at"],
    )
    observation_path.write_text(
        json.dumps(observation.to_dict()),
        encoding="utf-8",
    )
    completed = execute(
        "record-batch",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--pack-family",
        "missing_data",
        "--status",
        "completed",
        "--project-root",
        str(project_root),
        "--notebook-id",
        "nb_acceptance",
        "--option-id",
        "opt_acceptance",
        "--option-revision",
        "1",
        "--browser-observation",
        str(observation_path),
        "--browser-snapshot",
        str(browser_snapshot),
    )

    assert completed["evidence_collected"] == len(operation_ids)
    assert {event["operation_id"] for event in completed["attempts"]} == set(
        operation_ids
    )
    assert {event["status"] for event in completed["attempts"]} == {"completed"}


def test_cli_rejects_removed_legacy_migration_command(tmp_path) -> None:
    """Development-only ledger migration is absent; uncontrolled history stays closed."""

    root = Path(__file__).resolve().parents[1]
    python = root / ".venv" / "bin" / "python"
    runner = root / "scripts" / "p7_acceptance_runner.py"
    completed = subprocess.run(
        [str(python), str(runner), "migrate"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 2
    assert "invalid choice: 'migrate'" in completed.stderr


def test_cli_completed_state_is_collected_from_the_durable_notebook_chain(
    tmp_path,
) -> None:
    """The CLI refuses caller-authored completion and collects the real chain."""

    root = Path(__file__).resolve().parents[1]
    python = root / ".venv" / "bin" / "python"
    runner = root / "scripts" / "p7_acceptance_runner.py"
    manifest = tmp_path / "manifest.json"
    attempts = tmp_path / "attempts.jsonl"
    fixtures = tmp_path / "fixtures.json"
    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        tmp_path / "project"
    )
    observation_path = tmp_path / "browser-observation.json"
    fixtures.write_text(
        json.dumps(
            {
                "missingness.profile": {
                    "status": "ready",
                    "fixture_id": "browser_fixture_v1",
                    "source": str(project_root),
                }
            }
        ),
        encoding="utf-8",
    )
    observation_path.write_text(
        json.dumps(observation.to_dict()),
        encoding="utf-8",
    )

    def execute(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(python), str(runner), *arguments],
            cwd=root,
            check=check,
            text=True,
            capture_output=True,
        )

    execute(
        "init",
        "--manifest",
        str(manifest),
        "--fixture-catalog",
        str(fixtures),
        "--provider",
        "deepseek",
        "--model",
        "deepseek-v4",
        "--capacity",
        "1",
        "--refill-per-second",
        "1",
        "--created-at",
        "2026-08-09T12:00:00Z",
    )
    started = execute(
        "start-attempt",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--operation-id",
        "missingness.profile",
    )
    started_payload = json.loads(started.stdout)
    project_root, observation, browser_snapshot = _write_notebook_chain_fixture(
        project_root,
        recorded_after=started_payload["attempt"]["occurred_at"],
    )
    observation_path.write_text(
        json.dumps(observation.to_dict()),
        encoding="utf-8",
    )

    missing = execute(
        "record",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--operation-id",
        "missingness.profile",
        "--attempt-no",
        "1",
        "--status",
        "completed",
        check=False,
    )
    assert missing.returncode == 2
    assert "completed status requires project_root" in missing.stderr

    completed = execute(
        "record",
        "--manifest",
        str(manifest),
        "--attempts",
        str(attempts),
        "--operation-id",
        "missingness.profile",
        "--attempt-no",
        "1",
        "--status",
        "completed",
        "--project-root",
        str(project_root),
        "--notebook-id",
        "nb_acceptance",
        "--option-id",
        "opt_acceptance",
        "--option-revision",
        "1",
        "--browser-observation",
        str(observation_path),
        "--browser-snapshot",
        str(browser_snapshot),
    )
    payload = json.loads(completed.stdout)
    assert payload["attempt"]["status"] == "completed"
    assert payload["trust_level"] == "coordinator_only"
    assert payload["verification_status"] == "NOT VERIFIED"
    assert payload["attempt"]["evidence"]["child_operation_id"] == "missingness.profile"
    assert payload["evidence_collected"] is True


def test_cli_executes_every_live_p7_operation_through_generic_workflow(tmp_path) -> None:
    """The batch executor records every live operation without browser evidence."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    root = Path(__file__).resolve().parents[1]
    python = root / ".venv" / "bin" / "python"
    runner = root / "scripts" / "p7_acceptance_runner.py"
    manifest = tmp_path / "manifest.json"
    results = tmp_path / "execution-results.json"
    work_root = tmp_path / "execution-work"
    fixtures = tmp_path / "fixtures.json"
    families = {
        p7_pack_registry.get(operation_id).pack_family
        for operation_id in p7_pack_registry.operation_ids()
    }
    fixtures.write_text(
        json.dumps(
            {
                "families": {
                    family: {
                        "status": "ready",
                        "fixture_id": "p7_generated_example_v1",
                        "source": "generated_example",
                    }
                    for family in sorted(families)
                }
            }
        ),
        encoding="utf-8",
    )

    def execute(*arguments: str) -> dict[str, object]:
        completed = subprocess.run(
            [str(python), str(runner), *arguments],
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        return json.loads(completed.stdout)

    execute(
        "init",
        "--manifest",
        str(manifest),
        "--fixture-catalog",
        str(fixtures),
        "--provider",
        "deepseek",
        "--model",
        "deepseek-v4",
        "--capacity",
        "64",
        "--refill-per-second",
        "64",
        "--created-at",
        "2026-08-10T12:00:00Z",
    )
    payload = execute(
        "execute-batch",
        "--manifest",
        str(manifest),
        "--results",
        str(results),
        "--work-root",
        str(work_root),
        "--expected-failure",
        "glm.hurdle_negative_binomial=GLM_NONCONVERGENCE",
    )

    operation_ids = set(p7_pack_registry.operation_ids())
    assert payload["total_rows"] == len(operation_ids) == 64
    assert payload["terminal_outcomes"] == 64
    assert payload["counts"] == {"completed": 63, "expected_failure": 1}
    assert payload["browser_confirmation_performed"] is False
    assert payload["verification_status"] == "NOT VERIFIED"
    persisted = json.loads(results.read_text(encoding="utf-8"))
    assert {item["operation_id"] for item in persisted["operations"]} == operation_ids
    assert persisted["manifest_digest"] == payload["manifest_digest"]
