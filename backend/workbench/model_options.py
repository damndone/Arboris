"""Canonical, model-agnostic transport for per-model option objects."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .contracts.common.envelope import ContractError, freeze_json, thaw_json


class ModelOptionsError(ValueError):
    """A stable boundary error for malformed generic model options."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def canonicalize_model_options(value: object) -> dict[str, object]:
    """Validate an object and return a recursively key-sorted JSON copy."""

    if not isinstance(value, Mapping):
        raise ModelOptionsError(
            "MODEL_OPTIONS_NOT_OBJECT", "model_options must be a JSON object."
        )
    try:
        frozen = freeze_json(value, "model_options")
        thawed = thaw_json(frozen)
        canonical = json.loads(
            json.dumps(
                thawed,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except (ContractError, TypeError, ValueError) as exc:
        raise ModelOptionsError(
            "MODEL_OPTIONS_INVALID_JSON", "model_options must contain finite JSON values."
        ) from exc
    if not isinstance(canonical, dict):  # Defensive: the input mapping guarantees this.
        raise ModelOptionsError(
            "MODEL_OPTIONS_NOT_OBJECT", "model_options must be a JSON object."
        )
    return canonical


def parse_model_options(raw: str) -> dict[str, object]:
    """Parse the HTTP wire value without accepting lossy or non-JSON forms."""

    text = raw.strip() if isinstance(raw, str) else ""
    if not text:
        return {}
    try:
        value = json.loads(
            text,
            parse_constant=_reject_non_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ModelOptionsError(
            "MODEL_OPTIONS_INVALID_JSON", "model_options must be valid JSON."
        ) from exc
    return canonicalize_model_options(value)


def merge_model_options(
    source: Mapping[str, object], patch: Mapping[str, object]
) -> dict[str, object]:
    """Apply the only allowed rerun merge: one level below model_options."""

    merged = canonicalize_model_options(source)
    merged.update(canonicalize_model_options(patch))
    return canonicalize_model_options(merged)
