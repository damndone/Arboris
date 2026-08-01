"""Published Notebook vocabulary must agree with server-owned contracts."""

from __future__ import annotations

from workbench.agent.notebook.vocabulary import capability_artifact_types
from workbench.agent.recipe_contracts import RECIPE_CONTRACTS


def test_time_series_capability_artifacts_are_published_by_recipe_contracts() -> None:
    for recipe_id, contract in RECIPE_CONTRACTS.items():
        assert dict(capability_artifact_types(recipe_id)) == dict(contract.artifact_types)
