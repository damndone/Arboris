"""V1812-OPENAPI-TYPES: the canonical v1.8.1 wire fixtures match the declared responses.

frontend/src/notebook/fixtures/canonicalMocks.ts types these JSON files as the
generated response shapes; this test is what makes that typing true.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.response_contracts import violations
from workbench.http.responses.notebook import ExecutionView, MaterializationView, OptionRevision

FIXTURES = Path(__file__).parent / "fixtures" / "contracts" / "v181"


@pytest.mark.parametrize(
    ("name", "declared"),
    [
        ("notebook_option_revision", OptionRevision),
        ("notebook_option_revision_v11", OptionRevision),
        ("option_execution", ExecutionView),
        ("option_execution_v11", ExecutionView),
        ("option_materialization_v1", MaterializationView),
        ("option_materialization_genesis_v1", MaterializationView),
    ],
)
def test_canonical_fixture_satisfies_its_response_contract(name: str, declared: object) -> None:
    payload = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    assert violations(declared, payload) == []
