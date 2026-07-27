"""Pure, bounded projection of the MEM1 index into agent context input."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .project_index_contract import ProjectContextFact, ProjectContextIndex, ProjectIndexError


_MAX_FACTS_BUDGET = 128
_MAX_BYTES_BUDGET = 4096


@dataclass(frozen=True, slots=True)
class ProjectionOmission:
    fact_id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"fact_id": self.fact_id, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ProjectContextProjection:
    index_hash: str
    project_id: str
    run_family_id: str
    facts: tuple[ProjectContextFact, ...]
    omissions: tuple[ProjectionOmission, ...]
    truncated: bool
    cross_project_memory_used: bool = False
    cross_project_memory_iteration: bool = False

    @property
    def omitted_count(self) -> int:
        return len(self.omissions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "project-context-projection/v1",
            "index_hash": self.index_hash,
            "project_id": self.project_id,
            "run_family_id": self.run_family_id,
            "facts": [fact.to_dict() for fact in self.facts],
            "omissions": [item.to_dict() for item in self.omissions],
            "truncated": self.truncated,
            "omitted_count": self.omitted_count,
            "memory_authority": "non_authoritative",
            "cross_project_memory_used": self.cross_project_memory_used,
            "cross_project_memory_iteration": self.cross_project_memory_iteration,
        }


def project_index_to_context(
    index: ProjectContextIndex,
    *,
    max_facts: int,
    max_bytes: int,
) -> ProjectContextProjection:
    if not isinstance(index, ProjectContextIndex):
        raise ProjectIndexError("index must be a ProjectContextIndex")
    if not isinstance(max_facts, int) or isinstance(max_facts, bool) or not 0 <= max_facts <= _MAX_FACTS_BUDGET:
        raise ProjectIndexError("max_facts budget is invalid")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 128 <= max_bytes <= _MAX_BYTES_BUDGET:
        raise ProjectIndexError("max_bytes budget is invalid")

    selected: list[ProjectContextFact] = []
    omissions: list[ProjectionOmission] = []
    for fact in index.facts:
        if len(selected) >= max_facts:
            omissions.append(ProjectionOmission(fact.fact_id, "fact_budget"))
            continue
        candidate = ProjectContextProjection(
            index_hash=index.content_hash,
            project_id=index.project_id,
            run_family_id=index.run_family_id,
            facts=tuple(selected + [fact]),
            omissions=(),
            truncated=False,
        )
        encoded = json.dumps(candidate.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > max_bytes and selected:
            omissions.append(ProjectionOmission(fact.fact_id, "byte_budget"))
            continue
        if len(encoded) > max_bytes:
            omissions.append(ProjectionOmission(fact.fact_id, "byte_budget"))
            continue
        selected.append(fact)
    return ProjectContextProjection(
        index_hash=index.content_hash,
        project_id=index.project_id,
        run_family_id=index.run_family_id,
        facts=tuple(selected),
        omissions=tuple(omissions),
        truncated=bool(omissions),
    )


__all__ = [
    "ProjectContextProjection",
    "ProjectionOmission",
    "project_index_to_context",
]
