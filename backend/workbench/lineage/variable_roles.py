# backend/workbench/lineage/variable_roles.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    OUTCOME = "outcome"
    FOCAL = "focal"
    TREATMENT = "treatment"
    COVARIATES = "covariates"
    EXPLANATORY_UNSPECIFIED = "explanatory_unspecified"
    INSTRUMENTS = "instruments"
    EXPOSURE = "exposure"
    UNIT = "unit"
    TIME = "time"
    CLUSTER = "cluster"


ROLE_EDGE_OP: dict[Role, str] = {
    Role.OUTCOME: "enters_as_outcome",
    Role.FOCAL: "enters_as_focal",
    Role.TREATMENT: "enters_as_treatment",
    Role.COVARIATES: "enters_as_covariates",
    Role.EXPLANATORY_UNSPECIFIED: "enters_as_explanatory_unspecified",
    Role.EXPOSURE: "offsets_as_exposure",
    Role.INSTRUMENTS: "identifies_as_instruments",
    Role.UNIT: "configures_unit",
    Role.TIME: "configures_time",
    Role.CLUSTER: "configures_cluster",
}

# Roles that may hold at most one per column (substantive/identification/offset).
MUTUALLY_EXCLUSIVE: frozenset[Role] = frozenset({
    Role.OUTCOME, Role.FOCAL, Role.TREATMENT, Role.COVARIATES,
    Role.EXPLANATORY_UNSPECIFIED, Role.INSTRUMENTS, Role.EXPOSURE,
})
DIMENSION_ROLES: frozenset[Role] = frozenset({Role.UNIT, Role.TIME, Role.CLUSTER})


def _edge_kind(op: str) -> str:
    for prefix in ("enters_as_", "offsets_as_", "identifies_as_", "configures_"):
        if op.startswith(prefix):
            return prefix
    raise ValueError(f"unknown edge op {op!r}")


@dataclass(frozen=True)
class RoleAssignment:
    column: str
    role: Role
    source: str
    estimator_family: str
    estimator_key: str
    dropped: bool = False

    @property
    def edge_op(self) -> str:
        return ROLE_EDGE_OP[self.role]

    @property
    def edge_kind(self) -> str:
        return _edge_kind(self.edge_op)
