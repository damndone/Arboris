"""The one declaration of what every regression-shaped result carries.

Three families used to spell the same eight fields out separately, with a shared
validator that checked two of them.  The other six drifted freely: nothing made
`nobs` mean the same thing in an ordinal packet as in a quantile one, and nothing
would have noticed if one of them stopped emitting `engine`.

Families whose output genuinely differs -- ETS, which has no coefficients, and
the survival evidence packet, which is not a coefficient packet at all -- are not
forced through here.  Making them fit would be the same mistake in the opposite
direction.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The shared core.  One definition; the contracts import it rather than
#: restating it, so a change here reaches all of them at once.
RESULT_ENVELOPE_FIELDS: tuple[str, ...] = (
    "contract",
    "schema_version",
    "model_id",
    "model_type",
    "engine",
    "nobs",
    "coefficients",
    "validation",
)


class ResultEnvelopeError(ValueError):
    """A result packet that does not satisfy the shared core."""


def _require_present(payload: Mapping[str, Any], field: str, packet_name: str) -> Any:
    if field not in payload:
        raise ResultEnvelopeError(f"{packet_name}.{field} is required")
    value = payload[field]
    if value is None:
        raise ResultEnvelopeError(f"{packet_name}.{field} is required")
    return value


#: The identity pair every packet carries, result-shaped or not.  Diagnostics
#: packets share this and nothing else -- they have no coefficients and no
#: model_id -- so they are validated at this level rather than pushed through
#: the full envelope.
RESULT_IDENTITY_FIELDS: tuple[str, ...] = ("contract", "model_type")


def validate_result_identity(
    payload: Mapping[str, Any],
    *,
    packet_name: str,
    expected_contract: str,
    expected_model_type: str,
) -> None:
    """Check only that a packet says what it is."""
    if not isinstance(payload, Mapping):
        raise ResultEnvelopeError(f"{packet_name} must be an object")

    contract = _require_present(payload, "contract", packet_name)
    if not isinstance(contract, str) or not contract:
        raise ResultEnvelopeError(f"{packet_name}.contract must be a non-empty string")
    if contract != expected_contract:
        raise ResultEnvelopeError(f"{packet_name}.contract must be {expected_contract}")

    model_type = _require_present(payload, "model_type", packet_name)
    if not isinstance(model_type, str) or not model_type:
        raise ResultEnvelopeError(f"{packet_name}.model_type must be a non-empty string")
    if model_type != expected_model_type:
        raise ResultEnvelopeError(f"{packet_name}.model_type must be {expected_model_type}")


def validate_result_envelope(
    payload: Mapping[str, Any],
    *,
    packet_name: str,
    expected_contract: str,
    expected_model_type: str,
) -> None:
    """Validate every shared field, not just the two that used to be checked."""
    if not isinstance(payload, Mapping):
        raise ResultEnvelopeError(f"{packet_name} must be an object")

    for field in RESULT_ENVELOPE_FIELDS:
        _require_present(payload, field, packet_name)

    validate_result_identity(
        payload,
        packet_name=packet_name,
        expected_contract=expected_contract,
        expected_model_type=expected_model_type,
    )

    model_id = payload["model_id"]
    if not isinstance(model_id, str) or not model_id:
        raise ResultEnvelopeError(f"{packet_name}.model_id must be a non-empty string")

    engine = payload["engine"]
    if not isinstance(engine, str) or not engine:
        raise ResultEnvelopeError(f"{packet_name}.engine must be a non-empty string")

    schema_version = payload["schema_version"]
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ResultEnvelopeError(f"{packet_name}.schema_version must be an integer")

    nobs = payload["nobs"]
    if not isinstance(nobs, int) or isinstance(nobs, bool) or nobs < 0:
        raise ResultEnvelopeError(f"{packet_name}.nobs must be a non-negative integer")

    if not isinstance(payload["coefficients"], Mapping):
        raise ResultEnvelopeError(f"{packet_name}.coefficients must be an object")

    if not isinstance(payload["validation"], Mapping):
        raise ResultEnvelopeError(f"{packet_name}.validation must be an object")


def project_result_evidence(
    payload: Mapping[str, Any], *, contract: Any = None
) -> dict[str, Any]:
    """Project a result packet into the shape consumers read.

    Driven by the envelope plus whatever else the packet declares, so a family
    the projection has never seen still travels.  The alternative -- a branch per
    family -- is the enumeration matrix that blocks 2 and 3 removed from the
    design layer and from `result_shape`; leaving it here would only relocate
    the cost of adding a family.
    """
    if not isinstance(payload, Mapping):
        raise ResultEnvelopeError("result payload must be an object")

    projected: dict[str, Any] = {
        field: payload.get(field) for field in RESULT_ENVELOPE_FIELDS
    }
    if contract is not None:
        projected["result_shape"] = getattr(contract, "result_shape", None)
        projected["family"] = getattr(contract, "family", None)

    # Family-specific evidence rides along by declaration rather than by a
    # branch: anything the packet carries beyond the shared core is preserved
    # under a single key, so a consumer can find it without knowing the family.
    extras = {
        key: value
        for key, value in payload.items()
        if key not in RESULT_ENVELOPE_FIELDS
    }
    if extras:
        projected["family_evidence"] = extras
    return projected
