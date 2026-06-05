from __future__ import annotations

from ..context import ModelingContext, RunEnv


class ReliabilityStage:
    """Build narrative claims and surface model-reliability / data-quality
    issues: rare-event reliability, binary/treatment-proxy correlations,
    suspicious dtypes, categorical candidates, and the panel-pooled note.

    Extracted verbatim from orchestrator._run_workflow (the ``narrative``
    block: ``_s("narrative", "start")`` through the panel-pooled INFO issue,
    i.e. up to — but not including — ``descriptive_stats``) as part of the
    V1.5.4 engine decomposition. Behavior stays byte-identical.

    ``_check_rare_event`` reads the cleaned frame (``cleaned`` — NOT the
    modeling handle ``ctx.data.frame``) and ``primary_type`` from
    ``ctx.primary_type``; the rare-event INFO/WARNING issue is emitted inside
    ``_check_rare_event`` itself. ``reliability_info`` (+ ``caveat``, the
    reliability-driven claim caveat) and the claims are stashed for the
    report stage.
    """

    name = "reliability"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        from ... import orchestrator as _orch
        from ...orchestrator import (
            _check_binary_correlations,
            _check_categorical_candidates,
            _check_rare_event,
            _check_suspicious_dtypes,
            _check_treatment_proxy_correlations,
            _detect_binary_vars,
            _detect_suspicious_vars,
        )
        from ...artifacts import write_json
        from ...domain import GuardrailIssue, Severity

        build_claims = _orch.build_claims

        run_root = env.run_root

        cleaned = ctx.artifacts["_cleaned"]
        normalized_x = ctx.artifacts["_normalized_x"]
        normalized_y = ctx.artifacts["_normalized_y"]
        issue_dicts = ctx.artifacts["_issue_dicts"]
        model_results = ctx.artifacts["_model_results"]
        exposure_col = ctx.exposure_col
        categorical_vars = ctx.artifacts["_categorical_vars"]
        routing = ctx.artifacts["_routing"]

        env.step("narrative", "start", "Building claims...")
        binary_vars = _detect_binary_vars(cleaned, normalized_x)
        _check_binary_correlations(cleaned, binary_vars, issue_dicts, run_root)
        _check_treatment_proxy_correlations(cleaned, normalized_x, issue_dicts, run_root)
        suspicious_vars = _detect_suspicious_vars(normalized_x)
        primary_type = model_results[0][1].get("model_type", "ols") if model_results else "ols"
        effective_exposure_col = exposure_col if primary_type == "poisson_rate" else None
        reliability_info = _check_rare_event(cleaned, normalized_y, primary_type, len(normalized_x), issue_dicts, run_root)
        caveat = ""
        if reliability_info and reliability_info.get("reliability", "").startswith("Low"):
            caveat = "Reliability is limited due to rare events; interpret with caution"
        claims = build_claims(
            [result for _, result in model_results], issue_dicts,
            binary_vars=binary_vars, suspicious_vars=suspicious_vars,
            model_type=primary_type, reliability_caveat=caveat,
            categorical_vars=categorical_vars,
        )
        env.step("narrative", "complete", f"Built {len(claims)} claims")
        _check_suspicious_dtypes(cleaned, normalized_x, issue_dicts, run_root)
        _check_categorical_candidates(
            cleaned,
            issue_dicts,
            run_root,
            encoded_categorical_vars=categorical_vars,
        )
        if routing["kind"] == "panel" and primary_type not in ("fixed_effects", "panel_ols"):
            issue_dicts.append(GuardrailIssue(
                Severity.INFO,
                "PANEL_POOLED_MODEL",
                f"Dataset detected as panel-like, but this run used a pooled {primary_type} model "
                f"without fixed effects or clustered standard errors.",
                {"kind": routing["kind"], "model_type": primary_type},
            ).to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})

        ctx.primary_type = primary_type
        ctx.artifacts["_reliability_info"] = reliability_info
        ctx.artifacts["_caveat"] = caveat
        ctx.artifacts["_claims"] = claims
        ctx.artifacts["_binary_vars"] = binary_vars
        ctx.artifacts["_suspicious_vars"] = suspicious_vars
        ctx.artifacts["_effective_exposure_col"] = effective_exposure_col
        return ctx
