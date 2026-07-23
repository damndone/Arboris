"""Typed, deterministic option planning producer."""

from __future__ import annotations

import pytest

from workbench.agent.notebook import generate_option_batch
from workbench.agent.notebook.planning_agent import NotebookPlanningUnavailable


def test_option_producer_does_not_invent_fixed_model_paths() -> None:
    with pytest.raises(NotebookPlanningUnavailable):
        generate_option_batch(notebook_id="nb_producer_test", count=3)


def test_option_producer_requires_a_typed_agent_for_any_count() -> None:
    with pytest.raises(NotebookPlanningUnavailable):
        generate_option_batch(notebook_id="nb_producer_test", count=4)
