"""v1.8.10 step 1b: one declaration per family, read the same way everywhere.

Separate tables decided what a family's evidence was -- the Agent's, the
report stage's, the run-detail route's -- and a family missing from one was
invisible there. Callaway-Sant'Anna, Sun-Abraham and dCDH were in none. The
Agent, the report stage and the report writer's citable facts now read the
declaration. The run-detail route's merge list and the Table and Report views'
per-family renderers still name four families; they go with the v1.9.0
interface rework.
"""

from __future__ import annotations

import ast
import asyncio
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.agent.context_tools import NodeOperationContextProvider
from workbench.agent.tools import ToolRegistry
from workbench.artifacts import read_json
from workbench.contracts.model.result_envelope_registry import (
    EVIDENCE_KINDS,
    RESULT_ENVELOPE_DECLARATIONS,
    declaration_for,
    declared_families,
)
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

BACKEND = Path(__file__).resolve().parent.parent / "backend" / "workbench"


def test_every_model_family_and_every_model_handler_has_a_declaration() -> None:
    from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS
    from workbench.engine.packs.loader import bootstrap_builtin_packs
    from workbench.engine.registry import MODEL_REGISTRY

    bootstrap_builtin_packs()
    # Other tests register throwaway handlers in the same process; the
    # question is about the handlers the product ships.
    shipped = {
        model_type
        for model_type, handler in MODEL_REGISTRY.items()
        if getattr(handler.fit, "__module__", "").startswith("workbench.")
    }
    missing = sorted(
        model_type
        for model_type in {*MODEL_FAMILY_CONTRACTS, *shipped}
        if declaration_for(model_type) is None
    )
    assert missing == [], f"no result envelope declaration for {missing}"


def test_declarations_agree_with_the_family_contract_result_shape() -> None:
    from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS

    for family, contract in MODEL_FAMILY_CONTRACTS.items():
        assert declaration_for(family).result_shape == contract.result_shape, family


def test_every_evidence_kind_has_an_agent_presentation() -> None:
    from workbench.agent.family_evidence import BOUNDS_BY_KIND

    assert set(BOUNDS_BY_KIND) == set(EVIDENCE_KINDS)


