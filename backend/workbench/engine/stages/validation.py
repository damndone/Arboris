from __future__ import annotations

from ...artifacts import write_json
from ...validation import has_blockers, validate_profile
from ..context import ModelingContext, RunEnv


class ValidationStage:
    """Validate the data profile and short-circuit on blocker issues.

    Extracted verbatim from orchestrator._run_workflow (the validation block)
    as part of the V1.5.4 engine decomposition. Behavior must stay
    byte-identical.

    A stage cannot ``return`` from ``_run_workflow``, so on blockers this stage
    performs the same side effects (blocked manifest write + recorder flush)
    and signals the early-exit by setting ``ctx.terminal_status = "blocked"``.
    The orchestrator bridge inspects that flag and returns the blocked result.
    """

    name = "validation"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        # Lazy import to avoid a module-load cycle: orchestrator imports this
        # stage at the top of its module, and these helpers live in orchestrator.
        from ...orchestrator import _lineage, _safe_flush_recorder, _write_manifest

        profile = ctx.artifacts["_profile"]
        config = ctx.artifacts["_config"]
        input_files = ctx.artifacts["_input_files"]
        mode = ctx.artifacts["_mode"]
        y = ctx.artifacts["_y"]
        x = ctx.artifacts["_x"]
        model_type = ctx.artifacts["_model_type"]
        started_at = ctx.artifacts["_started_at"]
        run_root = env.run_root
        run_id = env.run_id

        env.step("validation", "start", "Validating profile...")
        issues = validate_profile(profile, config)
        issue_dicts = [issue.to_dict() for issue in issues]
        write_json(run_root / "errors.json", {"issues": issue_dicts})

        ctx.artifacts["_issues"] = issues
        ctx.artifacts["_issue_dicts"] = issue_dicts

        if has_blockers(issues):
            env.step("validation", "blocked", "Validation found blocker issues")
            _write_manifest(
                run_root,
                run_id,
                mode,
                "blocked",
                _lineage(input_files),
                started_at=started_at,
                y=y,
                x=x,
                requested_model_type=model_type,
            )
            _safe_flush_recorder(env.recorder, context="blocked@validation")
            ctx.terminal_status = "blocked"
            return ctx

        env.step("validation", "complete", "Validation passed")
        return ctx
