"""The script-export plan contract (v1.8.11 step 7) round-trips and rejects bad plans."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from workbench.contracts.common.envelope import ContractError
from workbench.script_export.plan import CoverageEntry, ScriptExport, ScriptPlan, ScriptStep

FIXTURE = Path(__file__).parent / "fixtures" / "script_export" / "basic"


def _plan() -> dict:
    return json.loads((FIXTURE / "plan.json").read_text())


def test_fixture_plan_round_trips_and_names_its_source_by_hash():
    raw = _plan()
    plan = ScriptPlan.from_dict(raw)
    assert plan.to_dict() == raw
    source = plan.sources[0]
    assert hashlib.sha256((FIXTURE / source.filename).read_bytes()).hexdigest() == source.sha256


def test_a_step_cannot_refer_to_a_later_or_unknown_input():
    raw = _plan()
    raw["steps"][0]["inputs"] = ["step:ols"]
    with pytest.raises(ContractError, match="unknown inputs"):
        ScriptPlan.from_dict(raw)


def test_operation_prefix_must_match_the_step_kind():
    with pytest.raises(ContractError, match="must start with"):
        ScriptStep(step_id="s", kind="model", operation="data.subset", parameters={}, inputs=())


def test_a_non_native_coverage_entry_must_say_why():
    with pytest.raises(ContractError, match="requires a note"):
        CoverageEntry(step_id="s", operation="model.dcdh", status="snapshot")


def test_fully_native_is_derived_from_coverage():
    native = CoverageEntry(step_id="a", operation="data.subset", status="native")
    snap = CoverageEntry(step_id="b", operation="model.dcdh", status="snapshot", note="Workbench estimator")
    export = ScriptExport("stata", "a.do", "", (native, snap), ("b",), ())
    assert not export.fully_native
    assert ScriptExport("r", "a.R", "", (native,), (), ()).fully_native
