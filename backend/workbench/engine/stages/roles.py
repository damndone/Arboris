from __future__ import annotations

from ...variable_roles import infer_variable_roles
from ..context import ModelingContext, RunEnv


class RoleInferenceStage:
    """Infer variable roles (treatment / control / etc.) for the X columns.

    Extracted verbatim from orchestrator._run_workflow (the variable_roles
    block) as part of the V1.5.4 engine decomposition. Behavior must stay
    byte-identical.
    """

    name = "roles"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        cleaned = ctx.data.frame
        normalized_x = ctx.artifacts["_normalized_x"]
        y_type = ctx.y_type

        variable_roles = infer_variable_roles(cleaned, normalized_x, y_type=y_type)

        ctx.roles = variable_roles
        return ctx
