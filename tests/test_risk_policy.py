from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
import time

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from workbench.agent.operations import (
    OperationDefinition,
    OperationRecordStore,
    OperationRecordTransitionError,
    OperationRegistry,
)
from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.proposals import ProposalConfirmation
from workbench.agent.session import JsonlSessionRepository
from workbench.app import app
from tests.test_data_column_cast import _source_project


def _high_confirmation(proposal_id: str = "proposal-high-1") -> ProposalConfirmation:
    return ProposalConfirmation(
        proposal_id=proposal_id,
        operation_id="test.high_risk",
        operation_version="v1",
        revision=1,
        fingerprint="fingerprint-high-1",
        session_id="session-1",
        chain_id="chain-1",
        command_id="command-1",
        target={"run_id": "run-1", "node_ref": "dataset:source"},
        preconditions={
            "context_fingerprint": "context-high-1",
            "active_head_run_id": "run-1",
        },
        actor_type="user",
        confirmed_at="2026-07-16T00:00:00+00:00",
        status="confirmed",
    )


def _high_registry() -> OperationRegistry:
    registry = OperationRegistry()
    registry.register(
        OperationDefinition(
            operation_id="test.high_risk",
            operation_version="v1",
            risk_level="high",
            confirmation_policy="required",
            executor_key="test.high_risk",
        )
    )
    return registry


def _grant(store, *, ttl_seconds: int = 300):
    return store.issue(
        operation_id="test.high_risk",
        operation_version="v1",
        proposal_id="proposal-high-1",
        revision=1,
        fingerprint="fingerprint-high-1",
        session_id="session-1",
        chain_id="chain-1",
        active_head_run_id="run-1",
        actor_type="user",
        ttl_seconds=ttl_seconds,
    )


def test_high_risk_authorization_binds_operation_and_active_head(tmp_path: Path) -> None:
    from workbench.agent.risk import RiskAuthorizationStore

    store = RiskAuthorizationStore(tmp_path)
    grant = _grant(store)

    assert grant.authorization_id
    assert grant.token
    assert grant.operation_id == "test.high_risk"
    assert grant.proposal_id == "proposal-high-1"
    assert grant.active_head_run_id == "run-1"
    assert grant.expires_at > grant.issued_at
    assert "token" not in store.read(grant.authorization_id)


def test_registry_exposes_explicit_policy_only_for_high_risk_operations() -> None:
    registry = OperationRegistry()
    high = registry.require("code.execute", "v1")
    ordinary = registry.require("data.column.cast", "v1")

    assert high.risk_level == "high"
    assert high.risk_authorization_policy == "explicit_single_use"
    assert high.requires_risk_authorization is True
    assert ordinary.risk_authorization_policy == "none"
    assert ordinary.requires_risk_authorization is False


def test_risk_authorization_expires_and_replay_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.agent.risk import (
        RiskAuthorizationExpired,
        RiskAuthorizationReplay,
        RiskAuthorizationStore,
    )

    store = RiskAuthorizationStore(tmp_path)
    expired = _grant(store)
    expires_after = datetime.fromisoformat(expired.expires_at) + timedelta(seconds=1)
    monkeypatch.setattr(
        "workbench.agent.risk._now",
        lambda: expires_after,
    )
    with pytest.raises(RiskAuthorizationExpired):
        store.consume(
            expired.authorization_id,
            token=expired.token,
            operation_id="test.high_risk",
            operation_version="v1",
            proposal_id="proposal-high-1",
            revision=1,
            fingerprint="fingerprint-high-1",
            session_id="session-1",
            chain_id="chain-1",
            active_head_run_id="run-1",
            execution_key="exec-expired",
        )

    monkeypatch.setattr(
        "workbench.agent.risk._now",
        lambda: datetime.now(timezone.utc),
    )
    grant = _grant(store)
    store.consume(
        grant.authorization_id,
        token=grant.token,
        operation_id="test.high_risk",
        operation_version="v1",
        proposal_id="proposal-high-1",
        revision=1,
        fingerprint="fingerprint-high-1",
        session_id="session-1",
        chain_id="chain-1",
        active_head_run_id="run-1",
        execution_key="exec-one",
    )
    with pytest.raises(RiskAuthorizationReplay):
        store.consume(
            grant.authorization_id,
            token=grant.token,
            operation_id="test.high_risk",
            operation_version="v1",
            proposal_id="proposal-high-1",
            revision=1,
            fingerprint="fingerprint-high-1",
            session_id="session-1",
            chain_id="chain-1",
            active_head_run_id="run-1",
            execution_key="exec-two",
        )


