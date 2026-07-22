"""Gate 2 Task 2 — bounded projection with explicit omissions.

Input is a byte copy of the real v1.8.0 ARMA-GARCH run: 59 artifacts, an 11-node
graph, a real data profile. Hand-written fixtures would agree with whatever the
projector assumes, which is the failure this task exists to catch — the guessed
default of "<=5 key artifacts" was off by an order of magnitude against exactly
this data.
"""
import shutil
from pathlib import Path

import pytest

from workbench.agent.context_compiler import (
    BudgetConfig,
    compile_notebook_planning_context,
)

FIXTURE = Path(__file__).parent / "fixtures" / "run_family"
ROOT_RUN = "20260722_043309_451505_f0d8672b"
CHILD_RUN = "20260722_043812_924307_874cc62b"

CONTRACT = {"objective": "VIX volatility", "revision": 3}
FOCUS = {"selected_text": "the conditional variance looks persistent"}


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    project_root = tmp_path / "vix-dofile-repro"
    runs = project_root / "runs"
    runs.mkdir(parents=True)
    for run_dir in sorted(FIXTURE.iterdir()):
        shutil.copytree(run_dir, runs / run_dir.name)
    return project_root


def _compile(project: Path, **overrides):
    kwargs = dict(
        notebook_id="nb_0001",
        run_family_id="run-family:11111111-1111-4111-8111-111111111111",
        active_head_run_id=ROOT_RUN,
        analysis_contract=CONTRACT,
        user_focus=FOCUS,
    )
    kwargs.update(overrides)
    return compile_notebook_planning_context(project, **kwargs)


def test_artifacts_are_counted_in_full_and_summarized_in_part(project: Path) -> None:
    context = _compile(project)

    assert len(context.artifact_summaries) == 5
    assert sum(context.artifact_type_counts.values()) == 59
    assert context.artifact_type_counts["time_series_json"] == 36

    dropped = [o for o in context.omissions if o["section"] == "artifact_summaries"]
    assert dropped == [
        {
            "section": "artifact_summaries",
            "included_count": 5,
            "available_count": 59,
            "reason": "section_budget_exceeded",
        }
    ]


def test_lineage_is_bounded_and_reported(project: Path) -> None:
    context = _compile(project, budget=BudgetConfig(lineage_nodes=4))

    assert len(context.bounded_lineage) == 4
    dropped = [o for o in context.omissions if o["section"] == "bounded_lineage"]
    assert dropped[0]["available_count"] == 11
    assert dropped[0]["included_count"] == 4


def test_nothing_is_dropped_silently(project: Path) -> None:
    """Every truncated section must own an omission record."""
    context = _compile(project, budget=BudgetConfig(lineage_nodes=2, artifact_summaries=1))

    truncated = {
        "bounded_lineage": len(context.bounded_lineage),
        "artifact_summaries": len(context.artifact_summaries),
    }
    reported = {o["section"]: o["included_count"] for o in context.omissions}
    for section, kept in truncated.items():
        assert reported[section] == kept


def test_must_keep_sections_survive_a_starvation_budget(project: Path) -> None:
    """A plan built on a truncated analysis contract is worse than no plan."""
    context = _compile(
        project,
        budget=BudgetConfig(
            dataset_columns=0,
            lineage_nodes=0,
            artifact_summaries=0,
            option_summaries=0,
            total_chars=1,
        ),
    )

    assert context.analysis_contract == CONTRACT
    assert context.user_focus == FOCUS
    assert context.run_family_id.startswith("run-family:")
    assert context.active_head_run_id == ROOT_RUN
    assert context.bounded_lineage == []  # truncation lands only on projectable sections


def test_blocking_diagnostics_are_never_truncated(project: Path) -> None:
    context = _compile(
        project,
        budget=BudgetConfig(total_chars=1),
        diagnostics=[
            {"code": "TS_NONSTATIONARY", "severity": "blocking"},
            {"code": "TS_SMALL_SAMPLE", "severity": "info"},
        ],
    )

    codes = {d["code"] for d in context.diagnostics}
    assert "TS_NONSTATIONARY" in codes


def test_ordering_is_stable_regardless_of_input_order(project: Path) -> None:
    """Sorted-then-cut: which 5 artifacts survive must not depend on readdir."""
    first = _compile(project).artifact_summaries

    scrambled = project.parent / "scrambled"
    shutil.copytree(project, scrambled)
    index = scrambled / "runs" / ROOT_RUN / "artifacts_index.json"
    payload = index.read_text()
    import json

    value = json.loads(payload)
    value["artifacts"] = list(reversed(value["artifacts"]))
    index.write_text(json.dumps(value))

    second = _compile(scrambled).artifact_summaries

    assert [a["artifact_id"] for a in first] == [a["artifact_id"] for a in second]


def test_source_manifest_names_every_source_that_was_read(project: Path) -> None:
    context = _compile(project)

    kinds = {entry["kind"] for entry in context.source_manifest}
    assert {"run", "artifact_index", "graph", "dataset_profile"} <= kinds
    for entry in context.source_manifest:
        assert entry["id"]
        assert entry["hash"]


def test_budget_report_states_actual_usage(project: Path) -> None:
    context = _compile(project)

    assert context.budget_report["content_chars"] == context.content_chars()
    assert context.budget_report["content_chars_budget"] == BudgetConfig().total_chars
    assert context.budget_report["within_budget"] is True
    # The meter excludes only itself, so it must still account for essentially
    # the whole bundle -- a drift here would mean sections escaped measurement.
    assert context.budget_report["content_chars"] > 0.8 * len(context.canonical_json())


def test_real_run_fits_the_budget_and_reports_actual_usage(project: Path, capsys) -> None:
    """Gate 2 Task 6 Step 1 — measure, don't assume.

    The printed usage is the calibration data for the next budget revision. The
    guessed defaults were an order of magnitude off once; the way to not repeat
    that is to keep measuring against a real run.
    """
    context = _compile(project)
    report = context.budget_report

    assert report["within_budget"] is True
    print(
        f"\n[gate2 budget] content_chars={report['content_chars']} "
        f"/ budget={report['content_chars_budget']} "
        f"({100 * report['content_chars'] / report['content_chars_budget']:.1f}%) "
        f"artifacts={len(context.artifact_summaries)}/59 "
        f"lineage={len(context.bounded_lineage)}/11 "
        f"truncated={report['sections_truncated']}"
    )
    captured = capsys.readouterr()
    assert "gate2 budget" in captured.out
