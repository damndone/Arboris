#!/usr/bin/env python3
"""Reference against opt-in fast IV on a registered shared input, in fresh workers.

At least five baseline calibrations and five alternating pairs are mandatory. All
lanes must have sample SD / median below 5%; fast time, RSS and run bytes may not
exceed 1.05x reference medians. Each engine must repeat its own bits. Cross-engine
agreement uses the fixed, fixture/oracle-backed product tolerances, never a CLI
knob. Reference preservation against v1.9.0 remains a separate bit-identical gate.
Host process snapshots cover the whole worker lifetime at 0.2s intervals (gaps
above 1s fail); this is sampled host evidence, not OS process-event tracing.

    PYTHONPATH=backend .venv/bin/python scripts/perf_fast_engine.py --out local/perf-evidence/<fresh dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from perf_1m import GATE_MEMORY, MEMORY_METRICS, REFERENCE_MEMORY, baseline_noise, product_sources, source_digest, source_identity, validate_family_manifest  # noqa: E402
from perf_evidence import MIN_FREE_BYTES, finalize_active, require_space, retain_worker_logs  # noqa: E402
from perf_host import HOST_MAX_GAP_SECONDS, other_heavy_runs, monitored_worker, wait_until_idle  # noqa: E402
from workbench.estimation_engine import (  # noqa: E402
    AGREEMENT_ABSOLUTE, AGREEMENT_ABSOLUTE_PER_ROW, AGREEMENT_RELATIVE, FAST_ENGINE_NAME,
)

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_METRICS = ("seconds", "rss_bytes", "run_bytes")
COMPARISON_METRICS = RESOURCE_METRICS + tuple(f"delivery_{m}" for m in RESOURCE_METRICS)
RESOURCE_RATIO_LIMIT = 1.05


def measurement_identity() -> dict:
    """Pin current disk identity independently of any mapped native image."""
    from workbench.estimation_engine import native
    output = native.library_directory()
    build = native.verify_build(ROOT / "native/engine", output)
    if not build or not build.get("build_identity_sha256"):
        raise ValueError("complete_native_build_identity_required")
    sources = product_sources(ROOT)
    sources.update({str(path.relative_to(ROOT)): source_digest(path)
                    for path in sorted((ROOT / "scripts").rglob("*.py")) if path.is_file()})
    return {"sources": sources, "native_build": build |
            {"abi": native.ABI_VERSION, "manifest": str(native.manifest_path(output))}}


def verify_host_trace(monitor: dict, evidence: Path) -> None:
    raw = evidence.read_bytes()
    if Path(monitor["evidence"]).resolve() != evidence or hashlib.sha256(raw).hexdigest() != monitor["sha256"]:
        raise ValueError("host_trace_identity_mismatch")
    from workbench.jsonl_store import jsonl_lines

    samples = [json.loads(line) for line in jsonl_lines(raw)]
    stamps = [sample["monotonic_seconds"] for sample in samples]
    if len(stamps) < 2 or len(stamps) != monitor["samples"] or not all(finite(stamp) for stamp in stamps):
        raise ValueError("host_trace_sample_mismatch")
    overlap, errors = set(), []
    for sample in samples:
        if "error" in sample:
            errors.append(sample["error"])
        else:
            busy = sample["other_heavy_runs"]
            if not isinstance(busy, list) or not all(isinstance(command, str) for command in busy):
                raise ValueError("invalid_host_process_sample")
            overlap.update(busy)
    start, end = monitor["worker_started_monotonic"], monitor["worker_ended_monotonic"]
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    covered = finite(start) and finite(end) and stamps[0] <= start <= end <= stamps[-1]
    if (min(gaps) < 0 or max(gaps) != monitor["max_gap_seconds"]
            or covered != monitor["covers_worker"] or sorted(overlap) != monitor["overlap"]
            or errors != monitor["errors"]):
        raise ValueError("host_trace_summary_mismatch")


def runtime_engine_selection(active: Path, run_root: str) -> dict:
    root = Path(run_root).resolve()
    if root.parent != active.resolve() / "worker/benchmark/runs":
        raise ValueError("worker_run_root_outside_active")
    path = root / "model_results/iv_2sls_1.json"
    limit = 2 * 1024 * 1024
    if path.resolve(strict=True) != path or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("worker_model_packet_unavailable_or_oversized")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("worker_model_packet_oversized")
    packet = json.loads(raw, parse_constant=lambda value: {"nonfinite": value})
    if packet.get("model_id") != "iv_2sls_1" or packet.get("model_type") != "iv_2sls":
        raise ValueError("worker_model_packet_identity_mismatch")
    selection = packet["engine_selection"]
    if not isinstance(selection, dict) or packet.get("engine") != selection.get("used"):
        raise ValueError("worker_engine_selection_mismatch")
    return selection



def observe(out: Path, manifest: Path, engine: str, label: str, ledger: Path, commit: str) -> dict:
    waited = wait_until_idle()
    free = require_space(out)  # immediately before each worker, after any host wait
    identity_before = measurement_identity()
    manifest_bytes = manifest.read_bytes()
    manifest_before = hashlib.sha256(manifest_bytes).hexdigest()
    payload = json.loads(manifest_bytes)
    active = out / "active"
    active.mkdir(exist_ok=False)
    command = [sys.executable, "-B", str(ROOT / "scripts/perf_1m.py"), "--case", "iv", "--out", str(active / "worker"),
               "--manifest", str(manifest), "--estimation-engine", engine, "--request-figures"]
    host_trace = (out / "host" / f"{label}.jsonl").resolve()
    code, stdout, stderr, monitor = monitored_worker(command, host_trace,
                                                     cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "backend")})
    (active / "stdout.log").write_text(stdout)
    (active / "stderr.log").write_text(stderr)
    metrics = active / "worker" / "metrics.json"
    try:
        value = json.loads(metrics.read_text(), parse_constant=lambda value: {"nonfinite": value})
        if not isinstance(value, dict):
            raise ValueError("metrics_object_required")
    except (OSError, ValueError) as exc:
        value = {"status": "failed", "run_root": str(active / "worker" / "uncompleted"),
                 "measurement_error": f"{type(exc).__name__}: {exc}", "input_sha256": payload["sha256"]}
    try:
        verify_host_trace(monitor, host_trace)
        monitor["raw_evidence_verified"] = True
    except (OSError, ValueError, KeyError, TypeError) as exc:
        monitor["raw_evidence_verified"] = False
        monitor["raw_evidence_error"] = f"{type(exc).__name__}: {exc}"
    if engine == "fast" and value.get("status") == "completed":
        try:
            value["runtime_engine_selection"] = runtime_engine_selection(active, value["run_root"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            value["runtime_engine_selection_error"] = f"{type(exc).__name__}: {exc}"
    try:
        identity_after = measurement_identity()
    except (OSError, ValueError, RuntimeError) as exc:
        identity_after = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        manifest_after = source_digest(manifest)
    except OSError as exc:
        manifest_after = {"error": f"{type(exc).__name__}: {exc}"}
    value.update(label=label, waited_for_idle_seconds=waited, returncode=code, host_monitor=monitor,
                 disk_free_bytes_before=free, source_identity_before=identity_before,
                 source_identity_after=identity_after, version_commit=commit,
                 input_source=payload["source"], input_manifest_sha256_before=manifest_before,
                 input_manifest_sha256_after=manifest_after)
    value["retained_logs"] = retain_worker_logs(active, out / "logs" / f"{label}.logs")
    value["retention"] = finalize_active(active, ledger=ledger, record_id=label, metadata=value,
                                         archive_dir=out / "representatives", version=f"v1.9.1-{engine}", case="iv")
    print(json.dumps({key: value.get(key) for key in ("label", "status", "seconds", "rss_bytes", "run_bytes",
                                                       "waited_for_idle_seconds")}), flush=True)
    return value


def decoded(value):
    if isinstance(value, dict):
        if "binary64" in value:
            if set(value) != {"binary64"}:
                raise ValueError("malformed_binary64")
            number = float.fromhex(value["binary64"])
            if not math.isfinite(number):
                raise ValueError("nonfinite_number")
            return number
        return {k: decoded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decoded(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite_number")
    return value


def finite(value, *, positive=False):
    return type(value) in (int, float) and math.isfinite(value) and (not positive or value > 0)


def validate_signature(raw):
    """A shared missing field is an invalid experiment, never agreement."""
    value = decoded(raw)
    packet, kernel = value["packet"], value["kernel"]
    names = kernel["param_names"]
    if not names or len(set(names)) != len(names) or set(names) != set(packet["coefficients"]):
        raise ValueError("coefficient_names")
    for name in names:
        row = packet["coefficients"][name]
        for key in ("estimate", "std_error", "p_value", "ci_lower", "ci_upper"):
            if not finite(row[key]) or (key == "std_error" and row[key] <= 0):
                raise ValueError(f"invalid_coefficient_{key}")
        if not 0 <= row["p_value"] <= 1:
            raise ValueError("invalid_probability")
        inference = value["coefficient_inference"][name]
        if not finite(inference["statistic"]) or not finite(inference["p_value"]) or not 0 <= inference["p_value"] <= 1:
            raise ValueError("invalid_inference")
    if kernel["vcov_scope"] != "full" or kernel["vcov_param_names"] != names:
        raise ValueError("full_covariance_required")
    if len(kernel["params"]) != len(names) or not all(finite(v) for v in kernel["params"]):
        raise ValueError("invalid_params")
    covariance = kernel["vcov"]
    if len(covariance) != len(names) or any(len(row) != len(names) or not all(finite(v) for v in row) for row in covariance):
        raise ValueError("invalid_covariance")
    if any(covariance[i][i] <= 0 for i in range(len(names))):
        raise ValueError("invalid_covariance_diagonal")
    for key in ("nobs", "df_resid"):
        if not finite(packet[key], positive=True) or packet[key] != kernel[key]:
            raise ValueError(f"invalid_{key}")
    if not all(finite(packet[key]) for key in ("r_squared", "r_squared_adj")):
        raise ValueError("finite_fit_statistics_required")
    if not finite(packet["df_model"], positive=True):
        raise ValueError("invalid_df_model")
    sample = value["sample"]
    if sample["retained_count"] != packet["nobs"] or type(sample["missing_count"]) is not int or sample["missing_count"] < 0:
        raise ValueError("invalid_sample_counts")
    if len(sample["positions_sha256"]) != 64 or not sample["fingerprint_version"]:
        raise ValueError("sample_identity_required")
    if len(value["point_definition"]["actual_design_sha256"]) != 64:
        raise ValueError("design_identity_required")
    if kernel["reference_distribution"] not in {"z", "t"} or not kernel["df_method"]:
        raise ValueError("inference_definition_required")
    if kernel["loglik"] is None and not kernel["unavailable"].get("loglik"):
        raise ValueError("NA_definition_required")
    diagnostics = value["diagnostics"]
    stages = diagnostics["weak_instruments"]["per_endogenous"]
    if not stages:
        raise ValueError("first_stage_required")
    checks = [(row, "p_value") for row in stages.values()] + [(diagnostics["endogeneity"], "pvalue")]
    overid = diagnostics["overidentification"]
    if overid["applicable"]:
        checks.append((overid, "pvalue"))
    elif not overid.get("verdict"):
        raise ValueError("NA_definition_required")
    for row, pkey in checks:
        if not finite(row["statistic"]) or not finite(row[pkey]) or not 0 <= row[pkey] <= 1 or not row["reference_distribution"]:
            raise ValueError("invalid_diagnostic")
    return value


def scientific_differences(reference, fast, path="", *, nobs=0):
    """Exact structure/NA/counts; symmetric fixed absolute + relative float bound."""
    if isinstance(reference, dict):
        if not isinstance(fast, dict) or reference.keys() != fast.keys():
            return [f"{path}: fields_differ"]
        return [error for key in reference for error in scientific_differences(
            reference[key], fast[key], f"{path}.{key}".lstrip("."), nobs=nobs)]
    if isinstance(reference, list):
        if not isinstance(fast, list) or len(reference) != len(fast):
            return [f"{path}: shape_differs"]
        return [error for i, (a, b) in enumerate(zip(reference, fast)) for error in
                scientific_differences(a, b, f"{path}[{i}]", nobs=nobs)]
    if type(reference) is float and type(fast) is float:
        exact = path.rsplit(".", 1)[-1] in {"nobs", "df_model", "df_resid"}
        absolute = AGREEMENT_ABSOLUTE
        if path == "diagnostics.overidentification.statistic":
            absolute = max(absolute, nobs * AGREEMENT_ABSOLUTE_PER_ROW)
        if not exact and abs(reference - fast) <= absolute + AGREEMENT_RELATIVE * max(abs(reference), abs(fast)):
            return []
    if type(reference) is type(fast) and reference == fast:
        return []
    return [f"{path}: fast {fast!r} vs reference {reference!r}"]


def inference_numbers(signature, *, stable_reference=False):
    """Use the product's per-quantity oracle contract, with all covariance diagonals.

    Reported reference p-values remain in the signature. Only comparison tails
    are recalculated from their recorded statistic and declared distribution.
    Coefficient tails come from the persisted full precision inference kernel;
    the public packet's coefficient probabilities were already rounded to 6 dp.
    """
    from scipy import stats
    packet, kernel = signature["packet"], signature["kernel"]
    out = {key: float(packet[key]) for key in ("nobs", "df_model", "df_resid")}
    for i, name in enumerate(kernel["param_names"]):
        # Numeric labels avoid ambiguity for quoted terms containing dots.
        term = f"p{i}"
        row = packet["coefficients"][name]
        out.update({f"params.{term}": row["estimate"], f"std_errors.{term}": row["std_error"],
                    f"conf_int.{term}.lower": row["ci_lower"], f"conf_int.{term}.upper": row["ci_upper"],
                    f"tstats.{term}": signature["coefficient_inference"][name]["statistic"],
                    f"pvalues.{term}": signature["coefficient_inference"][name]["p_value"]})
        for j, number in enumerate(kernel["vcov"][i]):
            out[f"cov.{term}.p{j}"] = number
    def test_values(name, row, pkey):
        distribution, _, parameters = row["reference_distribution"].partition("(")
        degrees = [int(value) for value in parameters.rstrip(")").split(",")]
        if distribution not in {"chi2", "F"} or len(degrees) != (2 if distribution == "F" else 1):
            raise ValueError("unsupported_diagnostic_distribution")
        probability = row[pkey]
        if stable_reference:
            probability = float(stats.f.sf(row["statistic"], *degrees) if distribution == "F"
                                else stats.chi2.sf(row["statistic"], *degrees))
        out.update({name: row["statistic"], f"{name}.pval": probability,
                    f"{name}.df": float(degrees[0]), f"{name}.valid": 1.})
        if len(degrees) == 2:
            out[f"{name}.df_denom"] = float(degrees[1])
    diagnostics = signature["diagnostics"]
    for name, row in diagnostics["weak_instruments"]["per_endogenous"].items():
        test_values(f"first_stage.{name}", row, "p_value")
    row = diagnostics["endogeneity"]
    test_values(row.get("test", "endogeneity"), row, "pvalue")
    row = diagnostics["overidentification"]
    if row["applicable"]:
        test_values(row["test"], row, "pvalue")
    return out


def resource_values(run, memory="rss"):
    resource = ("seconds", MEMORY_METRICS[memory], "run_bytes")
    return {**{m: run.get(m) for m in resource},
            **{f"delivery_{m}": run.get("requested_delivery", {}).get(m) for m in resource}}


def has_verified_host(run):
    monitor = run.get("host_monitor", {})
    gap = monitor.get("max_gap_seconds")
    return (monitor.get("raw_evidence_verified") is True
            and monitor.get("samples", 0) >= 2 and monitor.get("covers_worker") is True
            and finite(gap) and gap <= HOST_MAX_GAP_SECONDS
            and monitor.get("overlap") == [] and monitor.get("errors") == [])


def evaluate_report(report, memory=GATE_MEMORY):
    failures, numerical = [], []
    calibration, pairs = report.get("calibration", []), report.get("pairs", [])
    complete_pairs = sum(set(pair) == {"reference", "fast"} for pair in pairs)
    if len(calibration) < 5 or complete_pairs < 5:
        failures.append("at_least_five_calibrations_and_pairs_required")
    for i, pair in enumerate(pairs):
        expected = ["fast", "reference"] if i % 2 == 0 else ["reference", "fast"]
        if list(pair) != expected[:len(pair)]:
            failures.append(f"pair-{i}: alternating_order_required")
        elif len(pair) != len(expected):
            failures.append(f"pair-{i}: incomplete_pair")
    lanes = {"calibration": calibration,
             **{engine: [p[engine] for p in pairs if engine in p] for engine in ("reference", "fast")}}
    identity = report.get("source_identity")
    if not identity or not identity.get("sources") or not identity.get("native_build", {}).get("build_identity_sha256"):
        failures.append("source_identity_required")
    valid = {}
    seen_labels = set()
    expected_delivery = None
    if calibration:
        first_delivery = calibration[0].get("requested_delivery", {})
        expected_delivery = (first_delivery.get("requirements"), first_delivery.get("figure_artifact_ids"))
    for lane, runs in lanes.items():
        for run in runs:
            label = run.get("label", "unlabelled")
            if label in seen_labels or label == "unlabelled":
                failures.append(f"{label}: unique_measurement_label_required")
            seen_labels.add(label)
            if run.get("status") != "completed" or run.get("returncode") != 0:
                failures.append(f"{label}: worker_failed")
            if run.get("engine_used") != (FAST_ENGINE_NAME if lane == "fast" else "linearmodels"):
                failures.append(f"{label}: requested_engine_did_not_run")
            if lane == "fast":
                selection = run.get("runtime_engine_selection")
                if (not isinstance(selection, dict) or selection.get("requested") != "fast"
                        or selection.get("used") != FAST_ENGINE_NAME
                        or selection.get("build") != (identity or {}).get("native_build")):
                    failures.append(f"{label}: runtime_build_identity_mismatch")
            observed = resource_values(run)
            for metric in COMPARISON_METRICS:
                if not finite(observed[metric], positive=True):
                    failures.append(f"{label}: invalid_{metric}")
            delivery = run.get("requested_delivery", {})
            if (delivery.get("status") != "completed" or not delivery.get("figure_count")
                    or not delivery.get("figure_artifact_ids")
                    or (delivery.get("requirements"), delivery.get("figure_artifact_ids")) != expected_delivery):
                failures.append(f"{label}: requested_delivery_incomplete_or_different")
            if not finite(run.get("disk_free_bytes_before")) or run["disk_free_bytes_before"] < MIN_FREE_BYTES:
                failures.append(f"{label}: disk_floor")
            if not has_verified_host(run):
                failures.append(f"{label}: host_exclusivity_unverified")
            if run.get("source_identity_before") != identity or run.get("source_identity_after") != identity:
                failures.append(f"{label}: source_identity_changed")
            if not report.get("input_sha256") or run.get("input_sha256") != report["input_sha256"]:
                failures.append(f"{label}: input_identity_changed")
            manifest_sha = report.get("input_manifest_sha256")
            if (not manifest_sha or run.get("input_manifest_sha256_before") != manifest_sha
                    or run.get("input_manifest_sha256_after") != manifest_sha):
                failures.append(f"{label}: input_manifest_identity_changed")
            try:
                valid[id(run)] = validate_signature(run["acceptance_signature"])
            except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
                failures.append(f"{label}: invalid_signature: {exc}")
    repeats = {}
    for engine, runs in {"reference": calibration + lanes["reference"], "fast": lanes["fast"]}.items():
        signatures = [r.get("acceptance_signature") for r in runs]
        repeats[engine] = len(signatures) >= 2 and bool(signatures[0]) and all(s == signatures[0] for s in signatures)
        if len(signatures) < 2:
            failures.append(f"{engine}: repeat_evidence_unavailable")
        elif not repeats[engine]:
            failures.append(f"{engine}: repeated_bits_differ")
    reference = next((valid[id(r)] for r in calibration if id(r) in valid), None)
    if reference:
        for run in lanes["fast"]:
            if id(run) in valid:
                numerical.extend(f'{run["label"]}: {e}' for e in scientific_differences(
                    reference, valid[id(run)], nobs=reference["packet"]["nobs"]))
                from workbench.estimation_engine.iv import disagreements
                try:
                    errors = disagreements(inference_numbers(valid[id(run)]),
                                           inference_numbers(reference, stable_reference=True),
                                           reference["packet"]["nobs"])
                    numerical.extend(f'{run["label"]}: {error}' for error in errors)
                except (KeyError, ValueError, TypeError) as exc:
                    numerical.append(f'{run["label"]}: invalid_inference_definition: {exc}')
    if numerical:
        failures.append("cross_engine_numerical_disagreement")
    noise = {}
    noise_lanes = {"calibration": calibration, "reference_pairs": lanes["reference"],
                   "all_reference": calibration + lanes["reference"], "fast": lanes["fast"]}
    comparison = tuple(resource_values({}, memory))
    for lane, runs in noise_lanes.items():
        if len(runs) >= 5 and all(finite(resource_values(r, memory)[m], positive=True) for r in runs for m in comparison):
            noise[lane] = baseline_noise([resource_values(r, memory) for r in runs], metrics=comparison)
            if any(not finite(v) or v >= .05 for v in noise[lane].values()):
                failures.append(f"{lane}: noise_not_below_5_percent")
        else:
            noise[lane] = None
            failures.append(f"{lane}: noise_unavailable")
    medians, ratios = {}, {}
    for engine in ("reference", "fast"):
        runs = lanes[engine]
        if runs and all(finite(resource_values(r, memory)[m], positive=True) for r in runs for m in comparison):
            medians[engine] = {m: statistics.median(resource_values(r, memory)[m] for r in runs) for m in comparison}
    if len(medians) == 2:
        ratios = {m: medians["fast"][m] / medians["reference"][m] for m in comparison}
        failures.extend(f"{m}: resource_ratio_above_1.05" for m, v in ratios.items() if v > RESOURCE_RATIO_LIMIT)
    else:
        failures.append("resource_medians_unavailable")
    return {"passed": not failures, "failures": failures, "numerical_disagreements": numerical,
            "noise": noise, "medians": medians, "fast_over_reference": ratios,
            "engine_repeats_own_bits": repeats,
            "tolerance": {"relative": AGREEMENT_RELATIVE, "absolute": AGREEMENT_ABSOLUTE,
                          "n_r_squared_absolute_per_row": AGREEMENT_ABSOLUTE_PER_ROW,
                          "basis": "product per-quantity disagreements contract; fixtures, R fixest and 60-digit arithmetic; no CLI override",
                          "standard_errors": "relative only",
                          "covariance": "original bound plus difference / sqrt(diag_i * diag_j) <= relative",
                          "probability": "positive tails relative and log; reference survival tail from declared distribution"},
            "resource_ratio_limit": RESOURCE_RATIO_LIMIT, "memory_metric": memory,
            "reference_bit_preservation": "separate v1.9.0 comparison required"}


def pin_input_manifest(manifest: Path, destination: Path):
    manifest_bytes = manifest.read_bytes()
    original_sha = hashlib.sha256(manifest_bytes).hexdigest()
    original = json.loads(manifest_bytes)
    source = Path(original["source"])
    current = source_identity(source)
    payload = validate_family_manifest(manifest)
    if payload != original or source_digest(manifest) != original_sha:
        raise ValueError("input_manifest_changed_during_validation")
    if payload["case"] != "iv":
        raise ValueError("iv_manifest_required")
    registered = payload["source_stat"]
    # A remount can change the device number. Keep the other identity checks
    # and require a full content hash before binding workers to this mount.
    if (source_identity(source) != current
            or current != {**registered, "device": current["device"]}):
        raise ValueError("registered_source_changed")
    if current != registered:
        payload["source_stat"] = current
        manifest_bytes = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    with destination.open("xb") as stream:
        stream.write(manifest_bytes)
    return payload, original_sha, hashlib.sha256(manifest_bytes).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "local/perf-inputs/iv/source.json")
    parser.add_argument("--calibrations", type=int, default=5)
    parser.add_argument("--pairs", type=int, default=5)
    args = parser.parse_args()
    if args.calibrations < 5 or args.pairs < 5:
        parser.error("at least five calibrations and five pairs are required")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {"calibration": [], "pairs": []}
    def save():
        (out / "report.json").write_text(json.dumps(report, indent=2, default=str, allow_nan=False))
    def save_observation(run):
        save()
        if not has_verified_host(run):
            raise RuntimeError(f'{run["label"]}: host_exclusivity_unverified')

    try:
        pinned_manifest = out / "input-manifest.json"
        payload, original_sha, manifest_sha = pin_input_manifest(args.manifest, pinned_manifest)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "backend", "native", "scripts"],
                                        cwd=ROOT, text=True).strip()
        report.update(commit=commit, dirty_product_files=dirty.splitlines(), manifest=str(args.manifest),
                      original_input_manifest_sha256=original_sha, pinned_manifest=str(pinned_manifest),
                      input_manifest_sha256=manifest_sha,
                      input_sha256=payload["sha256"], source_identity=measurement_identity())
        ledger = out / "journal.jsonl"
        save()
        for index in range(args.calibrations):
            run = observe(out, pinned_manifest, "reference", f"calibration-{index}", ledger, commit)
            report["calibration"].append(run)
            save_observation(run)
        for index in range(args.pairs):
            order = ("fast", "reference") if index % 2 == 0 else ("reference", "fast")
            pair = {}
            for engine in order:
                run = observe(out, pinned_manifest, engine, f"pair-{index}-{engine}", ledger, commit)
                if not pair:
                    report["pairs"].append(pair)
                pair[engine] = run
                save_observation(run)
        report["summary"] = evaluate_report(report, memory=GATE_MEMORY)
        report["reference_memory"] = evaluate_report(report, memory=REFERENCE_MEMORY)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError, SystemExit) as exc:
        report["summary"] = {"passed": False, "failures": [f"measurement_aborted: {type(exc).__name__}: {exc}"]}
    save()
    print(json.dumps(report["summary"], indent=2))
    return int(not report["summary"]["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
