"""Replay DiscoveryBench's published arithmetic on recorded evaluator JSON.

The released evaluator keeps its selected context matches, not the rejected
model decisions. Replay consumes those matches and the raw variable/relation
answers. The pinned receipts establish byte identity, not author attestation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


UPSTREAM = "c31fcf011e070f021a5f5b906896d0821f6880e8"
UNSCORED = {"unsupported_input", "missing_prediction", "missing_judgment", "run_failed"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _path(root, receipt):
    relative = Path(receipt["path"])
    path = (root / relative).resolve()
    _require(not relative.is_absolute() and path.is_relative_to(root),
             "receipt path must stay inside the local root")
    return path


def _pin(root, receipt, *, contents=False):
    path = _path(root, receipt)
    with path.open("rb") as stream:
        if contents:
            data = stream.read()
            digest = hashlib.sha256(data).hexdigest()
        else:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    _require(digest == receipt["sha256"], f"SHA-256 mismatch: {receipt['path']}")
    return data if contents else digest


def _load(root, receipt):
    return json.loads(_pin(root, receipt, contents=True), object_pairs_hook=_unique_object)


def _unique_object(pairs):
    obj = {}
    for name, value in pairs:
        _require(name not in obj, "duplicate JSON field")
        obj[name] = value
    return obj


def _key(case):
    key = case["key"]
    dataset, metadata, query = (key[name] for name in ("dataset", "metadata_file_number", "query_id"))
    _require(isinstance(dataset, str) and dataset and
             all(type(number) is int and number >= 0 for number in (metadata, query)),
             "invalid dataset/metadata/query key")
    return dataset, metadata, query


def _hypothesis_sha(record, side):
    text = [record["query"], record["Hypo" + side], record["Workflow" + side]]
    _require(all(isinstance(value, str) for value in text[:2]) and
             (text[2] is None or isinstance(text[2], str)), "invalid hypothesis receipt")
    return hashlib.sha256(json.dumps(text, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _query_sha(metadata, query_id):
    # Parse only the published query index. Other metadata fields include gold.
    text = metadata.decode("utf-8-sig")
    indexes = list(re.finditer(r'^    "queries"\s*:\s*', text, re.MULTILINE))
    _require(len(indexes) == 1, "missing or ambiguous query index")
    decoder = json.JSONDecoder(object_pairs_hook=_unique_object)
    groups, _ = decoder.raw_decode(text, indexes[0].end())
    questions = [query["question"] for group in groups for query in group if query["qid"] == query_id]
    _require(len(questions) == 1, "missing or ambiguous query ID")
    return hashlib.sha256(questions[0].encode("utf-8")).hexdigest()


def _pair_score(pair):
    context = pair["context"]
    _require(context["answer"] is True and context["score"] == 1, "invalid context match")
    counts = json.loads(pair["var"]["answer"], object_pairs_hook=_unique_object)
    gold, predicted, common = (counts[name] for name in ("sizeA", "sizeB", "intersection"))
    _require(all(type(count) is int and count >= 0 for count in (gold, predicted, common)) and
             common <= min(gold, predicted) and isinstance(counts["explanation"], str),
             "invalid variable counts")
    precision = common / predicted if predicted else 0.0
    recall = common / gold if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if common else 0.0

    # Preserve the ordering and spelling of the released answer parser.
    answer = json.loads(pair["rel"]["answer"], object_pairs_hook=_unique_object)["answer"].strip()
    for letter, phrase, score in (("A", "very similar", 1.0),
                                  ("B", "similar but general than HypoA", 0.5),
                                  ("C", "different", 0.0)):
        if answer.startswith(letter) or phrase in answer:
            return f1 * score
    raise ValueError("unscored relation answer")


def _replay(record):
    gold = record["gold_sub_hypo"]["sub_hypo"]
    predicted = record["gen_sub_hypo"]["sub_hypo"]
    matches = record["gen_subh_to_gold_subh"]
    _require(isinstance(gold, list) and gold and isinstance(predicted, list) and predicted and
             isinstance(matches, dict) and set(matches) == {str(p) for p in range(len(predicted))},
             "incomplete segmentation or context map")
    matched = {}
    for p in range(len(predicted)):
        g = matches[str(p)]
        _require(type(g) is int and -1 <= g < len(gold), "invalid context map index")
        if g >= 0:
            _require(g not in matched.values(), "context matching must be one-to-one")
            matched[f"P{p}||G{g}"] = g
    pairs = record["matched_gold_gen_subh_evals"]
    _require(isinstance(pairs, dict) and pairs.keys() == matched.keys() and
             record["gold_subh_covered"] == list(matched.values()), "inconsistent recorded matches")
    final = (len(matched) / len(gold)) * (sum(_pair_score(pairs[key]) for key in matched) / len(predicted))
    reported = record["final_score"]
    _require(type(reported) in (float, int) and math.isclose(final, reported, rel_tol=0, abs_tol=1e-12),
             "recorded final_score disagrees with replay")
    return 100 * final


def _arm(root, receipt, plan, protocol, roster):
    records = {}
    identity = {}
    if receipt is not None:
        bundle = _load(root, receipt)
        _require(bundle["schema"] == "discoverybench-recordings-v1" and
                 bundle["plan_sha256"] == plan and bundle["protocol_sha256"] == protocol,
                 "recordings do not bind the pinned plan and judge protocol")
        _require(bundle["kind"] in {"author_release", "paired_rerun", "synthetic"} and
                 isinstance(bundle["source"], str) and bundle["source"].strip(),
                 "recordings require declared source and kind")
        identity = {"bundle": receipt, "kind": bundle["kind"], "source": bundle["source"]}
        for item in bundle["cases"]:
            key = _key(item)
            _require(key in roster and key not in records, "unexpected or duplicate case")
            _require(all(item[field] == roster[key][field] for field in ("metadata_sha256", "input_sha256s")),
                     f"recorded input identity differs for {key}")
            records[key] = item

    cases = []
    scores = []
    for key, expected in roster.items():
        item = records.get(key, {"status": "missing"})
        status = item["status"]
        result = {**expected, "status": status, "hms": None}
        if status == "recorded":
            record = _load(root, item["judgment"])
            _require(hashlib.sha256(record["query"].encode("utf-8")).hexdigest() == expected["query_sha256"],
                     f"recorded query differs for {key}")
            for side, name in (("A", "gold_sha256"), ("B", "prediction_sha256")):
                _require(_hypothesis_sha(record, side) == item[name], f"{name} mismatch for {key}")
                result[name] = item[name]
            result["judgment"] = item["judgment"]
            try:
                result["hms"] = _replay(record)
            except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
                result.update(status="invalid_judgment", error=str(exc))
            else:
                scores.append(result["hms"])
        elif key in records:
            _require(status in UNSCORED and isinstance(item["reason"], str) and item["reason"].strip(),
                     f"unscored case requires a supported status and reason: {key}")
            result["reason"] = item["reason"]
        cases.append(result)
    count = len(roster)
    total = math.fsum(scores)
    missing = count - len(scores)
    return {**identity, "scored": len(scores), "hms": total / count if missing == 0 else None,
            "hms_bounds": [total / count, (total + 100 * missing) / count], "cases": cases}


def _report(root, plan_pin, protocol_pin, baseline_pin, candidate_pin):
    plan = _load(root, plan_pin)
    protocol = _load(root, protocol_pin)
    _require(plan["upstream_commit"] == protocol["upstream_commit"] == UPSTREAM and
             protocol["schema"] == "discoverybench-judge-v1", "unknown evaluator implementation")
    judge = protocol["judge"]
    _require(all(isinstance(judge[name], str) and judge[name].strip() for name in ("model", "version")) and
             protocol["evaluator_artifacts"], "judge version and evaluator artifacts are required")
    for source in protocol["evaluator_artifacts"]:
        _pin(root, source)

    roster = {}
    for case in plan["cases"]:
        key = _key(case)
        _require(key not in roster and case["resolved_declared_inputs"], "duplicate case or no inputs")
        metadata = _pin(root, case["metadata"], contents=True)
        roster[key] = {"key": case["key"], "metadata_sha256": case["metadata"]["sha256"],
                       "query_sha256": _query_sha(metadata, key[2]),
                       "input_sha256s": [_pin(root, source) for source in case["resolved_declared_inputs"]]}
    _require(roster and plan["candidate_count"] == len(roster), "frozen denominator mismatch")

    baseline = _arm(root, baseline_pin, plan_pin["sha256"], protocol_pin["sha256"], roster)
    candidate = _arm(root, candidate_pin, plan_pin["sha256"], protocol_pin["sha256"], roster)
    for old, new in zip(baseline["cases"], candidate["cases"], strict=True):
        if "gold_sha256" in old and "gold_sha256" in new:
            _require(old["gold_sha256"] == new["gold_sha256"], f"gold mismatch for {old['key']}")
    delta = None
    if baseline["hms"] is not None and candidate["hms"] is not None:
        _require((baseline["kind"] == "synthetic") == (candidate["kind"] == "synthetic"),
                 "cannot pair synthetic and recorded arms")
        delta = candidate["hms"] - baseline["hms"]
    return {"status": "OFFLINE_REPLAY_ONLY", "plan_status": plan["status"], "plan": plan_pin,
            "protocol": protocol_pin, "judge": judge, "upstream_commit": UPSTREAM,
            "denominator": len(roster), "baseline": baseline, "candidate": candidate,
            "paired_hms_delta": delta}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="root for local receipt paths")
    for name in ("plan", "protocol", "baseline", "candidate"):
        parser.add_argument(f"--{name}", nargs=2, metavar=("PATH", "SHA256"),
                            required=name in {"plan", "protocol"})
    args = parser.parse_args()
    pins = [dict(zip(("path", "sha256"), pair)) if pair else None
            for pair in (args.plan, args.protocol, args.baseline, args.candidate)]
    try:
        report = _report(args.root.resolve(), *pins)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
