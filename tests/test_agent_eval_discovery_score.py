"""Synthetic CLI checks for DiscoveryBench's offline replay."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/agent_eval/discovery_score.py"
UPSTREAM = "c31fcf011e070f021a5f5b906896d0821f6880e8"
GOLD = "fixture gold text"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, separators=(",", ":")).encode()


@pytest.fixture
def replay(tmp_path):
    def file(name, data):
        data = data if isinstance(data, bytes) else _json(data)
        (tmp_path / name).write_bytes(data)
        return {"path": name, "sha256": _sha(data)}

    metadata = file("metadata.json", b'{\n    "queries": [[{"qid": 0, "question": "Goal?"}]]\n}')
    inputs = [file("data.csv", b"x\n1\n"), file("tree.txt", b"(a,b);")]
    keys = [{"dataset": f"example-{i}", "metadata_file_number": i, "query_id": 0} for i in range(2)]
    plan = file("plan.json", {
        "status": "PROPOSED_UNAPPROVED", "upstream_commit": UPSTREAM, "candidate_count": 2,
        "cases": [{"key": key, "metadata": metadata, "resolved_declared_inputs": inputs} for key in keys],
    })
    protocol = file("protocol.json", {
        "schema": "discoverybench-judge-v1", "upstream_commit": UPSTREAM,
        "judge": {"model": "synthetic", "version": "fixture-v1"},
        "evaluator_artifacts": [file("mock-evaluator.py", b"# synthetic\n")],
    })

    def item(name, i=0, *, zero=False, gold=GOLD, query="Goal?", bad_score=False):
        matches = {} if zero else {"P0||G1": {
            "context": {"score": 1, "answer": True},
            "var": {"answer": '{"sizeA":2,"sizeB":4,"intersection":2,"explanation":""}'},
            "rel": {"answer": '{"answer":"B)"}'},
        }}
        raw = {
            "query": query, "HypoA": gold, "WorkflowA": None, "HypoB": "prediction", "WorkflowB": None,
            "gold_sub_hypo": {"sub_hypo": [{}, {}]}, "gen_sub_hypo": {"sub_hypo": [{}, {}]},
            "gen_subh_to_gold_subh": {"0": -1 if zero else 1, "1": -1},
            "gold_subh_covered": [] if zero else [1], "matched_gold_gen_subh_evals": matches,
            "final_score": 0 if zero or bad_score else 1 / 12,
        }
        return {"key": keys[i], "metadata_sha256": metadata["sha256"],
                "input_sha256s": [entry["sha256"] for entry in inputs], "status": "recorded",
                "gold_sha256": _sha(_json([query, gold, None])),
                "prediction_sha256": _sha(_json([query, "prediction", None])),
                "judgment": file(f"{name}.json", raw)}

    def run(candidate, baseline=None, *, wrong_judge=False):
        args = []
        for flag, items in (("candidate", candidate), ("baseline", baseline)):
            if items is not None:
                bundle = file(f"{flag}-bundle.json", {
                    "schema": "discoverybench-recordings-v1", "kind": "synthetic", "source": flag,
                    "plan_sha256": plan["sha256"], "cases": items,
                    "protocol_sha256": "0" * 64 if wrong_judge else protocol["sha256"],
                })
                args += [f"--{flag}", bundle["path"], bundle["sha256"]]
        return subprocess.run([sys.executable, str(SCRIPT), "--plan", plan["path"], plan["sha256"],
                               "--protocol", protocol["path"], protocol["sha256"], *args],
                              cwd=tmp_path, capture_output=True, text=True, check=False)

    return file, item, run


def _report(result):
    assert result.returncode == 0, result.stderr
    assert GOLD not in result.stdout
    return json.loads(result.stdout)


def test_partial_replay_keeps_denominator_and_distinguishes_zero(replay):
    _, item, run = replay
    report = _report(run([item("new")], [item("old", zero=True)]))
    arm = report["candidate"]
    assert report["denominator"] == 2 and report["plan_status"] == "PROPOSED_UNAPPROVED"
    assert arm["hms"] is None and arm["cases"][1]["status"] == "missing"
    assert arm["hms_bounds"] == pytest.approx([100 / 24, 50 + 100 / 24])
    assert report["baseline"]["cases"][0]["hms"] == 0
    assert report["paired_hms_delta"] is None


def test_complete_pair_requires_same_gold(replay):
    _, item, run = replay
    candidate = [item("new-a"), item("new-b", 1, zero=True)]
    baseline = [item("old-a", zero=True), item("old-b", 1, zero=True)]
    report = _report(run(candidate, baseline))
    assert report["candidate"]["kind"] == "synthetic"
    assert report["paired_hms_delta"] == pytest.approx(100 / 24)
    baseline[1] = item("old-c", 1, zero=True, gold="different")
    result = run(candidate, baseline)
    assert result.returncode != 0 and "gold" in result.stderr


def test_invalid_judgment_retains_receipt(replay):
    _, item, run = replay
    wrong = item("bad", bad_score=True)
    arm = _report(run([wrong]))["candidate"]
    assert arm["cases"][0]["status"] == "invalid_judgment"
    assert arm["cases"][0]["judgment"] == wrong["judgment"]
    assert arm["hms_bounds"] == [0, 100]


@pytest.mark.parametrize("drift", ["input", "input_order", "judge", "protocol_file",
                                   "judgment", "duplicate", "prediction", "query"])
def test_drift_fails_closed(replay, drift):
    file, item, run = replay
    case = item("new", query="Wrong?" if drift == "query" else "Goal?")
    if drift == "input":
        file("data.csv", b"x\n2\n")
    elif drift == "input_order":
        case["input_sha256s"].reverse()
    elif drift == "protocol_file":
        file("mock-evaluator.py", b"# altered")
    elif drift == "judgment":
        file("new.json", b"{}")
    elif drift == "prediction":
        case["prediction_sha256"] = "1" * 64
    result = run([case, case] if drift == "duplicate" else [case], wrong_judge=drift == "judge")
    assert result.returncode != 0 and not result.stdout
