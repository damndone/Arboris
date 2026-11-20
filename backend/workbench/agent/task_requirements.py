"""Server-owned delivery constraints, bound to real user messages, not plan prose.

Only binding/migration reads the session. Completion and reviewer packets consume
the bounded persisted record; ordinary follow-ups can add but cannot remove it.
"""
from __future__ import annotations

from copy import deepcopy
import re

from ..canonical import sha256_canonical
from .completion_targets import requested_outcomes, requested_targets, requested_targets_unbound
from .session import EntryRef

VERSION = 'agent.task-requirements/v1'
FULL_ANALYSIS = re.compile(r'完整分析|全部分析|全面分析|(?:full|complete|entire|end.to.end)\s+analysis', re.I)
#: The person asked for the work to be finished or handed over, not only for an answer.
FINISH_REQUEST = re.compile(
    r'请完成|做完|做出来|完成(?:这|此|该|全部|分析|任务)'
    r'|\b(?:finish|complete)\s+(?:this|the|it|all|everything)\b|\bget\s+(?:this|it)\s+done\b', re.I)
_QUOTED_TEXT = re.compile(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」|『[^』\n]*』|`[^`\n]*`')
_NEGATED_FINISH = re.compile(r"(?:\b(?:do\s+not|don['’]t|never|not)|不要|不用|无需|不必|不需要|别)\s*$", re.I)
CONTINUATION = re.compile(r'^(?:continue|resume|go on|proceed|ok|okay|yes|继续|接着|好的|确认)[.!。！\s]*$', re.I)


def asks_to_finish(text: str) -> bool:
    """Recognize an explicit completion request outside quotations."""
    request = _QUOTED_TEXT.sub(" ", text)
    return any(not _NEGATED_FINISH.search(request[:match.start()]) for match in FINISH_REQUEST.finditer(request))


def _empty():
    return {'version': VERSION, 'status': 'unverified', 'scope': 'question',
            'estimands': [], 'target_bindings': [], 'sources': [], 'cursor': None,
            'request_chain_sha256': None, 'latest_request': None}


def _valid(value):
    return (isinstance(value, dict) and value.get('version') == VERSION
            and value.get('status') in {'verified', 'unverified'}
            and value.get('scope') in {'question', 'analysis'}
            and isinstance(value.get('estimands'), list)
            and set(value['estimands']) <= {'ATT', 'ATC', 'ATE'}
            and isinstance(value.get('target_bindings', []), list)
            and all(isinstance(target, dict) and target.keys() == {'estimand', 'outcome', 'treatment'}
                    and target['estimand'] in value['estimands']
                    and isinstance(target['outcome'], str) and 0 < len(target['outcome']) <= 200
                    and (target['treatment'] is None or isinstance(target['treatment'], str)
                         and 0 < len(target['treatment']) <= 200)
                    for target in value.get('target_bindings', []))
            and isinstance(value.get('sources'), list) and len(value['sources']) <= 8
            and (value['status'] != 'verified' or (bool(value['sources'])
                 and isinstance(value.get('request_chain_sha256'), str)
                 and len(value['request_chain_sha256']) == 64
                 and isinstance(value.get('latest_request'), dict))))


def signature(value):
    """Cursor-only advances do not create another persisted plan snapshot."""
    return sha256_canonical({k: v for k, v in (value or {}).items()
                             if k != 'cursor' and (k != 'target_bindings' or v)})


def _leaf(repository, session_id):
    metadata = repository.get_metadata(session_id)
    leaf = metadata.get('leaf_entry_id')
    return ({'session_id': session_id, 'entry_id': leaf} if leaf
            else metadata.get('inherited_parent_ref'))


class RequirementBinder:
    def __init__(self, repository):
        self.repository = repository
        self.cache = {}

    def bind(self, session_id, previous):
        value = deepcopy(previous) if _valid(previous) else _empty()
        cached = self.cache.get(session_id)
        if cached and signature(cached) == signature(value):
            value = deepcopy(cached)
        if 'target_bindings' not in value:
            # Old user-only snapshots did not track when outcomes changed.
            # Replay those causal requests once; keep human revisions authoritative.
            if value['estimands'] and all(isinstance(source, dict) and source.get('kind') == 'user_message'
                                          for source in value['sources']):
                value = _empty()
            else:
                value['target_bindings'] = []
        head = _leaf(self.repository, session_id)
        current, pending, visited = head, [], set()
        stop = value.get('cursor')
        while current is not None and current != stop:
            key = (current['session_id'], current['entry_id'])
            if key in visited:
                raise ValueError('cycle in task requirement provenance')
            visited.add(key)
            entry = self.repository.get_entry(EntryRef.from_dict(current))
            pending.append(entry)
            current = entry.parent_ref.to_dict() if entry.parent_ref else None
        if stop is not None and current != stop:
            # A rewind must never reuse constraints from another branch.
            value = _empty()
        for entry in reversed(pending):
            if entry.entry_type != 'message' or entry.payload.get('role') != 'user':
                continue
            text = entry.payload.get('content')
            if not isinstance(text, str) or not text.strip() or CONTINUATION.fullmatch(text.strip()) or text.lstrip().startswith('/'):
                continue
            scope = 'analysis' if FULL_ANALYSIS.search(text) else value['scope']
            estimands = sorted(set(value['estimands']) | requested_targets(text))
            bindings = list(value['target_bindings'])
            for target in requested_outcomes(text):
                if target not in bindings:
                    bindings.append(target)
            provenance = {'kind': 'user_message', 'session_id': entry.session_id,
                'entry_id': entry.entry_id, 'sha256': sha256_canonical(text)}
            # A changed question can keep the same scope/estimand vocabulary.
            # Track all substantive user inputs without retaining their text.
            value['request_chain_sha256'] = sha256_canonical([value['request_chain_sha256'], provenance])
            value['latest_request'] = provenance
            if (value['status'] == 'verified' and scope == value['scope']
                    and estimands == value['estimands'] and bindings == value['target_bindings']):
                continue
            value.update(status='verified', scope=scope, estimands=estimands, target_bindings=bindings)
            if len(value['sources']) == 8:
                value['sources'][-1] = provenance
            else:
                value['sources'].append(provenance)
        value['cursor'] = head
        self.cache[session_id] = deepcopy(value)
        return value


def human_revision(repository, session_id, question, *, plan_id, version, changes):
    """Called exclusively by the human plan-control route, never update_plan."""
    source = {'kind': 'human_plan_edit', 'plan_id': plan_id, 'plan_version': version,
              'sha256': sha256_canonical(changes)}
    return {'version': VERSION, 'status': 'verified',
            'scope': 'analysis' if FULL_ANALYSIS.search(question) else 'question',
            'estimands': sorted(requested_targets(question)),
            'target_bindings': requested_outcomes(question),
            'sources': [source], 'latest_request': source, 'request_chain_sha256': sha256_canonical(source),
            'cursor': _leaf(repository, session_id)}


def enforce(result, requirements):
    missing = list(result['missing'])
    if not _valid(requirements) or requirements['status'] != 'verified':
        missing.append('task_requirements:unverified')
    else:
        if requirements['scope'] == 'analysis' and result.get('scope') == 'question':
            missing.append('task_scope:full_analysis_required')
        if requested_targets_unbound(result, set(requirements['estimands']), requirements.get('target_bindings', [])):
            missing.append('target:requested_estimand_unbound')
    return {**result, 'status': 'partial' if missing else result['status'],
            'missing': list(dict.fromkeys(missing)),
            'task_requirements_sha256': signature(requirements)}
