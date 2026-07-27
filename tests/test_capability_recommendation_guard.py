from __future__ import annotations

from pathlib import Path

import pytest

from test_notebook_capability_binding import _decision, _draft, _service_with_catalog
from tests.test_notebook_support import make_project
from workbench.agent.notebook.errors import OptionBatchInvalid


def test_bound_capability_rejects_legacy_recommendation_before_any_write(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    decision = _decision(context)

    with pytest.raises(OptionBatchInvalid) as caught:
        service.propose_batch(
            notebook.notebook_id,
            context=context,
            drafts=(_draft(capability_id="capability.registered"),),
            batch_id=decision.batch_id,
            recommendation_decision=decision,
        )

    assert caught.value.code == "OPTION_CAPABILITY_BINDING_DECISION_VERSION"
    assert service.store.read_decision(notebook.notebook_id, decision.batch_id) is None
    assert service.store.option_ids(notebook.notebook_id) == []
