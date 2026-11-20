"""Context skips irrelevant payload decoding without changing the resolved branch."""
import json
import os

import pytest

from workbench.agent import session as session_module
from workbench.agent.context import ContextBuilder
from workbench.agent.session import EntryRef, JsonlSessionRepository

CONTEXT_TYPES = frozenset({'message', 'custom_message', 'compaction'})


class FullPayloadRepository:
    """Reference: the pre-optimization complete-branch reader."""

    def __init__(self, repository):
        self.repository = repository

    def get_branch(self, session_id, *, leaf_entry_id=None, **unused):
        return self.repository.get_branch(session_id, leaf_entry_id=leaf_entry_id)


def repository(tmp_path):
    repo = JsonlSessionRepository(tmp_path / 'workbench')
    repo.create_session('s', chain_id='c', role='chain')
    return repo


def same_snapshot(repo, session_id='s', **kwargs):
    expected = ContextBuilder(FullPayloadRepository(repo)).build(session_id, **kwargs)
    actual = ContextBuilder(repo).build(session_id, **kwargs)
    assert actual == expected
    return actual


def replace_rows(repo, edit):
    path = repo.sessions_dir / 's.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    edit(rows)
    temporary = path.with_suffix('.replacement')
    temporary.write_text(''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows))
    os.replace(temporary, path)


