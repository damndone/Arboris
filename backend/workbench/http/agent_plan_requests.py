"""Versioned human plan-edit requests; clients cannot set execution state."""
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentPlanApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(gt=0)


class AgentPlanProposalRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,200}$")
    revision: int = Field(gt=0, strict=True)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class AgentPlanStepEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    operation_ids: list[str] = Field(min_length=1, max_length=40)
    depends_on: list[str] = Field(default_factory=list, max_length=40)
    expected_outputs: list[str] = Field(default_factory=list, max_length=40)
    proposal_ref: AgentPlanProposalRef | None = None


class AgentPlanPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(gt=0)
    question: str | None = Field(default=None, min_length=1, max_length=1000)
    criteria: list[Annotated[str, Field(min_length=1, max_length=300)]] | None = Field(default=None, max_length=12)
    steps: list[AgentPlanStepEdit] | None = Field(default=None, min_length=1, max_length=40)
    completion: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_changes(self):
        changed = self.model_fields_set - {"version"}
        if not changed or any(getattr(self, name) is None for name in changed):
            raise ValueError("provide non-null plan changes, omitting unchanged fields")
        if self.completion is not None:
            from jsonschema import Draft202012Validator
            from ..agent.completion import CONTRACT_SCHEMA
            if not Draft202012Validator(CONTRACT_SCHEMA).is_valid(self.completion):
                raise ValueError("completion must contain supported playbooks and one registered dataset identity")
        return self
