"""Shared constants/helpers for the HTTP layer's route modules."""
from __future__ import annotations

import json

BYTES_PER_GB = 1024**3

# A parent run must be in one of these (non-running) states to be rerun-from.
# Shared by the pipeline-draft (from-node) and rerun routes.
_TERMINAL_RUN_STATUSES = {
    "completed", "failed", "cancelled", "interrupted", "partial", "blocked",
}


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
            if key == "x" and copy.get("kind") == "columns":
                raw = form[key]
                if isinstance(raw, list):
                    columns = [str(item).strip() for item in raw if str(item).strip()]
                elif isinstance(raw, str):
                    try:
                        decoded = json.loads(raw)
                    except json.JSONDecodeError:
                        decoded = None
                    if isinstance(decoded, list):
                        columns = [str(item).strip() for item in decoded if str(item).strip()]
                    else:
                        columns = [item.strip() for item in raw.split(",") if item.strip()]
                else:
                    columns = [str(raw).strip()]
                copy["value"] = columns
                copy["options"] = columns
            else:
                copy["value"] = form[key]
        out.append(copy)
    return out
