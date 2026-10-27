"""Read-only historical count. No grading, answers, source data or provider calls.
Run: .venv/bin/python scripts/agent_eval/tool_rejections.py [checkout]
"""
import collections, json, statistics, sys
from pathlib import Path
root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
groups = ['free-speed2-20261025', 'free-off4b-20261022', 'free-off4b-auto-20261023', 'free-qrdata-20261025']
seen = set()
all_errors = collections.Counter()
for group in groups:
    grouped = collections.defaultdict(list)
    tape_status = collections.Counter()
    for path in sorted((root / 'local/agent-eval' / group).glob('*/tasks/*/record.json')):
        doc = json.loads(path.read_text())
        conv = doc.get('conversation', {})
        sid = conv.get('session_id')
        if sid and sid in seen:
            continue
        if sid:
            seen.add(sid)
        entries = conv.get('entries', [])
        results = {}
        for entry in entries:
            payload = entry['payload']
            if entry['entry_type'] == 'message' and payload.get('role') == 'tool':
                results[payload['tool_call_id']] = json.loads(payload['content'])
        for entry in entries:
            if entry['entry_type'] == 'tool_receipt':
                payload = entry['payload']
                results[payload['tool_call_id']] = payload['tool_result']
        emitted = sum(len(e['payload'].get('tool_calls', [])) for e in entries if e['entry_type'] == 'message')
        assert emitted == len(results), (path, emitted, len(results))
        rejected = [r for r in results.values() if r.get('ok') is False]
        fmt = sum(r.get('error') == 'invalid_tool_arguments' for r in rejected)
        grouped[path.parts[-4]].append((len(results), len(rejected), fmt))
        all_errors.update(r.get('error') for r in rejected)
        tape = path.with_name('provider_tape.jsonl')
        if tape.exists():
            for line in tape.open():
                tape_status.update([json.loads(line).get('status')])
    for mode, tasks in grouped.items():
        calls = sum(t[0] for t in tasks)
        rejects = sum(t[1] for t in tasks)
        formats = [t[2] for t in tasks]
        print(json.dumps({'group':group, 'mode':mode, 'tasks':len(tasks), 'calls':calls,
            'rejected':rejects, 'rate':round(rejects/calls,6) if calls else None,
            'format_failure_median':statistics.median(formats), 'format_failure_max':max(formats)}, sort_keys=True))
    print('provider_status', group, dict(tape_status))
print('error_counts', dict(all_errors))
