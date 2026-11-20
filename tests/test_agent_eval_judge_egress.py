"""Check each outbound judge boundary with synthetic data and no transport."""

import builtins
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CANARY = "PRIVATE_CANARY"
OBSERVATION = 919293.123456
REPLY = '{"status":"insufficient_evidence"}'


@pytest.fixture
def case(tmp_path, monkeypatch):
    def no_transport(*args, **kwargs):
        pytest.fail("unexpected real transport")

    monkeypatch.setattr(socket.socket, "connect", no_transport)
    monkeypatch.setattr(socket.socket, "connect_ex", no_transport)
    monkeypatch.setattr(subprocess, "run", no_transport)
    original_import = builtins.__import__

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        assert "heldout" not in (name.split(".") + list(fromlist or ())), "loaded sealed tasks"
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", safe_import)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import agent_eval_judge as cli
    import agent_eval_grade as grader
    from agent_eval import cli_judges, judge
    from workbench.llm import client, config

    real_chat = client.chat_completion
    monkeypatch.setattr(client, "chat_completion", no_transport)
    monkeypatch.setattr(config, "load_llm_config", no_transport)
    folder = tmp_path / CANARY / "tasks" / f"{CANARY}.r1"
    folder.mkdir(parents=True)
    project = folder / f"project_{CANARY}"
    model = project / "runs" / f"run_{CANARY}" / "model_results" / f"{CANARY}.json"
    model.parent.mkdir(parents=True)
    model.write_text(json.dumps({"model_id": CANARY, "model_type": CANARY, "y_column": CANARY,
                                 "nobs": OBSERVATION, "coefficients": {CANARY: {
                                     "estimate": OBSERVATION, "std_error": [OBSERVATION],
                                 }}}))
    artifact = model.parent.parent / "artifacts" / CANARY / f"{CANARY}.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps({"result": {"nested": {"values": [OBSERVATION], "note": CANARY}}}))
    record = {
        "status": "ran", "suite": "external", "source": "blade", "task_id": CANARY,
        "project_root": str(project), "seed_run_id": "seed", "prompt": f"{CANARY} {OBSERVATION}",
        "reference": {"payload": [OBSERVATION, {"text": CANARY}]}, "answer": CANARY,
        "conversation": {
            "completed_marker": True, "turns": [{"reply": f"FINAL ANSWER: {CANARY} {OBSERVATION}"}],
            "confirmations": [{"status": "completed", "rows": [OBSERVATION]}],
            "entries": [
                {"entry_type": "message", "payload": {"role": "tool", "content": CANARY}},
                {"entry_type": "message", "payload": {"role": "tool", "content": json.dumps(
                    {"rows": [OBSERVATION], "preview": {"unseen_key": [[OBSERVATION, CANARY]]}})}},
            ],
        },
    }
    (folder / "record.json").write_text(json.dumps(record))
    owner = folder.parents[1] / "judging" / folder.name / "packet.txt"
    owner.parent.mkdir(parents=True)
    owner.write_text(f"historical private owner packet: {CANARY}, {OBSERVATION}")
    return SimpleNamespace(folder=folder, root=folder.parents[1], record=record, owner=owner, cli=cli,
                           grader=grader, cli_judges=cli_judges, judge=judge, client=client,
                           config=config, real_chat=real_chat)


def _assert_safe(text):
    assert CANARY not in text and str(OBSERVATION) not in text
    assert json.loads(text.rsplit("\n\n", 1)[-1]) == {
        "protocol": "judge-structural-evidence/v1", "rubric_status": "insufficient_evidence",
        "kind": "blade_external", "completed_marker": True, "turns": "one", "confirmations": "one",
    }


@pytest.mark.parametrize("backend", ["codex", "grok"])
def test_cli_wire_never_uses_historical_owner_packet(case, monkeypatch, backend):
    calls = []
    monkeypatch.setattr(case.judge, "require_outbound_approval", lambda: None, raising=False)

    def run(argv, *, input, **kwargs):
        text = input if backend == "codex" else Path(argv[argv.index("--prompt-file") + 1]).read_text()
        _assert_safe(text)
        assert CANARY not in str(argv) and CANARY not in kwargs["cwd"]
        calls.append(backend)
        stdout = REPLY if backend == "codex" else json.dumps({"text": REPLY})
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr(case.cli_judges.subprocess, "run", run)
    case.cli.run_backend(case.root, [case.folder], backend, None)
    assert calls == [backend]
    assert CANARY in case.owner.read_text()
    result = json.loads((case.root / "judging-review-local" / "case-001" /
                         f"{backend}.result.json").read_text())
    assert result["status"] == "unscored" and "scores" not in result


