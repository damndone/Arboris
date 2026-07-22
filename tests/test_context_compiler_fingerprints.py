"""Gate 2 Task 3 — two fingerprints, and why they cannot be one (spec §4.0).

`test_sibling_options_do_not_stale_each_other` is the 命门. The compiled context
contains the notebook's existing options, so if freshness were computed over the
whole context, generating three options would immediately stale all three —
including the one just created. Every other test here defends the boundary that
makes that impossible: a strict whitelist for freshness, everything else only in
the generation hash.
"""
import shutil
from pathlib import Path

import pytest

from workbench.agent.context_compiler import (
    FRESHNESS_DEPENDENCY_FIELDS,
    compile_notebook_planning_context,
    freshness_dependency_fingerprint,
    generation_context_hash,
)

FIXTURE = Path(__file__).parent / "fixtures" / "run_family"
ROOT_RUN = "20260722_043309_451505_f0d8672b"
CHILD_RUN = "20260722_043812_924307_874cc62b"


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
        analysis_contract={"objective": "VIX volatility", "revision": 3},
        user_focus={"selected_text": "persistent conditional variance"},
    )
    kwargs.update(overrides)
    return compile_notebook_planning_context(project, **kwargs)


def test_sibling_options_do_not_stale_each_other(project: Path) -> None:
    """The 命门: generating options must not invalidate the options."""
    before = _compile(project)
    pinned = freshness_dependency_fingerprint(before)

    after = _compile(
        project,
        existing_option_summaries=[
            {"option_id": "opt_1", "batch": "b1", "rank": 1},
            {"option_id": "opt_2", "batch": "b1", "rank": 2},
            {"option_id": "opt_3", "batch": "b1", "rank": 3},
        ],
    )

    assert freshness_dependency_fingerprint(after) == pinned
    # ...while the generation hash *does* move, because the agent now sees more.
    assert generation_context_hash(after) != generation_context_hash(before)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"analysis_contract": {"objective": "VIX volatility", "revision": 4}}, id="contract_revision"),
        pytest.param({"active_head_run_id": CHILD_RUN}, id="active_head"),
        pytest.param({"run_family_id": "run-family:22222222-2222-4222-8222-222222222222"}, id="run_family"),
        pytest.param({"user_focus": {"selected_text": "something else entirely"}}, id="selected_text"),
        pytest.param({"available_capabilities": ["ts.arma_garch@2"]}, id="capabilities"),
    ],
)
def test_whitelisted_changes_move_the_fingerprint(project: Path, overrides: dict) -> None:
    base = freshness_dependency_fingerprint(_compile(project))

    assert freshness_dependency_fingerprint(_compile(project, **overrides)) != base


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"trace_id": "trace_other"}, id="trace_id"),
        pytest.param(
            {"existing_option_summaries": [{"option_id": "opt_9", "batch": "b2", "rank": 1}]},
            id="sibling_option",
        ),
    ],
)
def test_blacklisted_changes_do_not_move_the_fingerprint(project: Path, overrides: dict) -> None:
    base = freshness_dependency_fingerprint(_compile(project))

    assert freshness_dependency_fingerprint(_compile(project, **overrides)) == base


def test_budget_and_omissions_are_generation_only(project: Path) -> None:
    """Squeezing the budget changes what the agent saw, not whether it still holds."""
    from workbench.agent.context_compiler import BudgetConfig

    base = _compile(project)
    squeezed = _compile(project, budget=BudgetConfig(artifact_summaries=1, lineage_nodes=1))

    assert freshness_dependency_fingerprint(squeezed) == freshness_dependency_fingerprint(base)
    assert generation_context_hash(squeezed) != generation_context_hash(base)


def test_the_two_hashes_are_never_equal(project: Path) -> None:
    context = _compile(project)

    assert freshness_dependency_fingerprint(context) != generation_context_hash(context)


def test_freshness_whitelist_is_declared_not_inferred() -> None:
    """The whitelist is the contract; it must be readable, not scattered."""
    assert FRESHNESS_DEPENDENCY_FIELDS == (
        "analysis_contract",
        "dataset_profile",
        "run_family_id",
        "active_head_run_id",
        "available_capabilities",
        "user_focus",
        "source_manifest",
    )
    for forbidden in ("existing_option_summaries", "budget_report", "omissions", "trace_id"):
        assert forbidden not in FRESHNESS_DEPENDENCY_FIELDS


def test_fingerprint_covers_what_confirm_already_compares(project: Path) -> None:
    """Gate 2 Task 3 Step 5 — the new fingerprint must not contradict confirm().

    `agent/proposals.py: confirm()` gates on two preconditions:
    `context_fingerprint` and `active_head_run_id`. The freshness fingerprint is
    a superset -- it must move whenever either of those would, or the two
    mechanisms would disagree about whether the same option is still valid.
    """
    base = freshness_dependency_fingerprint(_compile(project))

    # active_head_run_id is compared directly by confirm().
    assert freshness_dependency_fingerprint(_compile(project, active_head_run_id=CHILD_RUN)) != base

    # confirm()'s context_fingerprint covers the owner run's node context, which
    # the compiler reads through source_manifest; changing the run's recorded
    # inputs must therefore move the fingerprint too.
    tampered = project.parent / "tampered"
    shutil.copytree(project, tampered)
    manifest_path = tampered / "runs" / ROOT_RUN / "run_manifest.json"
    import json

    manifest = json.loads(manifest_path.read_text())
    manifest["requested_model_type"] = "changed_by_test"
    manifest_path.write_text(json.dumps(manifest))

    assert freshness_dependency_fingerprint(_compile(tampered)) != base
