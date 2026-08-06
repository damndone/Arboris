"""How strongly a result's numbers have been checked, declared once.

Two contracts enforced this independently -- `v186_model_families` and
`survival` -- with the same constants copied into both. Raising the level in one
left the other rejecting the very payload the first now required, which is how
the A3 oracles first landed: green in the family contract, failing every Cox run.

`survival` is imported *by* `v186_model_families`, so the shared definition
cannot live in either. It lives here, below both.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..common.envelope import ContractError

#: Weakest first. `internal_consistency_only` is the truthful default for a
#: family nothing outside this project has checked.
VALIDATION_LEVELS = (
    "internal_consistency_only",
    "external_oracle_within_tolerance",
    "external_oracle_exact",
)

INTERNAL_ONLY = VALIDATION_LEVELS[0]
NOT_VERIFIED = "not_verified"

VALIDATION_FIELDS = {"level", "external_oracle"}


@dataclass(frozen=True)
class ExternalOracle:
    """What a family was checked against, and how closely.

    The tolerance and its cause travel with the claim on purpose. "Verified"
    alone would overstate three of the four v1.8.7 A3 results, which agree with R
    only within a solver tolerance; leaving them at `internal_consistency_only`
    would understate all four.
    """

    level: str
    reference: str
    tolerance: str
    note: str

    def __post_init__(self) -> None:
        if self.level not in VALIDATION_LEVELS:
            raise ContractError(f"unknown validation level: {self.level}")
        if self.level == INTERNAL_ONLY:
            raise ContractError(
                "an ExternalOracle record cannot claim internal consistency only"
            )
        if not self.reference or not self.tolerance:
            raise ContractError("an external oracle must name its reference and tolerance")

    @property
    def statement(self) -> str:
        return f"{self.reference}; agrees to {self.tolerance}"


def check_validation(validation: dict, field_name: str) -> None:
    """Reject a claim its own payload does not support.

    A level beyond internal consistency has to name what backs it: `verified`
    with nothing after it is exactly the unsupported assertion these contracts
    exist to prevent.
    """
    if validation["level"] not in VALIDATION_LEVELS:
        raise ContractError(f"{field_name}.level must be one of {VALIDATION_LEVELS}")
    external = str(validation["external_oracle"]).strip()
    if validation["level"] == INTERNAL_ONLY:
        if external != NOT_VERIFIED:
            raise ContractError(
                f"{field_name}.external_oracle must be {NOT_VERIFIED} without external evidence"
            )
    elif not external or external == NOT_VERIFIED:
        raise ContractError(
            f"{field_name}.external_oracle must name the reference implementation "
            "whenever the level claims one"
        )
