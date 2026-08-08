"""Stable errors for the missing-data pack."""

from __future__ import annotations


class MissingDataPackError(ValueError):
    """A fail-closed missing-data input or statistical-policy rejection."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


__all__ = ["MissingDataPackError"]
