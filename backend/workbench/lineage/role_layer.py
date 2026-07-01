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


def canonicalize_focal_x(raw: "str | list[str] | None", resolved_rhs: list[str]) -> list[str]:
    """Parse focal_x once into a canonical, ordered, de-duplicated list.

    Order follows resolved_rhs (model-matrix order), NOT user input order.
    Column names are case-sensitive; tokens not present in resolved_rhs are
    dropped (they cannot be regressors)."""
    if raw is None:
        tokens: list[str] = []
    elif isinstance(raw, str):
        tokens = [t.strip() for t in raw.split(",") if t.strip()]
    else:
        tokens = [str(t).strip() for t in raw if str(t).strip()]
    wanted = set(tokens)
    return [col for col in resolved_rhs if col in wanted]


class RoleConflictError(ValueError):
    """A column was assigned conflicting roles (spec §4.8)."""


@dataclass(frozen=True)
class ResolvedRoleInputs:
    estimator_family: str            # regression | panel | iv | did
    estimator_key: str               # ols | logit | … | cs_did | dcdh
    outcome: str
    rhs: list[str] = field(default_factory=list)      # resolved RHS (already exposure-stripped for poisson)
    focal_x: list[str] = field(default_factory=list)  # canonical; empty for iv/did
    # poisson
    exposure: str | None = None
    # panel / did
    unit: str | None = None
    time: str | None = None
    # iv
    endog: list[str] = field(default_factory=list)
    instruments: list[str] = field(default_factory=list)
    # did / dcdh
    treatment: list[str] = field(default_factory=list)
    cluster: str | None = None


def _a(col: str, role: Role, source: str, ri: ResolvedRoleInputs, dropped: bool = False) -> RoleAssignment:
    return RoleAssignment(column=col, role=role, source=source,
                          estimator_family=ri.estimator_family,
                          estimator_key=ri.estimator_key, dropped=dropped)


def _user_focal_rhs(ri: ResolvedRoleInputs) -> list[RoleAssignment]:
    """Shared rule for user-focal families (regression, poisson, panel)."""
    out = [_a(ri.outcome, Role.OUTCOME, "outcome", ri)]
    if ri.focal_x:
        focal = set(ri.focal_x)
        for col in ri.rhs:
            if col in focal:
                out.append(_a(col, Role.FOCAL, "focal_x", ri))
            else:
                out.append(_a(col, Role.COVARIATES, "rhs", ri))
    else:
        for col in ri.rhs:
            out.append(_a(col, Role.EXPLANATORY_UNSPECIFIED, "rhs", ri))
    return out


def dedup_edges(assignments: list[RoleAssignment]) -> list[RoleAssignment]:
    """Collapse by (column, role, edge_kind); merge sources into provenance."""
    merged: dict[tuple[str, Role, str], RoleAssignment] = {}
    for a in assignments:
        key = (a.column, a.role, a.edge_kind)
        if key in merged:
            prev = merged[key]
            if a.source not in prev.source.split("|"):
                merged[key] = RoleAssignment(
                    column=prev.column, role=prev.role,
                    source=f"{prev.source}|{a.source}",
                    estimator_family=prev.estimator_family,
                    estimator_key=prev.estimator_key,
                    dropped=prev.dropped or a.dropped,
                )
        else:
            merged[key] = a
    return list(merged.values())


# The ONLY multi-role overlaps permitted (spec §4.8). Everything else is a
# hard conflict. Cluster is the one role allowed to overlap a substantive role.
_ALLOWED_OVERLAPS: frozenset[frozenset[Role]] = frozenset({
    frozenset({Role.UNIT, Role.CLUSTER}),
    frozenset({Role.TIME, Role.CLUSTER}),
    frozenset({Role.COVARIATES, Role.CLUSTER}),
})


def validate_role_conflicts(assignments: list[RoleAssignment]) -> list[RoleAssignment]:
    by_col: dict[str, set[Role]] = {}
    for a in assignments:
        by_col.setdefault(a.column, set()).add(a.role)
    for col, roles in by_col.items():
        if len(roles) <= 1:
            continue
        # two mutually-exclusive roles on one column -> always a conflict
        if len(roles & MUTUALLY_EXCLUSIVE) >= 2:
            raise RoleConflictError(
                f"{col!r} holds conflicting roles {sorted(r.value for r in roles)}")
        # any non-allowlisted overlap -> conflict (Cluster is the only role
        # permitted to overlap a substantive role)
        if frozenset(roles) not in _ALLOWED_OVERLAPS:
            raise RoleConflictError(
                f"{col!r} holds non-allowlisted roles {sorted(r.value for r in roles)}")
    return assignments


def derive_roles(ri: ResolvedRoleInputs) -> list[RoleAssignment]:
    if ri.estimator_family == "regression":
        if ri.exposure and ri.exposure in set(ri.focal_x):
            raise RoleConflictError(
                f"exposure column {ri.exposure!r} cannot also be a focal regressor")
        out = _user_focal_rhs(ri)
        if ri.exposure:
            out.append(_a(ri.exposure, Role.EXPOSURE, "exposure_col", ri))
        return validate_role_conflicts(dedup_edges(out))

    if ri.estimator_family == "panel":
        out = _user_focal_rhs(ri)
        if ri.unit:
            out.append(_a(ri.unit, Role.UNIT, "entity", ri))
        if ri.time:
            out.append(_a(ri.time, Role.TIME, "time", ri))
        return validate_role_conflicts(dedup_edges(out))

    if ri.estimator_family == "iv":
        out = [_a(ri.outcome, Role.OUTCOME, "outcome", ri)]
        for col in ri.endog:
            out.append(_a(col, Role.FOCAL, "_iv_endog", ri))
        for col in ri.instruments:
            out.append(_a(col, Role.INSTRUMENTS, "_iv_instruments", ri))
        for col in ri.rhs:
            out.append(_a(col, Role.COVARIATES, "exog", ri))
        return validate_role_conflicts(dedup_edges(out))

    if ri.estimator_family == "did":
        out = [_a(ri.outcome, Role.OUTCOME, "outcome", ri)]
        for col in ri.treatment:        # deterministic order from caller
            out.append(_a(col, Role.TREATMENT, "treatment", ri))
        for col in ri.rhs:
            out.append(_a(col, Role.COVARIATES, "covariates", ri))
        if ri.unit:
            out.append(_a(ri.unit, Role.UNIT, "entity", ri))
        if ri.time:
            out.append(_a(ri.time, Role.TIME, "time", ri))
        if ri.cluster:                  # only when present
            out.append(_a(ri.cluster, Role.CLUSTER, "_cs_cluster_var", ri))
        return validate_role_conflicts(dedup_edges(out))

    raise ValueError(f"unsupported estimator_family {ri.estimator_family!r}")
