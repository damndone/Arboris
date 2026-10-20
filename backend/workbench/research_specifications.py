"""Exact before-results specification evidence; it never grants execution authority."""
from datetime import UTC, datetime
import json
import os
from pathlib import Path

from . import analysis_ledger
from .canonical import sha256_canonical
from .jsonl_store import _exclusive_jsonl_lock
from .services.research_history import result_history


def _steps(record):
    return record.changes['steps'] if record.operation_id == 'operation.multi_step' else [
        {'step_id':record.operation_id,'operation_id':record.operation_id}]


def _exploratory(record, reason):
    return {'specification_status':'exploratory','verification':'unverified','reason':reason,
            'question_id':None,'step_ids':[s['step_id'] for s in _steps(record)]}


def freeze_operation(root, record, plan, *, first_dispatch):
    """Called under the common domain lease, before any effect is prepared.

    The immutable operation request fixes every member of a multi-step set.
    A plan containing operation names alone is insufficient. Historical work
    is never retroactively certified. The append-only ledger survives undo.
    """
    root = Path(root)
    path = analysis_ledger.ledger_path(root)
    key = sha256_canonical(['research-specification.v1',record.record_id])
    with analysis_ledger._LOCK, _exclusive_jsonl_lock(path):
        raw = path.read_text(encoding='utf-8') if path.exists() else ''
        if raw and not raw.endswith('\n'):
            raise ValueError('Incomplete research ledger needs reconciliation before analysis.')
        entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
        prior = next((entry for entry in entries if entry.get('event_id') == key), None)
        if prior is not None:
            if (prior['proposal_fingerprint'] != record.proposal_fingerprint
                    or prior['proposal_revision'] != record.proposal_revision):
                raise ValueError('Frozen research specification differs from the execution request.')
            return prior['research_specification']
        if not first_dispatch:
            return _exploratory(record,'missing_pre_execution_snapshot')
        if plan is None or plan.status not in {'approved','completed'} or plan.approved_version is None:
            return _exploratory(record,'criteria_not_fixed')
        criteria = next((entry for entry in entries if entry.get('event_type') == 'criteria_fixed'
            and entry.get('session_id') == record.agent_session_id and entry.get('plan_id') == plan.plan_id
            and entry.get('plan_version') == plan.approved_version), None)
        if criteria is None or criteria['plan_snapshot']['question'] != plan.question or criteria['plan_snapshot']['criteria'] != list(plan.criteria):
            return _exploratory(record,'criteria_approval_unverified')
        history = result_history(root,record.target.get('run_id'))
        source = history['source_upload_sha256']
        recorded_results = [entry for entry in entries if source is not None
            and entry.get('source_upload_sha256') == source
            and any(step.get('category') in {'model','inferential','descriptive'} for step in entry.get('steps',[]))]
        changed_question = any(entry.get('event_type') == 'question_change' and entry.get('plan_id') == plan.plan_id
                               for entry in entries)
        reason = ('question_changed' if changed_question else
                  'source_history_unverified' if not history['verified'] else
                  'prior_result_on_same_original_data' if history['prior_results'] or recorded_results else
                  'fixed_before_related_results')
        status = 'pre_specified' if reason == 'fixed_before_related_results' else 'exploratory'
        exact = {'operation_id':record.operation_id,'operation_version':record.operation_version,
                 'target':record.target,'preconditions':record.preconditions,'changes':record.changes,
                 'question':plan.question,'criteria':list(plan.criteria)}
        proof = {'specification_status':status,'verification':('verified' if status=='pre_specified' else
                                 'unverified' if reason=='source_history_unverified' else 'not_prespecified'),
                 'reason':reason,'question_id':plan.plan_id,'criteria_event_id':criteria['event_id'],
                 'specification_event_id':key,'exact_specification_sha256':sha256_canonical(exact),
                 'source_upload_sha256':source,'step_ids':[step['step_id'] for step in _steps(record)]}
        event = {'record_type':'research_specification','event_type':'specification_status','event_id':key,
                 'session_id':record.agent_session_id,'plan_id':plan.plan_id,'plan_version':plan.approved_version,
                 'actor':'system','authorized_by':'user','source':'operation.before_effect','status':'completed',
                 'steps':[],'inferential_steps':0,'changes_data':False,
                 'run_id':record.target.get('run_id'),'source_upload_sha256':source,
                 'proposal_id':record.proposal_id,'proposal_revision':record.proposal_revision,
                 'proposal_fingerprint':record.proposal_fingerprint,'criteria_event_id':criteria['event_id'],
                 'research_specification':proof,'prior_results':history['prior_results'],
                 'at':datetime.now(UTC).isoformat(timespec='milliseconds')}
        with path.open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(event,ensure_ascii=False,sort_keys=True)+'\n')
            handle.flush()
            os.fsync(handle.fileno())
        return proof
