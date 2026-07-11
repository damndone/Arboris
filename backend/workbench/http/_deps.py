"""Shared constants/helpers for the HTTP layer's route modules."""
from __future__ import annotations

BYTES_PER_GB = 1024**3


def _backfill_schema_values(editable_schema: list, form: dict) -> list:
    """2B.4: overlay the run's real form values onto editable_schema[i].value (by key).
    Copies (never mutates the shared capabilities list); missing/empty keys keep the
    capabilities default.

    Shared by the graph annotation (head-set view) and the pipeline-draft routes.
    """
    out = []
    for param in editable_schema:
        copy = dict(param)
        key = copy.get("key")
        if key in form and form[key] not in (None, ""):
            copy["value"] = form[key]
        out.append(copy)
    return out