def test_context_does_not_redecode_discarded_payloads_but_full_reader_still_does(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    repo.append('s', 'message', {'role': 'user', 'content': 'question'})
    for entry_type in ['turn_state', 'turn_input', 'tool_intent', 'tool_receipt', 'analysis_checkpoint']:
        repo.append('s', entry_type, {'opaque': 'DO_NOT_REDECODE_DISCARDED_PAYLOAD' * 128})
    repo.append('s', 'custom_message', {'name': 'workbench_agent_protocol', 'content': 'protocol'})
    expected = ContextBuilder(FullPayloadRepository(repo)).build('s')
    session_module._log_index(repo.sessions_dir / 's.jsonl')
    original, parsed = session_module.json.loads, []

    def loads(raw, *args, **kwargs):
        if isinstance(raw, str) and 'DO_NOT_REDECODE_DISCARDED_PAYLOAD' in raw:
            parsed.append(raw)
        return original(raw, *args, **kwargs)

    monkeypatch.setattr(session_module.json, 'loads', loads)
    assert ContextBuilder(repo).build('s') == expected
    assert ContextBuilder(repo).build('s') == expected
    assert parsed == [], 'ContextBuilder decoded payloads it never reads'
    full = repo.get_branch('s')
    assert len(parsed) == 5
    assert full[1].payload['opaque'].startswith('DO_NOT_REDECODE')


@pytest.mark.parametrize('anchor', ['audit', 'message', 'missing'])
@pytest.mark.parametrize('verified', [True, False])
def test_all_positions_keep_compaction_anchor_fallback_and_failed_message_contract(tmp_path, anchor, verified):
    repo = repository(tmp_path)
    repo.append('s', 'custom_message', {'name': 'workbench_agent_protocol', 'content': 'old protocol'})
    repo.append('s', 'message', {'role': 'user', 'content': 'earlier'})
    audit = repo.append('s', 'turn_state', {'large': 'not a message'})
    message = repo.append('s', 'message', {'role': 'user', 'content': 'kept'})
    repo.append('s', 'message', {'role': 'assistant', 'content': 'failed answer', 'stop_reason': 'error'})
    repo.append('s', 'custom_message', {'name': 'workbench_agent_protocol', 'content': 'new protocol'})
    first_kept = {'audit': audit.entry_id, 'message': message.entry_id, 'missing': 'missing'}[anchor]
    repo.append('s', 'compaction', {'summary': 'summary', 'first_kept_entry_id': first_kept, 'verified': verified})
    repo.append('s', 'message', {'role': 'assistant', 'content': 'after compaction'})
    for include_failed in [False, True]:
        snapshot = same_snapshot(repo, include_failed_assistant_messages=include_failed,
            workbench_context={'analysis': {'value': 1.0}})
        assert snapshot.messages[0]['content'] == 'new protocol'
    full = repo.get_branch('s')
    selective = repo.get_branch('s', payload_entry_types=CONTEXT_TYPES)
    assert [entry.entry_id for entry in selective] == [entry.entry_id for entry in full]
    assert [entry.parent_ref for entry in selective] == [entry.parent_ref for entry in full]
    assert next(entry for entry in selective if entry.entry_id == audit.entry_id).payload == {}
    assert next(entry for entry in full if entry.entry_id == audit.entry_id).payload == {'large': 'not a message'}


def test_header_validation_occurs_once_per_index_version_without_sharing_mutable_fields(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    audit = repo.append_once('s', 'turn_state', {'discarded': {'nested': [1]}}, key='audit-key', stage='state')
    repo.append('s', 'message', {'role': 'assistant', 'content': '',
        'tool_calls': [{'id': 'call', 'function': {'arguments': '{}'}}]})
    session_module._log_index(repo.sessions_dir / 's.jsonl')
    original, checks = session_module._identity_from, []

    def validate(value):
        if value.get('key') == 'audit-key':
            checks.append(value['key'])
        return original(value)

    monkeypatch.setattr(session_module, '_identity_from', validate)
    one = repo.get_branch('s', payload_entry_types=CONTEXT_TYPES)
    entry = next(entry for entry in one if entry.entry_id == audit.entry_id)
    entry.idempotency['key'] = 'caller mutation'
    entry.payload['injected'] = True
    one[-1].payload['tool_calls'][0]['function']['arguments'] = 'caller mutation'
    two = repo.get_branch('s', payload_entry_types=CONTEXT_TYPES)
    entry = next(entry for entry in two if entry.entry_id == audit.entry_id)
    assert entry.idempotency['key'] == 'audit-key' and entry.payload == {}
    assert two[-1].payload['tool_calls'][0]['function']['arguments'] == '{}'
    assert checks == ['audit-key']
    repo.append('s', 'turn_input', {'discarded': 'new tail'})
    repo.get_branch('s', payload_entry_types=CONTEXT_TYPES)
    assert checks == ['audit-key'], 'unchanged prefix headers need no revalidation after append'


@pytest.mark.parametrize('damage', ['created_at', 'idempotency', 'payload'])
def test_ignored_entries_do_not_hide_bad_headers_or_non_object_payloads(tmp_path, damage):
    repo = repository(tmp_path)
    repo.append_once('s', 'turn_state', {'discarded': 'large'}, key='key', stage='stage')
    repo.append('s', 'message', {'role': 'user', 'content': 'question'})

    def damage_row(rows):
        if damage == 'created_at':
            del rows[0]['created_at']
        elif damage == 'idempotency':
            rows[0]['idempotency']['payload_sha256'] = 'bad'
        else:
            rows[0]['payload'] = 123

    replace_rows(repo, damage_row)
    with pytest.raises((KeyError, ValueError, TypeError)) as expected:
        ContextBuilder(FullPayloadRepository(repo)).build('s')
    with pytest.raises(type(expected.value)) as actual:
        ContextBuilder(repo).build('s')
    assert str(actual.value) == str(expected.value)


def test_non_object_payload_preserves_legacy_conversion_instead_of_silent_emptying(tmp_path):
    repo = repository(tmp_path)
    repo.append('s', 'turn_state', {'unused': 'old'})
    repo.append('s', 'message', {'role': 'user', 'content': 'question'})
    replace_rows(repo, lambda rows: rows[0].update(payload=[['legacy', 'value']]))
    branch = repo.get_branch('s', payload_entry_types=CONTEXT_TYPES)
    assert branch[0].payload == {'legacy': 'value'}
    same_snapshot(repo)


def test_fork_rewind_last_duplicate_and_external_replacement_remain_visible(tmp_path):
    repo = repository(tmp_path)
    first = repo.append('s', 'message', {'role': 'user', 'content': 'first'})
    orphan = repo.append('s', 'turn_state', {'discarded': 'orphan'})
    repo.rewind('s', EntryRef('s', first.entry_id))
    kept = repo.append('s', 'message', {'role': 'assistant', 'content': 'old text'})
    repo.create_session('fork', chain_id='c', role='chain', inherited_parent_ref=EntryRef('s', kept.entry_id))
    repo.append('fork', 'turn_input', {'discarded': 'fork audit'})
    repo.append('fork', 'message', {'role': 'user', 'content': 'fork question'})
    same_snapshot(repo, 'fork')

    def replace_and_duplicate(rows):
        # An invalid orphan was never materialized by get_branch. It must not
        # become an eager global validation error in the optimized reader.
        next(row for row in rows if row['entry_id'] == orphan.entry_id).pop('created_at')
        duplicate = dict(next(row for row in rows if row['entry_id'] == kept.entry_id))
        duplicate['payload'] = {'role': 'assistant', 'content': 'new text'}
        rows.append(duplicate)

    replace_rows(repo, replace_and_duplicate)
    snapshot = same_snapshot(repo, 'fork')
    assert 'new text' in [message['content'] for message in snapshot.messages]
    assert 'old text' not in [message['content'] for message in snapshot.messages]
    assert orphan.entry_id not in snapshot.source_entry_ids


def test_invalid_json_remains_a_hard_error_at_the_existing_index_boundary(tmp_path):
    repo = repository(tmp_path)
    repo.append('s', 'message', {'role': 'user', 'content': 'question'})
    path = repo.sessions_dir / 's.jsonl'
    path.write_text(path.read_text() + '{broken json}\n')
    with pytest.raises(json.JSONDecodeError):
        ContextBuilder(repo).build('s')
