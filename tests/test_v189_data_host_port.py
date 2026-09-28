from __future__ import annotations

import pytest


def test_default_data_execution_resolver_rejects_caller_execution_authority() -> None:
    from workbench.services.data_consumer_execution_resolver import (
        DataConsumerExecutionResolverV1,
    )

    resolver = DataConsumerExecutionResolverV1(project_root="/project")

    for forbidden in (
        {"path": "/tmp/source.csv"},
        {"executor": object()},
        {"registry": object()},
        {"arbitrary": object()},
    ):
        with pytest.raises(ValueError, match="DATA_EXECUTION_CALLER_AUTHORITY_FORBIDDEN"):
            resolver.resolve(**forbidden)