def test_separate_authorization_stores_allow_only_one_concurrent_consume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one-time token remains exclusive across request-local stores."""

    import workbench.agent.risk as risk_module

    store_a = risk_module.RiskAuthorizationStore(tmp_path)
    grant = _grant(store_a)
    store_b = risk_module.RiskAuthorizationStore(tmp_path)
    start = Barrier(2)
    original_append = risk_module.append_jsonl_atomic

    def delayed_append(path, value):
        if value.get("status") == "consumed":
            time.sleep(0.05)
        return original_append(path, value)

    monkeypatch.setattr(risk_module, "append_jsonl_atomic", delayed_append)

    def consume(store: risk_module.RiskAuthorizationStore, execution_key: str) -> str:
        start.wait()
        try:
            store.consume(
                grant.authorization_id,
                token=grant.token or "",
                operation_id="test.high_risk",
                operation_version="v1",
                proposal_id="proposal-high-1",
                revision=1,
                fingerprint="fingerprint-high-1",
                session_id="session-1",
                chain_id="chain-1",
                active_head_run_id="run-1",
                execution_key=execution_key,
            )
        except risk_module.RiskAuthorizationReplay:
            return "replay"
        return "ok"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(
            pool.map(
                lambda args: consume(*args),
                ((store_a, "exec-a"), (store_b, "exec-b")),
            )
        )

    assert outcomes == ["ok", "replay"]


def test_risk_authorization_rejects_active_head_change(tmp_path: Path) -> None:
    from workbench.agent.risk import RiskAuthorizationStale, RiskAuthorizationStore

    store = RiskAuthorizationStore(tmp_path)
    grant = _grant(store)
    with pytest.raises(RiskAuthorizationStale):
        store.consume(
            grant.authorization_id,
            token=grant.token,
            operation_id="test.high_risk",
            operation_version="v1",
            proposal_id="proposal-high-1",
            revision=1,
            fingerprint="fingerprint-high-1",
            session_id="session-1",
            chain_id="chain-1",
            active_head_run_id="run-2",
            execution_key="exec-stale-head",
        )


def test_same_execution_key_reconsume_is_idempotent(tmp_path: Path) -> None:
    from workbench.agent.risk import RiskAuthorizationStore

    store = RiskAuthorizationStore(tmp_path)
    grant = _grant(store)
    kwargs = {
        "token": grant.token,
        "operation_id": "test.high_risk",
        "operation_version": "v1",
        "proposal_id": "proposal-high-1",
        "revision": 1,
        "fingerprint": "fingerprint-high-1",
        "session_id": "session-1",
        "chain_id": "chain-1",
        "active_head_run_id": "run-1",
        "execution_key": "exec-one",
    }

    first = store.consume(grant.authorization_id, **kwargs)
    repeated = store.consume(grant.authorization_id, **kwargs)

    assert first.status == "consumed"
    assert repeated.status == "consumed"
    assert repeated.consumed_at == first.consumed_at


def test_pending_operation_can_replace_unconsumed_grant_but_not_claimed_one(
    tmp_path: Path,
) -> None:
    from workbench.agent.execution import execution_key
    from workbench.agent.risk import RiskAuthorizationStore

    record_store = OperationRecordStore(tmp_path)
    record = record_store.create_pending(_high_confirmation())
    risk_store = RiskAuthorizationStore(tmp_path)
    first = _grant(risk_store)
    second = _grant(risk_store)

    record = record_store.bind_risk_authorization(record.record_id, first.authorization_id)
    record = record_store.bind_risk_authorization(record.record_id, second.authorization_id)
    assert record.execution["risk_authorization_id"] == second.authorization_id

    claimed = record_store.claim_execution(
        record.record_id,
        execution_key=execution_key(
            proposal_id=record.proposal_id,
            revision=record.proposal_revision,
            fingerprint=record.proposal_fingerprint,
        ),
        lease_owner="test-worker",
    )
    with pytest.raises(OperationRecordTransitionError, match="another risk authorization"):
        record_store.bind_risk_authorization(claimed.record_id, first.authorization_id)


def test_consumed_grant_is_the_only_recovery_authorization(tmp_path: Path) -> None:
    from workbench.agent.execution import execution_key
    from workbench.agent.risk import RiskAuthorizationReplay, RiskAuthorizationStore

    record_store = OperationRecordStore(tmp_path)
    confirmation = _high_confirmation()
    record = record_store.create_pending(confirmation)
    risk_store = RiskAuthorizationStore(tmp_path)
    first = _grant(risk_store)
    second = _grant(risk_store)
    record_store.bind_risk_authorization(record.record_id, first.authorization_id)
    key = execution_key(
        proposal_id=confirmation.proposal_id,
        revision=confirmation.revision,
        fingerprint=confirmation.fingerprint,
    )
    risk_store.consume(
        first.authorization_id,
        token=first.token,
        operation_id=confirmation.operation_id,
        operation_version=confirmation.operation_version,
        proposal_id=confirmation.proposal_id,
        revision=confirmation.revision,
        fingerprint=confirmation.fingerprint,
        session_id=confirmation.session_id,
        chain_id=confirmation.chain_id,
        active_head_run_id="run-1",
        execution_key=key,
    )
    orchestrator = WorkbenchOrchestrator(
        JsonlSessionRepository(tmp_path),
        AgentEventStream(tmp_path),
        main_session_id="main",
        operation_store=record_store,
        operation_registry=_high_registry(),
        risk_authorization_store=risk_store,
    )

    with pytest.raises(RiskAuthorizationReplay):
        asyncio.run(
            orchestrator.execute_confirmed_operation(
                record.record_id,
                project_root=tmp_path,
                current_context_fingerprint="context-high-1",
                current_active_head_run_id="run-1",
                risk_authorization_id=second.authorization_id,
                risk_authorization_token=second.token,
            )
        )


def test_generic_lifecycle_rejects_high_risk_without_authorization(tmp_path: Path) -> None:
    from workbench.agent.execution import OperationEffect, WorkbenchOperationLifecycle

    class Handler:
        def __init__(self) -> None:
            self.execute_calls = 0

        async def execute(self, record, *, execution_key, failpoint):
            self.execute_calls += 1
            return OperationEffect(outputs={"effect": True})

        async def reconcile(self, record, *, execution_key, failpoint):
            raise AssertionError("must not reconcile without risk authorization")

    record_store = OperationRecordStore(tmp_path)
    record = record_store.create_pending(_high_confirmation())
    handler = Handler()
    lifecycle = WorkbenchOperationLifecycle(
        operation_store=record_store,
        operation_registry=_high_registry(),
        handlers={"test.high_risk": handler},
        lease_owner="test-worker",
    )

    failed = asyncio.run(lifecycle.execute(record.record_id))

    assert failed.status == "failed"
    assert failed.error == {"type": "RiskAuthorizationRequired"}
    assert handler.execute_calls == 0


def test_generic_lifecycle_consumes_authorization_before_effect(tmp_path: Path) -> None:
    from workbench.agent.execution import OperationEffect, WorkbenchOperationLifecycle, execution_key
    from workbench.agent.risk import RiskAuthorizationStore

    class Handler:
        def __init__(self) -> None:
            self.execute_calls = 0

        async def execute(self, record, *, execution_key, failpoint):
            self.execute_calls += 1
            return OperationEffect(outputs={"effect": True})

        async def reconcile(self, record, *, execution_key, failpoint):
            return OperationEffect(outputs={"effect": True})

    confirmation = _high_confirmation()
    record_store = OperationRecordStore(tmp_path)
    record = record_store.create_pending(confirmation)
    risk_store = RiskAuthorizationStore(tmp_path)
    grant = _grant(risk_store)
    record = record_store.bind_risk_authorization(record.record_id, grant.authorization_id)
    key = execution_key(
        proposal_id=confirmation.proposal_id,
        revision=confirmation.revision,
        fingerprint=confirmation.fingerprint,
    )
    risk_store.consume(
        grant.authorization_id,
        token=grant.token,
        operation_id=confirmation.operation_id,
        operation_version=confirmation.operation_version,
        proposal_id=confirmation.proposal_id,
        revision=confirmation.revision,
        fingerprint=confirmation.fingerprint,
        session_id=confirmation.session_id,
        chain_id=confirmation.chain_id,
        active_head_run_id="run-1",
        execution_key=key,
    )
    handler = Handler()
    lifecycle = WorkbenchOperationLifecycle(
        operation_store=record_store,
        operation_registry=_high_registry(),
        handlers={"test.high_risk": handler},
        lease_owner="test-worker",
        risk_authorization_store=risk_store,
    )

    completed = asyncio.run(lifecycle.execute(record.record_id))

    assert completed.status == "completed"
    assert completed.execution["risk_authorization_id"] == grant.authorization_id
    assert handler.execute_calls == 1


def test_high_risk_failpoint_recovery_does_not_repeat_effect(tmp_path: Path) -> None:
    from workbench.agent.execution import (
        InjectedOperationCrash,
        OperationEffect,
        WorkbenchOperationLifecycle,
        execution_key,
    )
    from workbench.agent.risk import RiskAuthorizationStore

    class CrashOnce:
        triggered = False

        def hit(self, point: str, record) -> None:
            if point == "before_child_effect" and not self.triggered:
                self.triggered = True
                raise InjectedOperationCrash(point)

    class Handler:
        def __init__(self) -> None:
            self.effects: dict[str, int] = {}

        async def execute(self, record, *, execution_key, failpoint):
            self.effects[execution_key] = self.effects.get(execution_key, 0) + 1
            return OperationEffect(outputs={"effect": True})

        async def reconcile(self, record, *, execution_key, failpoint):
            return OperationEffect(outputs={"effect": True})

    confirmation = _high_confirmation()
    record_store = OperationRecordStore(tmp_path)
    record = record_store.create_pending(confirmation)
    risk_store = RiskAuthorizationStore(tmp_path)
    grant = _grant(risk_store)
    record = record_store.bind_risk_authorization(record.record_id, grant.authorization_id)
    key = execution_key(
        proposal_id=confirmation.proposal_id,
        revision=confirmation.revision,
        fingerprint=confirmation.fingerprint,
    )
    risk_store.consume(
        grant.authorization_id,
        token=grant.token,
        operation_id=confirmation.operation_id,
        operation_version=confirmation.operation_version,
        proposal_id=confirmation.proposal_id,
        revision=confirmation.revision,
        fingerprint=confirmation.fingerprint,
        session_id=confirmation.session_id,
        chain_id=confirmation.chain_id,
        active_head_run_id="run-1",
        execution_key=key,
    )
    handler = Handler()
    crashed = WorkbenchOperationLifecycle(
        operation_store=record_store,
        operation_registry=_high_registry(),
        handlers={"test.high_risk": handler},
        lease_owner="test-worker",
        failpoint=CrashOnce(),
        risk_authorization_store=risk_store,
    )

    with pytest.raises(InjectedOperationCrash):
        asyncio.run(crashed.execute(record.record_id))

    recovered = WorkbenchOperationLifecycle(
        operation_store=record_store,
        operation_registry=_high_registry(),
        handlers={"test.high_risk": handler},
        lease_owner="test-worker",
        risk_authorization_store=risk_store,
    )
    completed = asyncio.run(recovered.execute(record.record_id))

    assert completed.status == "completed"
    assert handler.effects == {key: 1}


def _fake_code_preview(_root, spec):
    from workbench.code_execution import CodeExecutePreview

    return CodeExecutePreview(
        spec=spec,
        source_sha256="source-sha-1",
        row_count_before=2,
        row_count_after=2,
        columns_added=("derived",),
        columns_removed=(),
        dtype_changes=(),
        schema_fingerprint_before="schema-before",
        schema_fingerprint_after="schema-after",
        result_fingerprint="result-fingerprint",
        result_preview_rows=(),
        stdout="",
        fingerprint="code-preview-fingerprint",
        downstream_invalidation=("model:ols",),
    )


def _code_request(run_id: str, artifact_id: str) -> dict[str, object]:
    return {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "code": "result = df",
        "language": "python",
        "output_format": "csv",
        "preview_fingerprint": "code-preview-fingerprint",
        "session_id": "agent_data_ui",
    }


def test_code_execute_confirm_requires_risk_authorization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import data_operation_routes

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": [10, 11]}),
    )
    monkeypatch.setattr(data_operation_routes, "preview_code_execute", _fake_code_preview)

    with TestClient(app) as client:
        response = client.post(
            "/data-operations/code-execute/confirm",
            params={"project_root": str(project)},
            json=_code_request(run_id, artifact_id),
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RISK_AUTHORIZATION_REQUIRED"
    assert response.json()["error"]["details"]["operation_id"] == "code.execute"


def test_code_execute_risk_authorization_is_explicit_and_durable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import data_operation_routes

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": [10, 11]}),
    )
    monkeypatch.setattr(data_operation_routes, "preview_code_execute", _fake_code_preview)

    with TestClient(app) as client:
        response = client.post(
            "/data-operations/code-execute/risk-authorize",
            params={"project_root": str(project)},
            json={**_code_request(run_id, artifact_id), "acknowledge_risk": True},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "risk_authorized"
    authorization = body["risk_authorization"]
    assert authorization["operation_id"] == "code.execute"
    assert authorization["active_head_run_id"] == run_id
    assert authorization["token"]
    stored = list((project / "workbench" / "risk-authorizations").glob("*.jsonl"))
    assert len(stored) == 1
    assert authorization["token"] not in stored[0].read_text(encoding="utf-8")
