"""Canonical, model-agnostic transport for per-model option objects."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .contracts.common.envelope import ContractError, freeze_json, thaw_json


class ModelOptionsError(ValueError):
    """A stable boundary error for malformed generic model options."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_BINDING_FIELDS = frozenset(
    {
        "owner_model_type",
        "owner_model_id",
        "producer_version",
        "input_contract_version",
        "normalized_options_hash",
    }
)
_SECRET_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
)


@dataclass(frozen=True)
class ModelOptionsContract:
    """Server-owned version facts for one handler's model-options payload."""

    producer_version: str
    input_contract_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.producer_version, str) or not self.producer_version:
            raise ValueError("producer_version must be a non-empty string")
        if (
            not isinstance(self.input_contract_version, str)
            or not self.input_contract_version
        ):
            raise ValueError("input_contract_version must be a non-empty string")


@dataclass(frozen=True)
class ModelOptionsBinding:
    """The server-derived identity and integrity facts for a non-empty payload."""

    owner_model_type: str
    owner_model_id: str
    producer_version: str
    input_contract_version: str
    normalized_options_hash: str

    def to_dict(self) -> dict[str, str]:
        return {
            "owner_model_type": self.owner_model_type,
            "owner_model_id": self.owner_model_id,
            "producer_version": self.producer_version,
            "input_contract_version": self.input_contract_version,
            "normalized_options_hash": self.normalized_options_hash,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ModelOptionsBinding":
        if not isinstance(value, Mapping) or set(value) != _BINDING_FIELDS:
            raise ModelOptionsError(
                "MODEL_OPTIONS_INTEGRITY_ERROR",
                "model_options_binding must contain exactly the server-owned fields.",
            )
        fields = {field: value[field] for field in _BINDING_FIELDS}
        if any(not isinstance(item, str) or not item for item in fields.values()):
            raise ModelOptionsError(
                "MODEL_OPTIONS_INTEGRITY_ERROR",
                "model_options_binding contains invalid owner facts.",
            )
        digest = fields["normalized_options_hash"]
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ModelOptionsError(
                "MODEL_OPTIONS_INTEGRITY_ERROR",
                "model_options_binding has an invalid normalized_options_hash.",
            )
        return cls(**fields)


@dataclass(frozen=True)
class BoundModelOptions:
    """A canonical payload and its optional server-owned sibling binding."""

    payload: dict[str, object]
    binding: ModelOptionsBinding | None


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in _SECRET_KEY_MARKERS):
                raise ModelOptionsError(
                    "MODEL_OPTIONS_SECRET_KEY_FORBIDDEN",
                    "model_options must not contain secret-bearing keys.",
                )
            _reject_secret_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_secret_keys(item)


def canonicalize_model_options(value: object) -> dict[str, object]:
    """Validate an object and return a recursively key-sorted JSON copy."""

    if not isinstance(value, Mapping):
        raise ModelOptionsError(
            "MODEL_OPTIONS_NOT_OBJECT", "model_options must be a JSON object."
        )
    _reject_secret_keys(value)
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