def test_api_wire_uses_typed_projection_and_does_not_publish_scores(case, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(case.judge, "require_outbound_approval", lambda: None, raising=False)
    monkeypatch.setattr(case.client, "chat_completion", case.real_chat)
    monkeypatch.setenv("WORKBENCH_EGRESS_AUDIT_DIR", str(tmp_path / "egress"))
    config = case.config.LLMConfig("https://judge.invalid/v1", "synthetic", "fixture-judge")
    monkeypatch.setattr(case.config, "load_llm_config", lambda: config)

    def post(request):
        body = json.loads(request.content)
        assert request.method == "POST" and request.url.path == "/v1/chat/completions"
        assert CANARY.encode() not in request.content and str(OBSERVATION).encode() not in request.content
        assert set(body) == {"model", "stream", "messages"}
        _assert_safe(body["messages"][1]["content"])
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": REPLY}, "finish_reason": "stop"}]})

    monkeypatch.setattr(case.client, "_client_factory", lambda _: httpx.Client(transport=httpx.MockTransport(post)))
    monkeypatch.setattr(case.grader, "grade_task", lambda *args, **kwargs: {
        "task": case.folder.name, "status": "ran", "suite": "external", "source": "blade", "user_actions": 0,
        "failed_operations": {CANARY: OBSERVATION},
    })
    cached = case.folder / "judge.json"
    legacy = '{"method":{"score":5,"reason":"historical"}}'
    cached.write_text(legacy)
    monkeypatch.setattr(sys, "argv", ["agent_eval_grade.py", str(case.root), "--judge", "--grader", "v2"])
    assert case.grader.main() == 0
    grades = json.loads((case.root / "grades-v2.json").read_text())
    row = grades["tasks"][0]
    assert len(calls) == 1 and row["outbound_review"]["status"] == "unscored"
    assert row["outbound_review"]["reason"] == "insufficient_evidence"
    assert "judge" not in row and "rubric_overall" not in grades["summary"]
    assert grades["summary"]["external"]["blade_rubric_overall"] is None
    assert cached.read_text() == legacy


def test_default_export_is_safe_and_preserves_owner_evidence(case, monkeypatch, capsys):
    original = case.owner.read_bytes()
    monkeypatch.setattr(sys, "argv", ["agent_eval_judge.py", str(case.root), "--export"])
    assert case.cli.main() == 0
    assert case.owner.read_bytes() == original
    outbound = case.root / "judging-outbound"
    paths = {p.relative_to(outbound).as_posix() for p in outbound.rglob("*")}
    assert paths == {"case-001", "case-001/packet.txt"}
    assert CANARY not in capsys.readouterr().out
    _assert_safe((outbound / "case-001/packet.txt").read_text())

    monkeypatch.setattr(sys, "argv", ["agent_eval_judge.py", str(case.root), "--export-owner"])
    assert case.cli.main() == 0
    owner = case.root / "judging-owner-local" / case.folder.name / "owner-packet.txt"
    assert CANARY in owner.read_text()
    assert owner.stat().st_mode & 0o077 == 0
    assert case.owner.read_bytes() == original


@pytest.mark.parametrize("entry", ["backend", "grade"])
def test_live_flags_refuse_before_transport_or_heldout(case, monkeypatch, capsys, entry):
    if entry == "backend":
        monkeypatch.setattr(sys, "argv", ["agent_eval_judge.py", str(case.root), "--backend", "codex"])
        main = case.cli.main
    else:
        monkeypatch.setattr(sys, "argv", ["agent_eval_grade.py", str(case.root), "--judge"])
        main = case.grader.main
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 2 and "scoped" in capsys.readouterr().err


@pytest.mark.parametrize("mutate", ["sealed", "malformed"])
def test_unsupported_evidence_rejected_before_configuration(case, monkeypatch, mutate):
    monkeypatch.setattr(case.judge, "require_outbound_approval", lambda: None, raising=False)
    if mutate == "sealed":
        case.record["suite"] = "heldout"
    else:
        case.record["conversation"]["completed_marker"] = {"nested": [OBSERVATION]}
    (case.folder / "record.json").write_text(json.dumps(case.record))
    with pytest.raises(ValueError, match="outbound"):
        case.grader.judge_task(case.folder, {})


def test_cli_sender_rejects_a_raw_prompt(case, monkeypatch):
    monkeypatch.setattr(case.judge, "require_outbound_approval", lambda: None, raising=False)
    with pytest.raises(ValueError, match="outbound"):
        case.cli_judges.run("codex", case.owner.read_text(), case.owner.parent)


def test_export_will_not_replace_linked_historical_packet(case, monkeypatch, capsys):
    original = case.owner.read_bytes()
    path = case.root / "judging-outbound/case-001/packet.txt"
    path.parent.mkdir(parents=True)
    path.symlink_to(case.owner)
    monkeypatch.setattr(sys, "argv", ["agent_eval_judge.py", str(case.root), "--export"])
    assert case.cli.main() == 2
    assert CANARY not in capsys.readouterr().out
    assert case.owner.read_bytes() == original


def test_outbound_reply_cannot_supply_rubric_scores(case):
    with pytest.raises(ValueError, match="outbound"):
        case.judge.outbound_result('{"status":"insufficient_evidence","method":{"score":5}}')
