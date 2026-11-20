"""Recompute the expanded reference-comparison failures without weakening their limits.

Run: LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python tests/fixtures/fast_engine_iv_independent/generate_reference_gaps.py
Decimal moment arithmetic at two precisions supplies covariances/statistics; R supplies tails.
The original input generator and the observed fast/reference numbers are retained separately.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from scripts.oracles.iv_high_precision import high_precision
from test_fast_engine_iv import DESIGNS, _design, _fast, _reference
from workbench.estimation_engine.iv import comparable_numbers, disagreements


def main():
    records = []
    for rows, case, kind in [(20000, "just", "robust"), (30, "two_endogenous", "robust"),
                             (400, "two_endogenous", "robust"), (20000, "just", "unadjusted"),
                             (400, "over", "unadjusted"), (400, "two_endogenous", "unadjusted")]:
        data = _design(rows, rows+len(case), scale=1e6)
        endog, instruments = DESIGNS[case]
        hp = high_precision(data, endog, instruments, kind)
        higher = high_precision(data, endog, instruments, kind, precision=110)
        assert hp == higher
        native = comparable_numbers(_fast(data, endog, instruments, kind))
        reference = comparable_numbers(_reference(data, endog, instruments, kind))
        failures = disagreements(native, reference, rows)
        fields = []
        for failure in failures:
            name = failure.split(": fast ", 1)[0]
            expression = None
            if name.startswith("pvalues."):
                t = hp[name.replace("pvalues.", "tstats.", 1)]
                expression = f"2*pnorm(-abs({t!r}))"
            elif name.startswith("first_stage.") and name.endswith(".pval"):
                prefix = name.removesuffix(".pval")
                expression = f"pchisq({hp[prefix]!r}, {hp[prefix+'.df']!r}, lower.tail=FALSE)"
            elif name == "wu_hausman.pval":
                prefix = "wu_hausman_excluded_projection"
                expression = f"pf({hp[prefix]!r}, {hp[prefix+'.df']!r}, {hp[prefix+'.df_denom']!r}, lower.tail=FALSE)"
            if expression:
                output = subprocess.run(["Rscript", "-e", f"cat(sprintf('%.17g', {expression}))"],
                                        check=True, text=True, capture_output=True)
                expected = float(output.stdout)
            else:
                expected = hp[name]
            fields.append(dict(field=name, fast=native[name], reference=reference[name], independent=expected,
                               independent_method="R upper tail from stable Decimal statistic" if expression else "Decimal IV moments",
                               r_expression=expression, reference_agreement=False,
                               independent_covariance_scale=(math.sqrt(hp[f"cov.{name.split('.')[1]}.{name.split('.')[1]}"]
                                                                       * hp[f"cov.{name.split('.')[2]}.{name.split('.')[2]}"])
                                                             if name.startswith("cov.") else None),
                               fast_absolute_error=abs(native[name]-expected),
                               fast_relative_error=abs(native[name]-expected)/abs(expected),
                               reference_relative_error=abs(reference[name]-expected)/abs(expected)))
        records.append(dict(rows=rows, seed=rows+len(case), case=case, shape="scaled", covariance=kind,
                            input_array_sha256=hashlib.sha256(data.to_numpy().tobytes()).hexdigest(),
                            precision=[80, 110], precision_stable_as_float=True, reference_agreement=False,
                            reference_failures=failures, fields=fields))
    Path(__file__).with_name("reference_gaps.json").write_text(json.dumps(dict(
        generator="tests/fixtures/fast_engine_iv_independent/generate_reference_gaps.py",
        definition="Compatibility failures remain failures; independent accuracy is a separate gate.",
        r_environment=json.loads(Path(__file__).with_name("oracle.json").read_text())["meta"]["environment"],
        cases=records), indent=2)+"\n")


if __name__ == "__main__":
    main()
