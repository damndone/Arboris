from __future__ import annotations

import pytest

from workbench.agent.runtime_bootstrap import (
    RuntimeBootstrapError,
    compose_builtin_agent_notebook_runtime,
)
from workbench.providers.catalog import load_builtin_catalog
from tests.test_v189_agent_notebook_runtime_bootstrap import _evidence_committer
from tests.v189_cutover_test_host import CutoverTestHostCompiler


def test_runtime_bootstrap_rejects_an_unissued_classification_execution_port() -> None:
    """The shared bootstrap must expose a typed, fail-closed classification seam."""

    with pytest.raises(RuntimeBootstrapError, match="CLASSIFICATION|PORT|server|port"):
        compose_builtin_agent_notebook_runtime(
            provider_catalog=load_builtin_catalog(),
            evidence_committer=_evidence_committer,
            host_compiler=CutoverTestHostCompiler(),
            classification_execution_port=object(),
        )
