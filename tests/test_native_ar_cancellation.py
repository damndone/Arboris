"""Real native loops must schedule the server and obey the owner's cancel check."""
import asyncio
import threading
import time

import numpy as np
import pytest

from tests.test_native_ar_exact import _case, _native


def test_native_ar_callback_preserves_original_exception():
    native = _native()
    original = ValueError('owner cancelled this exact calculation')

    def check():
        raise original

    with native.cancellation_scope(check):
        with pytest.raises(ValueError) as caught:
            native.robust_polynomials(*_case(), 3.84)
    assert caught.value is original


def test_native_ar_robust_set_does_not_turn_callback_error_into_unavailable(monkeypatch):
    native = _native()
    from workbench.checks import ar_confidence, ar_verified
    original = ValueError('rank_deficient_auxiliary_design')
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise original

    def uncertain(*args):
        raise ar_verified.VerificationUncertain('exercise real exact kernel')

    monkeypatch.setattr(ar_verified, 'verified_set', uncertain)
    with native.cancellation_scope(check):
        with pytest.raises(ValueError) as caught:
            ar_confidence.robust_set(*_case())
    assert caught.value is original


def test_native_ar_real_thread_yields_to_event_loop_and_terminates_on_cancel(record_property):
    native = _native()
    values = _case(n=250_000, p=3, q=2)
    started = threading.Event()
    cancelled = threading.Event()
    stopped = threading.Event()
    native_errors = []
    original = asyncio.CancelledError('real owner cancellation')

    def check():
        started.set()
        if cancelled.is_set():
            raise original

    def calculate():
        try:
            with native.cancellation_scope(check):
                native.robust_polynomials(*values, 5.99)
        except BaseException as error:
            native_errors.append(error)
            raise
        finally:
            stopped.set()

    async def scenario():
        job = asyncio.create_task(asyncio.to_thread(calculate))
        deadline = time.monotonic()+5
        while not started.is_set():
            assert time.monotonic() < deadline
            await asyncio.sleep(.001)
        before = time.monotonic()
        await asyncio.sleep(.02)
        schedule_delay = time.monotonic()-before
        assert not stopped.is_set(), 'the real native loop must still be running'
        cancelled.set()
        before = time.monotonic()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(job), 2)
        # asyncio.shield may synthesize CancelledError; the native boundary
        # itself must retain the owner's exact exception object.
        assert native_errors == [original]
        assert stopped.is_set(), 'cancelling await alone is insufficient'
        drain_seconds = time.monotonic()-before
        record_property('native_cancel_drain_seconds', drain_seconds)
        record_property('event_loop_schedule_seconds', schedule_delay)
        assert drain_seconds < 2
        assert schedule_delay < .2

    asyncio.run(scenario())


def test_native_ar_missing_extension_reference_worker_really_stops(tmp_path, monkeypatch, record_property):
    native = _native(require_kernel=False)
    from workbench.checks import ar_confidence as ar
    monkeypatch.setattr(native, '_kernel', None)
    values = _case(n=250_000, p=3, q=2)
    started = threading.Event()
    requested = threading.Event()
    stopped = threading.Event()

    def check():
        started.set()
        if requested.is_set():
            raise asyncio.CancelledError('cancel reference exact worker')

    def calculate():
        try:
            with native.cancellation_scope(check):
                ar.robust_polynomials(*values, 5.99)
        finally:
            stopped.set()

    async def scenario():
        job = asyncio.create_task(asyncio.to_thread(calculate))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            assert not stopped.is_set()
            requested.set()
            before = time.monotonic()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(job), 2)
            assert stopped.is_set(), 'the reference worker must stop, not just its await'
            elapsed = time.monotonic()-before
            record_property('missing_native_reference_drain_seconds', elapsed)
            assert elapsed < 2
        finally:
            requested.set()
            await asyncio.gather(job, return_exceptions=True)

    asyncio.run(scenario())


def test_native_ar_cancel_during_covariance_not_only_scale_or_gram():
    native = _native()
    values = _case(n=2048, p=2, q=1)
    from workbench.checks.ar_confidence import _inverse_integer
    scale, gram, cy, cx = native.sufficient_statistics(*values)
    a, d = _inverse_integer(gram)
    u = [sum(t*c for t, c in zip(row, cy)) for row in a]
    v = [sum(t*c for t, c in zip(row, cx)) for row in a]
    calls = 0
    original = asyncio.CancelledError('cancel residual pass')

    def check():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise original

    with native.cancellation_scope(check):
        with pytest.raises(asyncio.CancelledError) as caught:
            native.covariance_polynomial(*values, scale, a, d, u, v)
    assert caught.value is original
    assert calls == 3


def test_native_ar_polynomial_certification_obeys_same_owner_callback():
    native = _native()
    from workbench.checks.ar_polynomials import certify_set
    original = asyncio.CancelledError('cancel exact root isolation')
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        if calls == 12:
            raise original

    with native.cancellation_scope(check):
        with pytest.raises(asyncio.CancelledError) as caught:
            certify_set([-2, 0, 1], [1])
    assert caught.value is original
    assert calls == 12


