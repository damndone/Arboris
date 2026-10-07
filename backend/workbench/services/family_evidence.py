"""The report's view of a family's evidence: the full declared document.

The report shows a family's evidence in full (the Agent sees a bounded
projection of the same declaration). Which document that is comes from the
family's declaration, not from a table here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..artifacts import read_json
from ..contracts.model.result_envelope_registry import declaration_for


def report_family_evidence(run_root: Path, primary: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(primary, Mapping):
        return None
    declaration = declaration_for(primary.get("kernel_family") or primary.get("model_type"))
    if declaration is None:
        return None
    if declaration.report_document is not None:
        path = run_root / declaration.report_document
        if not path.is_file():
            return None
        loaded = read_json(path)
        return loaded if isinstance(loaded, dict) else None
    if declaration.report_packet_keys:
        return {
            "contract": declaration.contract,
            **{key: primary.get(key) for key in declaration.report_packet_keys},
        }
    return None