def canonical_options_hash(value: object) -> str:
    """Hash canonical options after JSON validation and key normalization."""

    canonical = canonicalize_model_options(value)
    encoded = json.dumps(
        canonical,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _resolve_model_options_handler(model_type: object) -> object:
    if not isinstance(model_type, str) or not model_type or model_type == "auto":
        raise ModelOptionsError(
            "MODEL_OPTIONS_EXPLICIT_MODEL_REQUIRED",
            "non-empty model_options require an explicit model_type.",
        )

    # Core handlers register on importing the estimation stage; future packs are
    # still loaded only through their declared, idempotent loader boundary.
    from .engine.stages import estimation as _estimation  # noqa: F401
    from .engine.packs.loader import bootstrap_builtin_packs
    from .engine.registry import MODEL_REGISTRY

    bootstrap_builtin_packs()
    key = model_type.split(":", 1)[0] if model_type.startswith("glm:") else model_type
    handler = MODEL_REGISTRY.get(key)
    if handler is None:
        raise ModelOptionsError(
            "MODEL_OPTIONS_OWNER_UNRESOLVED",
            f"model_type {model_type!r} has no registered model-options owner.",
        )
    return handler


def _owner_facts(handler: object) -> tuple[str, str, ModelOptionsContract]:
    validator = getattr(handler, "validate_model_options", None)
    contract = getattr(handler, "model_options_contract", None)
    if validator is None or not isinstance(contract, ModelOptionsContract):
        raise ModelOptionsError(
            "MODEL_OPTIONS_UNSUPPORTED",
            f"Model type {getattr(handler, 'model_type', 'unknown')} does not declare model_options.",
        )
    model_type = getattr(handler, "model_type", None)
    model_id = getattr(handler, "model_id", None)
    if not isinstance(model_type, str) or not model_type or not isinstance(model_id, str) or not model_id:
        raise ModelOptionsError(
            "MODEL_OPTIONS_OWNER_UNRESOLVED",
            "The resolved model handler has incomplete owner identity.",
        )
    return model_type, model_id, contract


def _validate_payload_for_handler(handler: object, payload: dict[str, object]) -> None:
    validator = getattr(handler, "validate_model_options", None)
    if validator is None:
        raise ModelOptionsError(
            "MODEL_OPTIONS_UNSUPPORTED",
            f"Model type {getattr(handler, 'model_type', 'unknown')} does not declare model_options.",
        )
    try:
        validator(payload)
    except (TypeError, ValueError) as exc:
        code = getattr(exc, "error_code", "MODEL_OPTIONS_INVALID_VALUE")
        raise ModelOptionsError(
            code,
            f"Model type {getattr(handler, 'model_type', 'unknown')} rejected model_options: {exc}",
        ) from exc


def bind_new_model_options(model_type: object, value: object) -> BoundModelOptions:
    """Canonicalize, validate, and bind a newly submitted payload server-side."""

    payload = canonicalize_model_options(value)
    if not payload:
        return BoundModelOptions(payload=payload, binding=None)

    handler = _resolve_model_options_handler(model_type)
    owner_model_type, owner_model_id, contract = _owner_facts(handler)
    _validate_payload_for_handler(handler, payload)
    payload = canonicalize_model_options(payload)
    return BoundModelOptions(
        payload=payload,
        binding=ModelOptionsBinding(
            owner_model_type=owner_model_type,
            owner_model_id=owner_model_id,
            producer_version=contract.producer_version,
            input_contract_version=contract.input_contract_version,
            normalized_options_hash=canonical_options_hash(payload),
        ),
    )


def verify_bound_model_options(
    value: object,
    binding_value: object,
) -> BoundModelOptions:
    """Read a persisted non-empty payload without silently repairing integrity."""

    payload = canonicalize_model_options(value)
    if not payload:
        if binding_value is not None:
            raise ModelOptionsError(
                "MODEL_OPTIONS_INTEGRITY_ERROR",
                "empty model_options must not carry model_options_binding.",
            )
        return BoundModelOptions(payload=payload, binding=None)
    if binding_value is None:
        raise ModelOptionsError(
            "MODEL_OPTIONS_OWNER_MISSING",
            "non-empty persisted model_options require a server-owned binding.",
        )
    binding = ModelOptionsBinding.from_dict(binding_value)
    if binding.normalized_options_hash != canonical_options_hash(payload):
        raise ModelOptionsError(
            "MODEL_OPTIONS_INTEGRITY_ERROR",
            "persisted model_options do not match their normalized_options_hash.",
        )
    return BoundModelOptions(payload=payload, binding=binding)


def verify_binding_owner_for_model_type(
    binding: ModelOptionsBinding,
    model_type: object,
) -> None:
    """Require persisted owner facts to match the currently resolved handler."""

    handler = _resolve_model_options_handler(model_type)
    owner_model_type, owner_model_id, contract = _owner_facts(handler)
    expected = (
        owner_model_type,
        owner_model_id,
        contract.producer_version,
        contract.input_contract_version,
    )
    actual = (
        binding.owner_model_type,
        binding.owner_model_id,
        binding.producer_version,
        binding.input_contract_version,
    )
    if actual != expected:
        raise ModelOptionsError(
            "MODEL_OPTIONS_OWNER_MISMATCH",
            "persisted model_options owner does not match the resolved target model.",
        )