def test_native_ar_http_abort_stops_real_bound_workflow_before_artifact(tmp_path, monkeypatch, record_property):
    """Actual HTTP abort → AgentCore → lifecycle → to_thread → native kernel."""
    native = _native()
    import json
    import sys
    import httpx
    from fastapi import FastAPI
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.orchestrator import WorkbenchOrchestrator
    from workbench.agent.session import JsonlSessionRepository
    from workbench.agent.chains import ChainStore
    from workbench.agent.turn_runtime import turn_registry, active_turn_key
    from workbench.agent.workflow import WorkflowStateStore
    from workbench.http.agent_turn_routes import router
    from workbench.checks import ar_verified
    from tests.test_agent_completion_iv import build_products
    from tests.operation_request_fixtures import admit_proposal

    class IdleAdapter:
        async def stream(self, request):
            pytest.fail('offline abort test must never call a provider')
            yield

    project, contract, _ = build_products(tmp_path/'project')
    run_id = contract['source']['run_id']
    run = project/'runs'/run_id
    index_before = (run/'artifacts_index.json').read_bytes()
    repository = JsonlSessionRepository(project/'workbench')
    repository.create_session('native-ar-cancel', chain_id='ar-chain', role='chain')
    events = AgentEventStream(repository.root)
    core = AgentCore(repository, events, IdleAdapter(), session_id='native-ar-cancel')
    orchestrator = WorkbenchOrchestrator(repository, events, main_session_id='native-ar-cancel')
    orchestrator.register_chain('ar-chain', 'native-ar-cancel', core)
    ChainStore(repository.root).create_root(chain_id='ar-chain', run_family_id='iv-ar',
        active_head_run_id=run_id, agent_session_id='native-ar-cancel')
    fingerprint = 'native-ar-offline-cancellation'
    proposal = admit_proposal(orchestrator, chain_id='ar-chain', operation_id='operation.multi_step',
        target={'run_id': run_id, 'node_ref': 'stage:cleaned', 'artifact_id': 'cleaned_dataset'},
        preconditions={'context_version': 'node-operation-context/v1', 'owner_resolution': 'single_candidate',
            'context_fingerprint': fingerprint, 'active_head_run_id': run_id},
        changes={'steps': [{'step_id': 'ar', 'operation_id': 'iv.ar_confidence',
            'spec': {'model_run_id': run_id, 'model_ref': 'iv_2sls_1'}},
            {'step_id': 'report', 'operation_id': 'report.compose', 'depends_on': ['ar'],
             'spec': {'result_refs': [{'run_id': run_id, 'artifact_id': 'iv_2sls_1', 'role': 'primary'}]}}]},
        evidence_refs=[], expected_effect=['compute explicitly requested AR'], risks=[])
    record = orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
        fingerprint=proposal.fingerprint, actor_type='user',
        current_context_fingerprint=fingerprint, current_active_head_run_id=run_id)
    entered_native = threading.Event()
    release_native = threading.Event()

    def at_native_checkpoint():
        # Synchronize inside the real native buffer call, without replacing
        # the mathematical engine or the workflow/operation/HTTP handlers.
        frame = sys._getframe(1)
        while frame is not None:
            if frame.f_code.co_name == 'sufficient_statistics' and frame.f_code.co_filename == native.__file__:
                entered_native.set()
                assert release_native.wait(5)
                break
            frame = frame.f_back

    def force_exact(*args):
        raise ar_verified.VerificationUncertain('offline native cancellation exercise')

    monkeypatch.setattr(ar_verified, 'verify_polynomials', force_exact)
    app = FastAPI()
    app.include_router(router)

    async def scenario():
        with native.cancellation_scope(at_native_checkpoint):
            task = asyncio.create_task(orchestrator.execute_confirmed_operation(record.record_id,
                project_root=project, current_context_fingerprint=fingerprint, current_active_head_run_id=run_id))
        core.phase = 'tools'
        core._active_tool_task = task
        key = active_turn_key(project, core.session_id)
        turn_registry.activate(key, core)
        try:
            assert await asyncio.to_thread(entered_native.wait, 5), 'bound workflow did not enter the real C++ kernel'
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://offline') as client:
                before = time.monotonic()
                response = await client.post(f'/agent/sessions/{core.session_id}/abort', params={'project_root': str(project)})
                assert response.status_code == 200, response.text
                assert response.json()['status'] == 'cancelling'
                http_seconds = time.monotonic()-before
                record_property('http_abort_seconds', http_seconds)
                assert http_seconds < 1
            before = time.monotonic()
            release_native.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), 2)
            drain_seconds = time.monotonic()-before
            record_property('http_abort_to_real_worker_drained_seconds', drain_seconds)
            assert drain_seconds < 2
            cancelled = orchestrator.operation_store.get(record.record_id)
            assert cancelled.status == 'cancelled'
            state = WorkflowStateStore(project, f'workflow_{record.record_id}').current()
            assert state.status == 'cancelled'
            assert state.steps['ar'].status == 'cancelled'
            assert state.steps['report'].status == 'cancelled'
            assert state.steps['report'].error == 'workflow_cancelled_before_execution'
            assert not state.steps['ar'].artifact_ids
            children = [child for child in orchestrator.operation_store.list_records()
                        if child.operation_id == 'iv.ar_confidence']
            assert children and all(child.status == 'cancelled' for child in children)
            reports = [child for child in orchestrator.operation_store.list_records()
                       if child.operation_id == 'report.compose']
            assert reports and all(child.status == 'cancelled' and child.outputs['execution_status'] == 'not_executed'
                                   for child in reports)
            assert (run/'artifacts_index.json').read_bytes() == index_before
            leases = list((repository.root/'operation-records/chain-leases').glob('*.json'))
            assert leases and all(json.loads(path.read_text())['status'] == 'released' for path in leases)
        finally:
            release_native.set()
            await asyncio.gather(task, return_exceptions=True)
            turn_registry.deactivate(key, core)

    asyncio.run(scenario())


