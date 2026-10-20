"""Restore conversation and lineage as a new branch; retain the old evidence."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from uuid import uuid4

from ..canonical import sha256_canonical
from .chains import ChainStore
from .execution import ChainExecutionLease
from .operations import OperationRecordStore
from .plans import Plan, PlanStore
from .proposals import ProposalStore
from .session import EntryRef
from .turn_store import TurnStore


class AnalysisHistoryError(ValueError):
    """A branch cannot be restored without conflicting with live work."""


def require_active_session(repository, session_id):
    metadata = repository.get_metadata(session_id)
    leaf = repository.get_entry(EntryRef(session_id,metadata['leaf_entry_id'])) if metadata.get('leaf_entry_id') else None
    if metadata.get('analysis_rewind') or metadata.get('status') == 'restoring' or leaf and leaf.entry_type == 'analysis_rewind_intent':
        raise AnalysisHistoryError('This analysis was rewound; continue from its restored branch or finish the pending restore.')


def capture_checkpoint(repository, session_id, command_id):
    require_active_session(repository, session_id)
    branch = repository.get_branch(session_id)
    existing = next((e for e in branch if e.entry_type == 'analysis_checkpoint'
                     and e.payload['command_id'] == command_id), None)
    if existing:
        return existing
    metadata = repository.get_metadata(session_id)
    chain = next((record for record in ChainStore(repository.root, create=False).list_records()
                  if record['chain_id'] == metadata['chain_id']), None)
    focus = next(((e.payload.get('metadata') or {}).get('focus') for e in reversed(branch)
                  if e.entry_type == 'custom_message' and e.payload.get('name') == 'workbench_agent_focus'), None)
    plan = PlanStore(repository.root).current(session_id)
    before = EntryRef(branch[-1].session_id, branch[-1].entry_id).to_dict() if branch else None
    return repository.append_once(session_id,'analysis_checkpoint',{
        'command_id':command_id, 'session_id':session_id, 'role':metadata['role'],
        'before':before,
        'lineage':chain, 'focus':focus, 'plan':plan.to_dict() if plan else None,
        'execution_mode':metadata.get('execution_mode','ask'),
        'permission_grants':metadata.get('permission_grants',[]),
    },key=command_id,stage='analysis_checkpoint')


def _selection(repository, session_id, entry_id):
    branch = repository.get_branch(session_id)
    entry = next((e for e in branch if e.entry_id == entry_id and e.entry_type == 'message'), None)
    if entry is None or entry.payload.get('role') != 'user':
        raise AnalysisHistoryError('Choose one of your messages on this conversation branch.')
    checkpoint = next((e for e in reversed(branch[:branch.index(entry)]) if e.entry_type == 'analysis_checkpoint'
        and e.payload['command_id'] == entry.payload.get('command_id')), None)
    if checkpoint is None:
        raise AnalysisHistoryError('This older turn has no joint lineage checkpoint. Its history remains available; no analysis state was changed.')
    before = EntryRef.from_dict(checkpoint.payload['before']) if checkpoint.payload['before'] else None
    index = next(i for i,e in enumerate(branch) if e.entry_id == before.entry_id and e.session_id == before.session_id) if before else -1
    removed = branch[index+1:]
    return branch, checkpoint, removed


def rewind_analysis(repository, session_id, entry_id):
    """Explicit, resumable undo. No fit, provider call, deletion or raw-data edit."""
    metadata = repository.get_metadata(session_id)
    saved = metadata.get('analysis_rewind')
    if not saved:
        pending = next((e for e in repository.get_branch(session_id) if e.entry_type == 'analysis_rewind_intent'
            and e.payload['entry_id'] == entry_id), None)
        if pending:
            saved = EntryRef(pending.session_id,pending.entry_id).to_dict()
    if saved:
        intent = repository.get_entry(EntryRef.from_dict(saved)).payload
        if intent['entry_id'] != entry_id:
            raise AnalysisHistoryError('Use the restored branch before undoing another analysis.')
        sessions = intent['retired_sessions']
    else:
        branch, checkpoint, removed = _selection(repository,session_id,entry_id)
        sessions = sorted({session_id, *(e.session_id for e in removed)})
    store = TurnStore(repository.root.parent)
    with ExitStack() as held:
        for sid in sessions:
            held.enter_context(store.execution_guard(sid))
        active = [record for record in store.list_active() if record.session_id in sessions]
        if any(record.status != 'awaiting_approval' for record in active):
            raise AnalysisHistoryError('Stop or reconcile the unfinished execution before undoing this analysis.')
        chains = ChainStore(repository.root, create=False)
        chain_ids = {repository.get_metadata(sid)['chain_id'] for sid in sessions}
        for chain in chains.list_records():
            if (chain['chain_id'] in chain_ids or chain.get('agent_session_id') in sessions
                    or chain.get('child_session_id') in sessions):
                lease = ChainExecutionLease(repository.root, chain_id=chain['chain_id'],
                    active_head_run_id=chain['active_head_run_id'], execution_key='analysis-rewind:'+uuid4().hex)
                lease.acquire()
                held.callback(lease.release)
        if any(record.agent_session_id in sessions and record.status not in {'completed','failed','cancelled','stale'}
               for record in OperationRecordStore(repository.root,create=False).list_records()):
            raise AnalysisHistoryError('An approved operation still needs cancellation or reconciliation before undo.')
        if saved:
            return _restore(repository,intent,EntryRef.from_dict(saved))
        # Re-read under the same OS ownership used by all Agent turns.
        branch, checkpoint, removed = _selection(repository,session_id,entry_id)
        branch_refs = {(e.session_id,e.entry_id) for e in branch}
        for sid in sessions:
            current = repository.get_metadata(sid)
            if current.get('leaf_entry_id') and (sid,current['leaf_entry_id']) not in branch_refs:
                raise AnalysisHistoryError('A parent conversation changed on another branch; restore from that conversation without overwriting its newer work.')
        token = sha256_canonical([session_id,entry_id,checkpoint.entry_id])[:32]
        snapshot = checkpoint.payload
        prompt = next(e.payload['content'] for e in removed if e.entry_type == 'message' and e.payload.get('role') == 'user')
        result = {'session_id':'agent_restored_'+token, 'restored_prompt':prompt,
            'lineage':{'run_id':(snapshot['lineage'] or {}).get('active_head_run_id'), 'focus':snapshot['focus']}}
        intent = {'entry_id':entry_id,'source_session_id':session_id,'checkpoint':snapshot,
            'checkpoint_ref':EntryRef(checkpoint.session_id,checkpoint.entry_id).to_dict(),
            'retired_sessions':sessions,'result':result,'chain_id':'chain_restored_'+token,
            'chapters':metadata.get('chapters',[]),
            'decline_proposals':[p.proposal_id for sid in sessions
                for p in ProposalStore(repository.root,create=False).latest_revisions_for_session(sid)
                if ProposalStore(repository.root,create=False).latest_status(p.proposal_id)=='pending'],
            'awaiting_turns':[record.turn_id for record in active]}
        recorded = repository.append_once(session_id,'analysis_rewind_intent',intent,key=token,stage='analysis_rewind_intent')
        return _restore(repository,intent,EntryRef(session_id,recorded.entry_id))


def _restore(repository, intent, intent_ref):
    snapshot, result = intent['checkpoint'], intent['result']
    new_session = result['session_id']
    metadata = {m['session_id']:m for m in repository.list_metadata()}
    if new_session in metadata and metadata[new_session]['status'] == 'idle':
        return result
    for sid in intent['retired_sessions']:
        repository.update_metadata(sid,analysis_rewind=intent_ref.to_dict())
        repository.update_status(sid,'rewinding')
    source = snapshot['lineage']
    chain_id = intent['chain_id'] if source else repository.get_metadata(snapshot['session_id'])['chain_id']
    if new_session not in metadata:
        repository.create_session(new_session,chain_id=chain_id,role=snapshot['role'],status='restoring',
            inherited_parent_ref=EntryRef.from_dict(snapshot['before']) if snapshot['before'] else None)
    repository.update_status(new_session,'restoring')
    if source:
        chains = ChainStore(repository.root)
        try:
            chains.get(chain_id)
        except KeyError:
            chains.create_root(chain_id=chain_id,run_family_id=source['run_family_id'],
                active_head_run_id=source['active_head_run_id'],agent_session_id=new_session)
    plans = PlanStore(repository.root)
    if snapshot['plan'] is not None and plans.current(new_session) is None:
        restored = replace(Plan.from_dict(snapshot['plan']),status='draft',approved_at=None,approved_version=None)
        plans.save(new_session,restored)
    repository.update_metadata(new_session,permission_grants=snapshot['permission_grants'],execution_mode=snapshot['execution_mode'])
    on_branch = {e.entry_id for e in repository.get_branch(new_session)}
    repository.set_chapters(new_session,[c for c in intent['chapters'] if c['entry_id'] in on_branch])
    proposals = ProposalStore(repository.root,create=False)
    for proposal in intent['decline_proposals']:
        if proposals.latest_status(proposal)=='pending':
            proposals.decline(proposal,actor_type='human_ui',reason='The analysis branch was undone.')
    turns = TurnStore(repository.root.parent)
    for turn_id in intent['awaiting_turns']:
        record = turns.get(turn_id)
        if record.status=='awaiting_approval':
            record = turns.claim(turn_id,expected_version=record.version,owner='analysis-rewind',lease_seconds=60)
            turns.transition(turn_id,status='cancelled',expected_version=record.version,
                owner=record.lease_owner,fence=record.lease_epoch)
    repository.append_once(new_session,'analysis_restore',{
        'source_session_id':intent['source_session_id'],'checkpoint_ref':intent['checkpoint_ref'],
        'lineage':result['lineage'],'prior_plan_approval_restored':False,
    },key=intent['entry_id'],stage='analysis_restore')
    for sid in intent['retired_sessions']:
        repository.update_status(sid,'rewound')
    repository.update_status(new_session,'idle')
    return result
