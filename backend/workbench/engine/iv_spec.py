from __future__ import annotations


class IVSpecError(ValueError):
    """Raised when an IV/2SLS specification is invalid. Carries an
    IV_* prefixed message so the estimation failure path surfaces it
    as a structured MODEL_FIT_FAILED with a 'Switch to OLS' recovery."""


def validate_iv_spec(
    y: str,
    exog: list[str],
    endog: list[str],
    instruments: list[str],
) -> None:
    if not endog:
        raise IVSpecError(
            "IV_SPEC_INCOMPLETE: at least one endogenous regressor is required."
        )
    if not instruments:
        raise IVSpecError(
            "IV_SPEC_INCOMPLETE: at least one instrument is required."
        )
    if len(instruments) < len(endog):
        raise IVSpecError(
            "IV_UNDER_IDENTIFIED: the order condition requires "
            f"#instruments ({len(instruments)}) >= #endogenous ({len(endog)})."
        )
    buckets = {"exog": exog, "endog": endog, "instruments": instruments}
    seen: dict[str, str] = {}
    for role, cols in buckets.items():
        for col in cols:
            if col == y:
                raise IVSpecError(
                    f"IV_INVALID_PARTITION: '{col}' is the dependent variable "
                    f"and cannot also be in {role}."
                )
            if col in seen:
                if seen[col] == role:
                    raise IVSpecError(
                        f"IV_INVALID_PARTITION: '{col}' is listed more than "
                        f"once in {role}."
                    )
                raise IVSpecError(
                    f"IV_INVALID_PARTITION: '{col}' appears in both "
                    f"{seen[col]} and {role}; each column has exactly one role."
                )
            seen[col] = role