def test_native_ar_cancel_at_existing_persist_entry_publishes_no_artifact(tmp_path, monkeypatch):
    native = _native()
    from workbench.agent.workflow import execute_workflow, WorkflowStateStore
    from workbench.services import iv_ar
    from tests.test_agent_completion_iv import build_products
    from tests.test_agent_iv_ar_operation import ar_workflow
    project, contract, _ = build_products(tmp_path/'persist-entry')
    run = project/'runs'/contract['source']['run_id']
    before = (run/'artifacts_index.json').read_bytes()
    original_compute = iv_ar.compute_ar
    cancelled = threading.Event()
    original_error = asyncio.CancelledError('cancel before supplement publication')

    def check():
        if cancelled.is_set():
            raise original_error

    def compute_then_request_cancel(*args, **kwargs):
        result = original_compute(*args, **kwargs)
        cancelled.set()
        return result

    # Inject the cancellation at the already existing compute→persist seam;
    # the real fit, verification, mathematics and persistence code are used.
    monkeypatch.setattr(iv_ar, 'compute_ar', compute_then_request_cancel)
    draft = ar_workflow(project, contract, name='cancel-at-persist-entry')
    with native.cancellation_scope(check):
        with pytest.raises(asyncio.CancelledError) as caught:
            execute_workflow(project, draft)
    assert caught.value is original_error
    state = WorkflowStateStore(project, draft.workflow_id).current()
    assert state.status == 'cancelled' and not state.steps['ar'].artifact_ids
    assert (run/'artifacts_index.json').read_bytes() == before


def test_native_ar_actual_bound_service_publishes_exact_native_evidence(tmp_path, monkeypatch, record_property):
    """Successful compute_ar integration is separate from component timings."""
    native = _native()
    import hashlib
    import json
    from workbench.agent.workflow import execute_workflow
    from workbench.checks import ar_confidence as ar, ar_verified
    from workbench.checks.ar_polynomials import certify_set
    from tests.test_agent_completion_iv import build_products
    from tests.test_agent_iv_ar_operation import ar_workflow
    project, contract, _ = build_products(tmp_path/'native-service')
    original_native = native.robust_polynomials
    observed = []

    def calculate_and_compare(*args):
        actual = original_native(*args)
        expected = ar.robust_polynomials_reference(*args)
        assert actual == expected
        observed.append(actual)
        return actual

    def force_exact(*args):
        raise ar_verified.VerificationUncertain('offline integration of exact native fallback')

    monkeypatch.setattr(native, 'robust_polynomials', calculate_and_compare)
    monkeypatch.setattr(ar_verified, 'verify_polynomials', force_exact)
    draft = ar_workflow(project, contract, name='real-bound-native-success')
    state = execute_workflow(project, draft)
    assert state.status == 'completed'
    assert len(observed) == 1
    run = project/'runs'/contract['source']['run_id']
    artifact_id, = state.steps['ar'].artifact_ids
    index = json.loads((run/'artifacts_index.json').read_text())
    entry = next(item for item in index['artifacts'] if item['artifact_id'] == artifact_id)
    result = json.loads((run/entry['path']).read_text())['result']['anderson_rubin_95']
    assert result['computation']['engine'] == 'native_cpp_exact'
    assert result['computation']['engine_abi'] == 2
    assert result['computation']['certification_target'] == 'original_binary64_observations'
    oracle = certify_set(*observed[0])
    assert result['global_certification'] == oracle['global_certification']
    assert result['components'] == oracle['components']
    record_property('actual_service_exact_polynomial_sha256', hashlib.sha256(json.dumps(observed[0]).encode()).hexdigest())
