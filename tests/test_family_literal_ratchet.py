"""v1.8.10 step 2d: shared code does not learn new model-family names.

Capabilities are matched by declared properties, not by family names. Code
that belongs to one family (its fitting code, its pack, its contract
declarations, the name registry) may name it; shared code should not. The
existing names in shared code are the baseline below. A file that gains one
fails; a file that loses one fails too, so the baseline is lowered in the same
change and the ratchet only ever tightens.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "backend" / "workbench"

# Modules that belong to a family, or declare the families, may name them.
FAMILY_OWNED = (
    "engine/stages/estimation.py",
    "engine/packs/",
    "econometrics/",
    "contracts/model/",
    "orchestrator/_model_types.py",
    "engine/registry.py",
)

# A model id ("ols_1"), or a branch on a family name.
FAMILY_LITERAL = re.compile(
    r'"[a-z_]+_1"'
    r'|model_(?:type|family)\s*(?:==|!=)\s*"[a-z_:]+"'
    r'|model_(?:type|family)\s+(?:not\s+)?in\s*[\(\{\[]\s*"'
)

BASELINE = {
    "agent/context_tools_support/model_tools.py": 2,
    "agent/context_tools_support/summaries.py": 1,
    "agent/notebook/materialization.py": 7,
    "agent/notebook/service.py": 2,
    "agent/notebook/vocabulary.py": 1,
    "agent/planner_evaluation.py": 2,
    "agent/recipe_contracts.py": 2,
    "agent/recipes/lmm_public_result_view.py": 2,
    "agent/workflow_capability_adapters.py": 3,
    "agent/workflow_runtime.py": 3,
    "analysis_loop/resolver.py": 1,
    "diagnostic_preview/guidance.py": 1,
    "engine/recommended_actions.py": 5,
    "engine/stages/diagnostics.py": 5,
    "engine/stages/report.py": 3,
    "engine/stages/source.py": 1,
    "engine/stages/ytype.py": 1,
    "figure_context.py": 1,
    "http/drafts_routes.py": 1,
    "http/runs_routes.py": 7,
    "lineage/pipeline_drafts.py": 15,
    "lineage/role_inputs_from_ctx.py": 2,
    "model_options.py": 1,
    "narrative/claims.py": 2,
    "orchestrator/__init__.py": 8,
    "orchestrator/_reliability_checks.py": 4,
    "orchestrator/_report_build.py": 4,
    "prediction.py": 5,
    "repository/run_repository.py": 3,
    "services/draft_materialization.py": 13,
    "services/draft_service.py": 4,
    "services/lmm_result_adapter.py": 1,
    "services/run_service.py": 6,
}


def _counts() -> dict[str, int]:
    counts = {}
    for path in sorted(ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(FAMILY_OWNED):
            continue
        found = len(FAMILY_LITERAL.findall(path.read_text()))
        if found:
            counts[relative] = found
    return counts


def test_shared_code_names_no_new_model_families() -> None:
    counts = _counts()
    grew = {name: (BASELINE.get(name, 0), found) for name, found in counts.items() if found > BASELINE.get(name, 0)}
    assert not grew, (
        f"family names added to shared code (baseline, now): {grew}. Declare the property the code "
        "needs on the family (result envelope declaration, kernel) and match on that instead."
    )


def test_the_baseline_tightens_when_names_are_removed() -> None:
    counts = _counts()
    shrank = {name: (allowed, counts.get(name, 0)) for name, allowed in BASELINE.items() if counts.get(name, 0) < allowed}
    assert not shrank, f"lower BASELINE to the new counts so the ratchet keeps them: {shrank}"


def test_the_post_estimation_layer_names_no_family() -> None:
    for path in (ROOT / "postestimation").rglob("*.py"):
        assert not FAMILY_LITERAL.findall(path.read_text()), path
    assert not FAMILY_LITERAL.findall((ROOT / "agent" / "postestimation_steps.py").read_text())
