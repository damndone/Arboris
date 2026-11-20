"""The offline replay harness retains each sample and caps project scratch."""

import importlib.util
import fcntl
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def campaign(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('turn_ab', scripts / 'perf_agent_turn_ab.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _: SimpleNamespace(free=10**12))
    monkeypatch.setattr(module, '_other_python_processes', lambda: [])
    return module


def test_alternating_replays_retain_all_numbers_and_logs_without_full_projects(campaign, tmp_path, monkeypatch):
    from perf_evidence import read_records

    def replay(command, *, stdout=None, stderr=None, **unused):
        work = Path(command[command.index('--work') + 1])
        summary = Path(command[command.index('--out') + 1])
        assert work == tmp_path / 'active' / 'worker'
        project = work / 'project'
        project.mkdir(parents=True)
        (project / 'generated.csv').write_bytes(b'copy of the frozen input')
        sessions = project / 'workbench' / 'agent-sessions'
        sessions.mkdir(parents=True)
        (sessions / 'replay.jsonl').write_bytes(b'{"entry_type":"tool_receipt"}\n')
        (work / 'normalized-journal.json').write_bytes(b'[]\n')
        stdout.write(b'worker stdout\n')
        stderr.write(b'complete failure detail\n' + b'x' * 2100)
        if '002' in summary.name:
            return SimpleNamespace(returncode=1)
        summary.write_text(json.dumps({'step_nonmodel_ms_median': 2.0, 'turn_nonmodel_s_total': 0.25}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(campaign.subprocess, 'run', replay)
    rows = [campaign._one(tmp_path, 'A', tmp_path, 'b-c', tmp_path, tmp_path, ordinal, 'pair')
            for ordinal in range(3)]

    assert [row['status'] for row in rows] == ['ok', 'ok', 'failed']
    assert [row['summary']['turn_nonmodel_s_total'] for row in rows[:2]] == [0.25, 0.25]
    records = read_records(tmp_path / 'retention.jsonl')
    assert [record['metadata']['status'] for record in records] == ['ok', 'ok', 'failed']
    raw_rows = [json.loads(line) for line in (tmp_path / 'runs.jsonl').read_text().split('\n') if line]
    assert [row['status'] for row in raw_rows] == ['ok', 'ok', 'failed']
    [representative] = (tmp_path / 'representatives').rglob('*.tar.gz')
    assert all(row['retention']['representative_bytes'] == representative.stat().st_size for row in rows)
    assert not (tmp_path / 'active').exists()
    assert not (tmp_path / 'work').exists()
    failure_logs = {log['relative_path']: Path(log['path']).read_bytes()
                    for log in records[-1]['metadata']['retained_logs']}
    assert failure_logs['stdout.log'] == b'worker stdout\n'
    assert failure_logs['stderr.log'] == b'complete failure detail\n' + b'x' * 2100
    assert failure_logs['worker/normalized-journal.json'] == b'[]\n'
    assert failure_logs['worker/project/workbench/agent-sessions/replay.jsonl'] == b'{"entry_type":"tool_receipt"}\n'
    another = campaign._one(tmp_path, 'A-b', tmp_path, 'c', tmp_path, tmp_path, 3, 'pair')
    assert Path(another['retention']['representative']) != representative


def test_unrecorded_active_replay_blocks_new_project(campaign, tmp_path, monkeypatch):
    active = tmp_path / 'active'
    active.mkdir()
    (active / 'interrupted').write_text('partial run')
    monkeypatch.setattr(campaign.subprocess, 'run', lambda *args, **kwargs: pytest.fail('launched overlapping replay'))

    with pytest.raises(FileExistsError, match='active'):
        campaign._one(tmp_path, 'A', tmp_path, 'task', tmp_path, tmp_path, 0, 'pair')

    assert (active / 'interrupted').read_text() == 'partial run'


def test_a_reused_label_cannot_mix_a_different_exported_backend(campaign, tmp_path, monkeypatch, capsys):
    (tmp_path / 'runs.jsonl').write_text(json.dumps({'label': 'A', 'backend': str(tmp_path / 'original')}) + '\n')
    monkeypatch.setattr(campaign, '_one', lambda *args, **kwargs: pytest.fail('mixed source backends'))
    monkeypatch.setattr(sys, 'argv', ['perf_agent_turn_ab.py', '--out', str(tmp_path), '--provider', 'recorded.json',
                                    '--a', 'A=' + str(tmp_path / 'changed'), '--b', 'B=' + str(tmp_path / 'other'),
                                    '--task', 'case=fixture'])
    with pytest.raises(SystemExit, match='2'):
        campaign.main()

    assert 'new --out' in capsys.readouterr().err


@pytest.fixture
def replay_arguments(tmp_path, monkeypatch):
    task = tmp_path / 'fixture'
    task.mkdir()
    for name in ('data.csv', 'record.json', 'provider_tape.jsonl.gz'):
        (task / name).write_text(name)
    provider = tmp_path / 'provider.json'
    provider.write_text('{}')
    out = tmp_path / 'output'
    monkeypatch.setattr(sys, 'argv', ['perf_agent_turn_ab.py', '--out', str(out), '--provider', str(provider),
                                    '--a', 'A=' + str(tmp_path / 'a'), '--b', 'B=' + str(tmp_path / 'b'),
                                    '--task', 'case=' + str(task)])
    return out, task, provider


@pytest.mark.parametrize('changed_input', ['data.csv', 'record.json', 'provider_tape.jsonl.gz', 'provider.json'])
def test_replay_cannot_append_to_a_campaign_with_changed_inputs(
        campaign, replay_arguments, monkeypatch, capsys, changed_input):
    out, task, provider = replay_arguments
    calls = []

    def stopped(*args):
        calls.append(args)
        return {'ordinal': 0, 'status': 'not_started_low_disk'}

    monkeypatch.setattr(campaign, '_one', stopped)
    campaign.main()
    path = provider if changed_input == provider.name else task / changed_input
    path.write_text('changed bytes')

    with pytest.raises(SystemExit, match='2'):
        campaign.main()

    assert len(calls) == 1
    assert 'new --out' in capsys.readouterr().err
    assert (out / 'campaign.json').exists()


def test_replay_locks_the_full_campaign_before_starting(campaign, replay_arguments, monkeypatch, capsys):
    out, _, _ = replay_arguments
    out.mkdir()
    monkeypatch.setattr(campaign, '_one', lambda *args: pytest.fail('launched outside the campaign lock'))

    with (out / '.campaign.lock').open('ab') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit, match='2'):
            campaign.main()

    assert 'already running' in capsys.readouterr().err
