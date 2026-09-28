#!/usr/bin/env python3
"""Time everyday operations on a 1,000,000-row dataset against budgets.

Builds a scratch project with a 1M x 10 wage dataset, runs one OLS, then
times what a user does next: open the Data view, read variable metadata,
tabulate and summarize, recode and filter, export, read results and the
report's disclosure. Prints a table and exits non-zero when a budget is
missed. Heavy: run it alone on the machine.

    PYTHONPATH=backend .venv/bin/python scripts/perf_1m.py --out /private/tmp/perf-1m
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from workbench import analysis_disclosure, analysis_ledger  # noqa: E402
from workbench.data_operation_registry import get_data_operation  # noqa: E402
from workbench.orchestrator import run_workflow  # noqa: E402
from workbench.projects import create_project  # noqa: E402
from workbench.services.data_export import export_dataset, preview_export  # noqa: E402
from workbench.services.dataset_view import dataset_page, dataset_variables, load_dataset  # noqa: E402
from workbench.services.results_service import read_model_results  # noqa: E402
from workbench.statistical_exploration import ExplorationSpec, execute_exploration  # noqa: E402

ROWS = 1_000_000

# Seconds. Interactive reads must feel instant; one-off heavy work may take a
# while but must stay bounded.
BUDGETS = {
    "ingest + OLS run": 90.0,
    "data view: first page (cold)": 10.0,
    "data view: next page (warm)": 1.0,
    "data view: sorted page": 3.0,
    "variable view": 5.0,
    "tabulate region": 2.0,
    "summarize detail (3 vars)": 5.0,
    "recode age": 3.0,
    "subset filter": 3.0,
    "export preview (dta)": 10.0,
    "export dta": 30.0,
    "export csv": 30.0,
    "read model results": 1.0,
    "ledger: disclosure of 5,000 entries": 1.0,
}


def _dataset(path: Path) -> Path:
    rng = np.random.default_rng(1)
    education = rng.integers(9, 21, ROWS)
    experience = rng.integers(0, 40, ROWS)
    female = rng.binomial(1, 0.5, ROWS)
    region = rng.choice(["north", "south", "east", "west"], ROWS)
    frame = pd.DataFrame(
        {
            "id": np.arange(ROWS),
            "wage": np.round(np.exp(1.2 + 0.08 * education + 0.03 * experience - 0.1 * female + rng.normal(0, 0.35, ROWS)), 2),
            "education": education,
            "experience": experience,
            "age": np.clip(education + experience + 6, 18, 75),
            "female": female,
            "region": region,
            "union": rng.binomial(1, 0.25, ROWS),
            "hours": np.round(rng.normal(40, 6, ROWS), 1),
            "tenure": rng.integers(0, 30, ROWS),
        }
    )
    frame.to_csv(path, index=False)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "perf-1m")
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}

    @contextmanager
    def timed(name: str):
        started = time.perf_counter()
        yield
        timings[name] = time.perf_counter() - started
        print(f"{name:40s} {timings[name]:8.2f}s  (budget {BUDGETS[name]:.1f}s)", flush=True)

    source = _dataset(out / "wages_1m.csv")
    project = create_project(out, f"p{int(time.time())}")
    root = project.root
    with timed("ingest + OLS run"):
        outcome = run_workflow(root, [source], mode="auto", model_type="ols", y="wage",
                               x=["education", "experience", "female", "hours"])
    assert outcome["status"] == "completed", outcome
    run_id = outcome["run_id"]

    with timed("data view: first page (cold)"):
        dataset_page(root, run_id, "stage:raw", offset=0, limit=100)
    with timed("data view: next page (warm)"):
        dataset_page(root, run_id, "stage:raw", offset=500_000, limit=100)
    with timed("data view: sorted page"):
        dataset_page(root, run_id, "stage:raw", offset=0, limit=100, sort_by="wage", descending=True)
    with timed("variable view"):
        dataset_variables(root, run_id, "stage:raw")

    _context, frame = load_dataset(root, run_id, "stage:raw")
    with timed("tabulate region"):
        execute_exploration(frame, ExplorationSpec("tabulate", ("region",)))
    with timed("summarize detail (3 vars)"):
        execute_exploration(frame, ExplorationSpec("summarize_detail", ("wage", "hours", "age")))
    with timed("recode age"):
        get_data_operation("recode").run(frame, {
            "column": "age", "output": "age_group",
            "rules": [{"from": {"low": 18, "high": 29}, "to": 1}, {"from": {"low": 30, "high": 49}, "to": 2},
                      {"from": "else", "to": 3}],
        })
    with timed("subset filter"):
        get_data_operation("subset").run(frame, {
            "columns": ["wage", "education", "region"],
            "filters": [{"column": "age", "op": "between", "value": [25, 55]}, {"column": "region", "op": "eq", "value": "north"}],
        })
    with timed("export preview (dta)"):
        preview_export(root, run_id, "stage:raw", {"format": "dta"})
    with timed("export dta"):
        export_dataset(root, run_id, "stage:raw", {"format": "dta"})
    with timed("export csv"):
        export_dataset(root, run_id, "stage:raw", {"format": "csv"})
    with timed("read model results"):
        read_model_results(root / "runs" / run_id)

    step = analysis_ledger.LedgerStep.of("test.t_tests")
    for index in range(5000):
        analysis_ledger.record(root, analysis_ledger.LedgerEntry(
            actor="agent", authorized_by="read_only_policy", source="operation.multi_step", status="completed",
            steps=(step,), run_id=run_id, source_upload_sha256="x" if index % 2 else None,
        ))
    with timed("ledger: disclosure of 5,000 entries"):
        analysis_disclosure.disclosure(root, run_id)

    missed = {name: value for name, value in timings.items() if value > BUDGETS[name]}
    print()
    print("all within budget" if not missed else f"over budget: {', '.join(missed)}")
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