def test_the_agent_projection_never_names_a_family() -> None:
    """A family-name branch is how the three tables drifted in the first place."""
    families = declared_families() | {
        model_type for declaration in RESULT_ENVELOPE_DECLARATIONS.values() for model_type in declaration.model_types
    }
    for module in ("agent/family_evidence.py", "services/family_evidence.py"):
        tree = ast.parse((BACKEND / module).read_text(encoding="utf-8"))
        literals = {
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert not (literals & families), f"{module} names families {sorted(literals & families)}"


def test_the_report_stage_keeps_no_table_of_evidence_files() -> None:
    source = (BACKEND / "engine" / "stages" / "report.py").read_text(encoding="utf-8")
    for declared in {d.report_document for d in RESULT_ENVELOPE_DECLARATIONS.values() if d.report_document}:
        assert declared.split("/")[-1] not in source, f"report.py still hard-codes {declared}"


def _staggered() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    rows = []
    for i in range(40):
        cohort = [0, 2019, 2020, 2021][i % 4]
        fe = float(rng.normal())
        x1 = float(rng.normal())
        for year in range(2017, 2023):
            treated = 1 if (cohort and year >= cohort) else 0
            rows.append({
                "id": f"u{i:02d}", "year": year, "first_treat": cohort, "x1": x1,
                "y": fe + 0.1 * (year - 2017) + 0.3 * x1 + 2.0 * treated + 0.05 * rng.normal(),
            })
    return pd.DataFrame(rows)


def _switching() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    rows = []
    for i in range(40):
        first = [3, 4, 5, 0][i % 4]
        fe = float(rng.normal())
        for year in range(1, 9):
            treated = 1 if (first and year >= first) else 0
            if first and i % 6 == 0 and year >= first + 2:
                treated = 0
            rows.append({"id": f"u{i:02d}", "year": year, "d": treated, "x1": fe,
                         "y": fe + 0.1 * year + 0.8 * treated + 0.05 * rng.normal()})
    return pd.DataFrame(rows)


DID_CASES = [
    ("cs_did", _staggered, {
        "y": "y", "x": ["x1"], "entity_col": "id", "time_col": "year", "did_mode": "cohort",
        "did_cohort_col": "first_treat", "cs_control_group": "never", "cs_est_method": "dr",
        "cs_base_period": "varying",
    }),
    ("sa_did", _staggered, {
        "y": "y", "x": [], "entity_col": "id", "time_col": "year", "did_mode": "cohort",
        "did_cohort_col": "first_treat",
    }),
    ("dcdh", _switching, {
        "y": "y", "x": ["x1"], "entity_col": "id", "time_col": "year", "did_treatment_path": "d",
    }),
]


def _run(tmp_path: Path, frame: pd.DataFrame, model_type: str, kwargs: dict) -> tuple[Path, Path]:
    source = tmp_path / f"{model_type}.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, model_type)
    outcome = run_workflow(project.root, [source], mode="auto", model_type=model_type, **kwargs)
    assert outcome["status"] == "completed", outcome
    return project.root, project.root / "runs" / outcome["run_id"]


def _agent_summary(project_root: Path, run_root: Path, model_type: str) -> dict:
    """What the Agent receives: the tool as registered, under its output budget.

    Reading the provider directly skips the budget projection the Agent's copy
    goes through, and that projection is where the CS evidence was lost.
    """
    registry = ToolRegistry()
    for definition in NodeOperationContextProvider(project_root).tool_definitions(
        chain_id=f"chain:{run_root.name}", session_id="envelope-test"
    ):
        registry.register(definition)
    result = asyncio.run(registry.execute(
        {
            "tool_call_id": "envelope-test",
            "tool_id": "inspect_result_summary",
            "arguments": {
                "owner_run_id": run_root.name, "op_node_id": f"model:{model_type}_1",
                "active_head_run_id": run_root.name,
            },
        },
        session_id="envelope-test",
    ))
    assert result.ok, result.error_details
    return result.output["result_summary"]


@pytest.mark.parametrize(("model_type", "frame", "kwargs"), DID_CASES)
def test_the_agent_can_read_the_did_estimators_it_could_not_read_before(
    tmp_path: Path, model_type: str, frame, kwargs: dict
) -> None:
    project_root, run_root = _run(tmp_path, frame(), model_type, kwargs)
    evidence = _agent_summary(project_root, run_root, model_type)["model_family_evidence"]
    assert isinstance(evidence, dict), "the Agent still cannot read this estimator"

    packet = read_json(run_root / "model_results" / f"{model_type}_1.json")
    att = packet["coefficients"]["ATT"]
    overall = evidence["overall"]
    assert overall["estimate"] == pytest.approx(att["estimate"], rel=1e-12)
    assert overall["std_error"] == pytest.approx(att["std_error"], rel=1e-12)
    if model_type == "dcdh":
        # dCDH reports its overall effect without an interval and marks it
        # experimental; the projection must not invent one.
        assert "ci" not in overall and overall["experimental"] is True
        assert att.get("ci_lower") is None and att.get("ci_upper") is None
    else:
        assert len(overall["ci"]) == 2 and overall["ci"][0] < overall["estimate"] < overall["ci"][1]
        # The coefficient row and the family document are two copies of one
        # result; an Agent shown both must not see an interval in one and
        # "not reported" in the other.
        assert [att["ci_lower"], att["ci_upper"]] == pytest.approx(overall["ci"], rel=1e-12)

    rows = evidence["event_study"]["rows"]
    assert 0 < len(rows) <= 24
    for row in rows:
        assert set(row) >= {"label", "estimate", "std_error", "ci"}
        assert all(isinstance(value, (int, float)) and math.isfinite(value) for value in row["ci"])


def test_the_report_stage_reads_family_evidence_from_the_declaration(tmp_path: Path) -> None:
    model_type, frame, kwargs = DID_CASES[0]
    _, run_root = _run(tmp_path, frame(), model_type, kwargs)
    summary = read_json(run_root / "diagnostic_summary.json")
    evidence = summary.get("model_family_evidence")
    assert isinstance(evidence, dict), "the report has no Callaway-Sant'Anna section"
    document = read_json(run_root / "cs_did.json")
    assert evidence["aggregations"]["simple"]["overall"] == document["aggregations"]["simple"]["overall"]


def test_bounds_keep_the_agent_projection_small(tmp_path: Path) -> None:
    model_type, frame, kwargs = DID_CASES[0]
    project_root, run_root = _run(tmp_path, frame(), model_type, kwargs)
    evidence = _agent_summary(project_root, run_root, model_type)["model_family_evidence"]
    assert len(json.dumps(evidence)) < 16_000


def test_the_agent_reads_the_cs_evidence_of_the_shipped_example_within_its_budget(tmp_path: Path) -> None:
    """Found in the step-1 browser acceptance: on the example dataset the
    summary is larger than the tool's budget, and the family evidence -- the
    interval and the event study the user asked about -- was cut without a
    word, while a run-level ANOVA nobody asked for stayed."""
    example = Path(__file__).resolve().parent.parent / "examples" / "datasets" / "cs_did_staggered.csv"
    project_root, run_root = _run(tmp_path, pd.read_csv(example), "cs_did", {
        "y": "outcome", "x": ["policy_intensity"], "entity_col": "state", "time_col": "year",
        "did_mode": "cohort", "did_cohort_col": "first_treated_year",
        "cs_control_group": "never", "cs_est_method": "dr",
    })
    summary = _agent_summary(project_root, run_root, "cs_did")
    evidence = summary.get("model_family_evidence")
    assert isinstance(evidence, dict), "the Agent's copy lost the Callaway-Sant'Anna evidence"

    document = read_json(run_root / "cs_did.json")
    overall = evidence["overall"]
    assert overall["estimate"] == pytest.approx(document["aggregations"]["simple"]["overall"], rel=1e-12)
    assert len(overall["ci"]) == 2
    expected_rows = len(document["aggregations"]["dynamic"]["event_time"])
    rows = evidence["event_study"]["rows"]
    assert len(rows) == expected_rows, "event-study rows were dropped to fit the budget"


def test_the_report_writer_receives_the_same_family_projection_as_the_agent(tmp_path: Path) -> None:
    """The report writer cites only facts the page hands it. Before v1.8.10
    those came from the graph and the coefficient row, so a written report
    could quote the ATT and nothing of the event study the Agent could read."""
    from fastapi.testclient import TestClient

    from workbench.api import app

    model_type, frame, kwargs = DID_CASES[0]
    project_root, run_root = _run(tmp_path, frame(), model_type, kwargs)
    detail = TestClient(app).get(
        f"/runs/{run_root.name}", params={"project_root": str(project_root)}
    ).json()
    agent = _agent_summary(project_root, run_root, model_type)["model_family_evidence"]
    assert detail["family_evidence"] == agent
