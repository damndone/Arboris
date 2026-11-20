"""Shared constants/helpers for the HTTP layer's route modules."""
from __future__ import annotations

BYTES_PER_GB = 1024**3

# A parent run must be in one of these (non-running) states to be rerun-from.
# Shared by the pipeline-draft (from-node) and rerun routes.
_TERMINAL_RUN_STATUSES = {
    "completed", "failed", "cancelled", "interrupted", "partial", "blocked",
}


def _backfill_schema_values(editable_schema: list, form: dict) -> list:
    """Use the same saved-form projection as from-run draft materialization."""
    from ..services.draft_materialization import _backfill_schema_values as backfill

    return backfill(editable_schema, form)
