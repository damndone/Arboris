"""Read a durable isolated review for the common, explicitly requested report."""
from __future__ import annotations

from pathlib import Path

from ..canonical import sha256_canonical
from .completion import evaluate, source_receipt
from .session import JsonlSessionRepository
from .workflow import WorkflowExecutionError


def collect_review(root, target, options):
    repository = JsonlSessionRepository(Path(root) / 'workbench', create=False)
    try:
        branch = repository.get_branch(options['session_id'])
    except KeyError as exc:
        raise WorkflowExecutionError('research review session is unavailable') from exc
    intent = next((e.payload for e in branch if e.entry_type == 'research_review_intent'
                   and e.payload['review_id'] == options['review_id']), None)
    result = next((e.payload for e in branch if e.entry_type == 'research_review_result'
                   and e.payload['review_id'] == options['review_id']), None)
    if intent is None or result is None:
        raise WorkflowExecutionError('research review is unavailable on this conversation branch')
    packet = intent['packet']
    if sha256_canonical(packet) != intent['packet_sha256'] or result['packet_sha256'] != intent['packet_sha256']:
        raise WorkflowExecutionError('research review evidence packet changed')
    source = source_receipt(root, target)
    if source is None or packet.get('source') != source:
        raise WorkflowExecutionError('research review source does not match the report source')
    inputs = intent.get('verification_inputs')
    current = evaluate(root, inputs['contract'], inputs['evidence']) if inputs else None
    status = ('verification_unavailable' if current is None else
        'unchanged' if current['verified_manifest_sha256'] == result['manifest_sha256'] else 'changed_or_unavailable')
    references = []
    if inputs:
        evidence = inputs['evidence'] or {}
        references = [ref for kind in ['models', 'diagnostics', 'sensitivity'] for ref in evidence.get(kind, [])]
        if evidence.get('report'):
            references.append(evidence['report'])
    return {'session_id':options['session_id'], 'review_id':options['review_id'],
        'packet_sha256':intent['packet_sha256'], 'manifest_sha256':result['manifest_sha256'],
        'evidence_status':status, 'independent_numerical_oracle':False,
        'scope':'Review of supplied summaries only; historical if evidence changed or verification is unavailable. Scientific validity is not certified.',
        'source':source, 'packet':packet, 'result':result,
        'verification_inputs':inputs,
        'result_refs':[{'run_id':ref['run_id'], 'artifact_id':ref['artifact_id']} for ref in references],
        'local_artifact_inputs':list(dict.fromkeys([source['artifact_id'],
            *(ref['artifact_id'] for ref in references if ref['run_id'] == target['run_id'])]))}


def review_rows(review):
    result = review['result']
    identity = {key:review[key] for key in ['session_id','review_id','packet_sha256','manifest_sha256','evidence_status']}
    rows = [{**identity, 'verdict':result['verdict'], 'severity':'summary',
        'message':result.get('reason', review['scope']), 'evidence_refs':'', 'raw_response':result.get('raw_response','')}]
    for key in ['findings', 'prior_findings']:
        rows.extend({**identity, 'verdict':result.get('prior_verdict',result['verdict']) if key == 'prior_findings' else result['verdict'],
            'severity':('prior ' if key == 'prior_findings' else '') + finding['severity'],
            'message':finding['message'], 'evidence_refs':', '.join(finding['evidence_refs']), 'raw_response':''}
            for finding in result.get(key, []))
    return rows
