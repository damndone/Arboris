"""Private helpers shared across diagnostic_preview submodules.

Not part of the public API. Do not import outside the package.
"""
from __future__ import annotations

from typing import Any

SEVERITY_ORDER: dict[str, int] = {"BLOCKER": 4, "WARNING": 3, "CAUTION": 2, "INFO": 1}


def issue_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
