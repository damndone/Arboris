"""Read-only BLADE Table 2 arithmetic over pinned native JSON receipts.

Inputs come from BLADE (Gu et al., EMNLP 2024), Apache-2.0, commit below.
This replays the aggregation after alignment. It never imports the evaluator,
loads pickles, executes submitted Python, or makes semantic decisions.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import re
from statistics import fmean

if __package__:
    from .external import BLADE_DATASETS
else:
    from external import BLADE_DATASETS


SOURCE_COMMIT = "6118fa8d5007b91aa8c91c518182db82446a4547"
COVERAGE_K = 10
BOOTSTRAPS = 1000
SOURCE_FILES = {"data.csv", "info.json", "annotations.csv"}
TRUTH_FIELDS = ("num_cvars1", "num_mspecs1_unique", "num_mspecs1", "num_tspecs1")
GOLD_FIELDS = ("matched_cvars", "matched_models", "matched_models_cvar", "matched_gspecs", "matched_vspecs")
SUBMISSION_FIELDS = ("matched_cvars2", "matched_gspecs2", "matched_vspecs2", "num_cvars2", "num_tspecs2")
TYPES = ("cvar", "model", "model_cvar", "transform_graph", "transform_value")
OUTCOMES = ("aligned", "partial_transform", "generation_failed", "evaluator_failed",
            "missing_generation", "missing_alignment")
EMPTY = ((0.0,) * len(TYPES), ((),) * len(TYPES))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def digest_string(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)


def unique_object(pairs):
    data = dict(pairs)
    require(len(data) == len(pairs), "duplicate JSON key")
    return data


def read_json(path, digest=None):
    raw = path.read_bytes()
    observed = sha256(raw)
    require(digest is None or observed == digest, f"{path.name}: SHA-256 mismatch")
    return json.loads(raw, object_pairs_hook=unique_object), observed


def read_ref(base, ref):
    require(digest_string(ref["sha256"]), "invalid artifact digest")
    return read_json(base / ref["path"], ref["sha256"])[0]


def valid_judge(judge):
    return (set(judge) == {"model_snapshot", "temperature", "settings_sha256"}
            and isinstance(judge["model_snapshot"], str) and judge["model_snapshot"].strip()
            and type(judge["temperature"]) in (int, float) and judge["temperature"] == 0
            and digest_string(judge["settings_sha256"]))


def load_plan(path, digest, dataset_root):
    plan, _ = read_json(path, digest)
    require(plan["source_commit"] == SOURCE_COMMIT, "unsupported BLADE source commit")
    require(type(plan["repeats"]) is int and plan["repeats"] >= COVERAGE_K, "invalid repeat count")
    require(type(plan["bootstrap_seed"]) is int, "invalid bootstrap seed")
    require(valid_judge(plan["judge"]), "invalid judge snapshot or settings")
    require(digest_string(plan["input_protocol_sha256"]), "invalid input protocol digest")
    datasets = plan["datasets"]
    require(datasets and set(datasets) <= set(BLADE_DATASETS), "unexpected frozen dataset")
    for name, spec in datasets.items():
        files, truth = spec["files"], spec["truth"]
        require(set(files) == SOURCE_FILES, f"{name}: incomplete source files")
        require(set(truth) == set(TRUTH_FIELDS) and all(type(n) is int and n > 0 for n in truth.values())
                and truth["num_mspecs1_unique"] <= truth["num_mspecs1"], f"{name}: invalid truth counts")
        for filename, expected in files.items():
            require(sha256((dataset_root / name / filename).read_bytes()) == expected,
                    f"{name}/{filename}: SHA-256 mismatch")
    return plan


def native_rows(metrics, retained, expected_truth):
    for field, expected in expected_truth.items():
        value = metrics[field]
        observed = bool(retained) if field == "num_cvars1" else 5 in retained
        require(type(value) is int and (value == expected or (value == -1 and not observed)),
                f"{field}: truth counts mismatch")
    arrays = [metrics[name] for name in (*GOLD_FIELDS, *SUBMISSION_FIELDS)]
    require(all(isinstance(a, list) and len(a) == len(retained) for a in arrays), "incorrect metric rows")
    rows = []
    for status, row in zip(retained, zip(*arrays), strict=True):
        gold, (cvar2, graph2, value2, num_cv, num_t) = row[:5], row[5:]
        require(all(isinstance(xs, list) and all(isinstance(x, str) and x for x in xs)
                    for xs in (*gold, cvar2, graph2, value2)), "invalid matched identities")
        require(all(type(n) is int and n >= 0 for n in (num_cv, num_t)), "invalid submitted decision counts")
        require(status == 5 or not (num_t or gold[3] or gold[4] or graph2 or value2),
                "partial transform unexpectedly contains transform credit")
        matches = (cvar2, gold[1], gold[2], graph2, value2)
        denoms = (max(1, num_cv), 1, 1, max(1, num_t), max(1, num_t))
        require(all(len(m) <= n for m, n in zip(matches, denoms, strict=True))
                and (num_cv or not cvar2) and (num_t or not (graph2 or value2)), "invalid precision counts")
        precision = tuple(len(m) / n for m, n in zip(matches, denoms, strict=True))
        rows.append((precision, gold))
    return rows


def read_dataset(base, entry, dataset, spec, repeats):
    outcomes = ["missing_generation"] * repeats
    frozen = [EMPTY] * repeats
    if entry is None:
        return outcomes, frozen, []
    require(entry["files"] == spec["files"], "input file identities mismatch")
    submission = read_ref(base, entry["submission"])
    require(submission["dataset_name"] == dataset and type(submission["n"]) is int
            and submission["n"] == repeats, "submission roster mismatch")
    submissions = submission["analyses"]
    require(isinstance(submissions, dict) and set(submissions) <= {str(i) for i in range(repeats)},
            "unexpected submission slot")
    generation_failures, analyses = [], {}
    for key, item in submissions.items():
        index = int(key)
        if isinstance(item, dict):
            require(set(item) == {"cvars", "transform_code", "m_code"}
                    and isinstance(item["cvars"], dict)
                    and all(isinstance(item[k], str) for k in ("m_code", "transform_code")),
                    "invalid native analysis")
            analyses[index] = item
            outcomes[index] = "missing_alignment"
        else:
            require(isinstance(item, list) and len(item) == 2 and type(item[0]) is int and item[0] == 2
                    and isinstance(item[1], str), "invalid native generation failure")
            generation_failures.append(index)
            outcomes[index] = "generation_failed"

    if "evaluation" not in entry and "metrics" not in entry:
        return outcomes, frozen, []
    evaluation = read_ref(base, entry["evaluation"])
    metrics = read_ref(base, entry["metrics"])
    records = evaluation["results"]
    require(evaluation["dataset_name"] == dataset and isinstance(records, list)
            and len(records) == len(analyses) and metrics["analyses"] == list(analyses.values()),
            "analysis identity or evaluation count mismatch")
    statuses, retained, indices = [], [], []
    for (index, analysis), result in zip(analyses.items(), records, strict=True):
        require(result["analysis"] == analysis and result["dataset_name"] == dataset,
                "analysis identity mismatch")
        native = result["eval_run_result"]
        outer, transform = native["res_type"], native.get("res_type_transform")
        require(type(outer) is int and outer in {0, 1, 3, 4, 5, 6, 7}
                and (transform is None or (type(transform) is int and transform in {0, 1, 4})),
                "invalid native evaluation status")
        status = transform if outer == 5 and transform is not None else outer
        statuses.append(status)
        if outer == 5:
            retained.append(status)
            indices.append(index)
            outcomes[index] = "aligned" if transform is None else "partial_transform"
        else:
            outcomes[index] = "evaluator_failed"
    require(metrics["status"] == statuses + [2] * len(generation_failures)
            and all(type(status) is int for status in metrics["status"]), "native status order mismatch")
    rows = native_rows(metrics, retained, spec["truth"])
    for index, row in zip(indices, rows, strict=True):
        frozen[index] = row
    native = rows + [EMPTY] * len(generation_failures)
    # Native aggregation has no valid denominator when no execution supplied the truth counts.
    return outcomes, frozen, native if 5 in retained else []


def components(datasets, truth):
    metrics = []
    for name, rows in datasets.items():
        n_cv, n_models, n_models_cv, n_transforms = truth[name]
        top = rows[:COVERAGE_K]
        denoms = (n_cv, min(n_models, len(top)), min(n_models_cv, len(top)), n_transforms, n_transforms)
        precision = [fmean(row[0][i] for row in rows) for i in range(len(TYPES))]
        coverage = [len({match for row in top for match in row[1][i]}) / n
                    for i, n in enumerate(denoms)]
        require(all(c <= 1 for c in coverage), f"{name}: matches exceed ground truth counts")
        metrics.append((precision, coverage))
    return [(fmean(p[i] for p, _ in metrics), fmean(c[i] for _, c in metrics)) for i in range(len(TYPES))]


def weights_for(truth):
    totals = [sum(v) for v in zip(*(
        (n_cv, min(n_model, COVERAGE_K), min(n_model_cv, COVERAGE_K), n_t / 2, n_t / 2)
        for n_cv, n_model, n_model_cv, n_t in truth.values()
    ))]
    return [value / sum(totals) for value in totals]


def weighted(pairs, weights, *, native):
    f1 = [2 * p * c / (p + c) if p + c else (None if native else 0.0) for p, c in pairs]
    score = None if None in f1 else sum(w * value for w, value in zip(weights, f1, strict=True))
    return score, f1


def quantile(values, q):
    position = (len(values) - 1) * q
    lo = int(position)
    return values[lo] + (values[lo + 1] - values[lo]) * (position - lo)


def aggregate(datasets, truth, seed, *, native=False):
    result = {"point_weighted_f1": None, "bootstrap_mean_weighted_f1": None, "bootstrap_ci95": None,
              "components": None}
    if not all(datasets.values()):
        return result
    weights = weights_for(truth)
    pairs = components(datasets, truth)
    result["point_weighted_f1"], f1 = weighted(pairs, weights, native=native)
    result["components"] = {key: {"precision": p, "coverage_at_10": c, "f1": f, "weight": w}
                            for key, (p, c), f, w in zip(TYPES, pairs, f1, weights, strict=True)}
    if all(len(rows) > COVERAGE_K for rows in datasets.values()):
        rng = random.Random(seed)
        values = []
        for _ in range(BOOTSTRAPS):
            sampled = {name: rng.choices(rows, k=len(rows)) for name, rows in datasets.items()}
            values.append(weighted(components(sampled, truth), weights, native=native)[0])
        if None not in values:
            values.sort()
            result["bootstrap_mean_weighted_f1"] = fmean(values)
            result["bootstrap_ci95"] = [quantile(values, q) for q in (0.025, 0.975)]
    return result


def read_cohort(path, plan, plan_digest):
    cohort, digest = read_json(path)
    require(isinstance(cohort["cohort"], str) and cohort["cohort"].strip(), "invalid cohort ID")
    require(cohort["plan_sha256"] == plan_digest, "cohort plan mismatch")
    require(valid_judge(cohort["judge"]) and cohort["judge"] == plan["judge"], "judge mismatch")
    require(cohort["input_protocol_sha256"] == plan["input_protocol_sha256"], "input protocol mismatch")
    receipt = read_ref(path.parent, cohort["judge_receipt"])
    entries = cohort["datasets"]
    require(isinstance(entries, dict) and set(entries) <= set(plan["datasets"]), "unexpected dataset")
    aligned_digests = {name: {key: entry[key]["sha256"] for key in ("evaluation", "metrics")}
                       for name, entry in entries.items() if "evaluation" in entry and "metrics" in entry}
    require(valid_judge(receipt["judge"]) and receipt["judge"] == plan["judge"]
            and receipt["source_commit"] == SOURCE_COMMIT
            and receipt["datasets"] == aligned_digests, "judge receipt does not bind the alignments")
    truth, frozen, native, all_outcomes = {}, {}, {}, {}
    for name, spec in plan["datasets"].items():
        try:
            outcomes, frozen[name], native[name] = read_dataset(path.parent, entries.get(name), name,
                                                               spec, plan["repeats"])
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise ValueError(f"{name}: {exc}") from exc
        all_outcomes[name] = outcomes
        truth[name] = tuple(spec["truth"][key] for key in TRUTH_FIELDS)
    counts = Counter(status for statuses in all_outcomes.values() for status in statuses)
    return {
        "cohort": cohort["cohort"],
        "cohort_sha256": digest,
        "counts": {"planned": sum(counts.values()), **{status: counts[status] for status in OUTCOMES}},
        "slot_outcomes": all_outcomes,
        "native_denominators": {
            name: sum(s in OUTCOMES[:3] for s in statuses) if name in aligned_digests else None
            for name, statuses in all_outcomes.items()
        },
        "frozen_slots": aggregate(frozen, truth, plan["bootstrap_seed"]),
        "native_order": aggregate(native, truth, plan["bootstrap_seed"], native=True),
    }


def audit(plan_path, plan_digest, dataset_root, paths):
    require(digest_string(plan_digest), "invalid plan SHA-256")
    require(len(paths) in {1, 2}, "expected one or two cohorts")
    plan = load_plan(plan_path, plan_digest, dataset_root)
    cohorts = [read_cohort(path, plan, plan_digest) for path in paths]
    require(len({c["cohort"] for c in cohorts}) == len(cohorts), "duplicate cohort ID")
    pair_ready = (len(cohorts) == 2 and set(plan["datasets"]) == set(BLADE_DATASETS) and plan["repeats"] == 20
                  and all(c["native_order"]["bootstrap_mean_weighted_f1"] is not None
                          and not any(c["counts"][status] for status in OUTCOMES[3:]) for c in cohorts))
    return {"source_commit": SOURCE_COMMIT, "plan_sha256": plan_digest, "judge": plan["judge"],
            "coverage_k": COVERAGE_K, "bootstrap_iterations": BOOTSTRAPS,
            "bootstrap_seed": plan["bootstrap_seed"], "pair_ready": pair_ready, "cohorts": cohorts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--cohorts", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    try:
        report = audit(args.plan, args.plan_sha256, args.dataset_root, args.cohorts)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
