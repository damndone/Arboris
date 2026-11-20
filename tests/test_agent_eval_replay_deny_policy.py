"""Replay admission tests with synthetic source and zero provider activity."""

import sys

import pytest

import agent_eval_run


DENY_WRITER = '''\
import json

raise AssertionError("historic launcher must never run")

DENY = {"deny": [{"class": "external"}, {"class": "high"}]}
permission_path = project.root / "workbench/agent-permissions.json"
with permission_path.open("x") as stream:
    json.dump(DENY, stream)
'''


class AdmissionPassed(Exception):
    """Reached the first side-effect boundary after parsing."""


@pytest.mark.parametrize(
    "source, flags, blocked",
    [
        (DENY_WRITER, [], True),
        (DENY_WRITER, ["--project-deny-policy"], False),
        ('# "agent-permissions.json": {"deny": [{"class": "high"}]}\n', [], False),
        (
            'permission_path = project.root / "workbench/agent-permissions.json"\n'
            'permission_path.read_text()\n'
            'json.dumps({"deny": [{"class": "high"}]})\n',
            [],
            False,
        ),
        (
            'permission_path = project.root / "workbench/agent-permissions.json"\n'
            'permission_path.write_text(json.dumps({"deny": [{"class": "high"}]}))\n',
            [],
            True,
        ),
        (None, [], False),
    ],
)
def test_replay_requires_the_original_project_deny_policy(tmp_path, monkeypatch, capsys, source, flags, blocked):
    previous = tmp_path / "previous-round"
    previous.mkdir()
    if source is not None:
        (previous / "run.py").write_text(source)
    out = tmp_path / "replay"
    monkeypatch.setattr(sys, "argv", ["agent_eval_run.py", "--out", str(out), "--replay-round", str(previous), *flags])

    def stop_before_side_effects():
        raise AdmissionPassed

    monkeypatch.setattr(agent_eval_run, "_hold_machine_awake", stop_before_side_effects)
    if blocked:
        with pytest.raises(SystemExit) as refusal:
            agent_eval_run.main()
        assert refusal.value.code == 2
        assert "add --project-deny-policy" in capsys.readouterr().err
    else:
        with pytest.raises(AdmissionPassed):
            agent_eval_run.main()
    assert not out.exists()
