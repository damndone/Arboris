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
# Generic graph node ids are not model families. Keep unknown family ids counted.
FAMILY_LITERAL = re.compile(
    r'"(?!(?:model|table|source|input|dataset)_1")[a-z_]+_1"'
    r'|model_(?:type|family)\s*(?:==|!=)\s*"[a-z_:]+"'
    r'|model_(?:type|family)\s+(?:not\s+)?in\s*[\(\{\[]\s*"'
)

BASELINE = {
    "agent/context_tools_support/model_tools.py": 2,
    "agent/context_tools_support/summaries.py": 1,
    "agent/notebook/materialization.py": 3,
    "agent/notebook/service.py": 1,
    "agent/notebook/vocabulary.py": 1,
    "agent/planner_evaluation.py": 2,
    "agent/recipe_contracts.py": 2,
    "agent/recipes/lmm_public_result_view.py": 2,
    "agent/workflow_capability_adapters.py": 2,
    "agent/workflow_runtime.py": 3,
    "analysis_loop/resolver.py": 1,
    "diagnostic_preview/guidance.py": 1,
    "engine/recommended_actions.py": 5,
    "engine/stages/diagnostics.py": 5,
    "engine/stages/ytype.py": 1,
    "figure_context.py": 1,
    "lineage/role_inputs_from_ctx.py": 2,
    "model_options.py": 1,
    "orchestrator/__init__.py": 3,
    "prediction.py": 5,
    "repository/run_repository.py": 3,
    "services/draft_materialization.py": 2,
    "services/lmm_result_adapter.py": 1,
    "services/run_service.py": 3
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


def test_draft_node_ids_are_not_model_family_identifiers() -> None:
    for node_id in ("model_1", "table_1", "source_1", "input_1", "dataset_1"):
        assert not FAMILY_LITERAL.findall(f'"{node_id}"'), node_id
    for family_id in ("ols_1", "linear_mixed_effects_1", "future_family_1"):
        assert FAMILY_LITERAL.findall(f'"{family_id}"'), family_id
    assert FAMILY_LITERAL.findall('model_type == "future_family"')
