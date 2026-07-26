"""Small content-addressed store used by CF1 control records."""

from __future__ import annotations

from typing import Any, Generic, TypeVar


T = TypeVar("T")


class StoreError(ValueError):
    """Raised when a content-addressed identity would be overwritten."""


class ContentAddressedStore(Generic[T]):
    """An in-memory append-only content store for immutable contract values."""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def put(self, value: T) -> str:
        reference = getattr(value, "content_digest", None)
        if not isinstance(reference, str) or len(reference) != 64:
            raise StoreError("stored values must expose a SHA-256 content_digest")
        previous = self._items.get(reference)
        if previous is not None and previous != value:
            raise StoreError("content identity is immutable")
        self._items[reference] = value
        return reference

    def get(self, reference: str) -> T:
        try:
            return self._items[reference]
        except KeyError as error:
            raise KeyError(f"content reference is not present: {reference}") from error

    def contains(self, reference: str) -> bool:
        return reference in self._items

    def __len__(self) -> int:
        return len(self._items)


__all__ = ["ContentAddressedStore", "StoreError"]
