"""Publish scoped claim checks through the existing public evidence owner."""
from .statistical_claims import StatisticalClaimError, check_model_claims
from .tools import ToolDefinition, ToolVisibleError


def statistical_claim_tool(provider, *, session_id):
    def check(arguments, context):
        if context.session_id != session_id:
            raise ToolVisibleError("MODEL_CLAIMS_SESSION_MISMATCH: use the current session's tools.")
        try:
            result = check_model_claims(provider, **arguments)
        except StatisticalClaimError as exc:
            raise ToolVisibleError(f"{exc.code}: {exc}") from exc
        if result.get("provider_error"):
            result["provider_error"] = {"type": result["provider_error"]["type"],
                                        "message": "The selected public evidence is unavailable."}
        return result

    return ToolDefinition(
        tool_id="check_model_claims", version="v1", side_effect="none",
        scope_requirements=("project",), max_output_budget=24_000,
        description="Compare explicitly supplied raw-valued nobs or coefficient claims with one exact persisted run/model. "
                    "Use exact stored terms and public raw values; nobs is an integer. Missing evidence is unverifiable. "
                    "This does not validate omitted text, rounding, independent units, method suitability or causality.",
        input_schema={"type": "object", "required": ["run_id", "model_id", "claims"],
            "properties": {
                "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                "model_id": {"type": "string", "minLength": 1, "maxLength": 200},
                "claims": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
                    "type": "object", "required": ["field", "reported"], "properties": {
                        "field": {"type": "string", "enum": ["nobs", "estimate", "std_error", "p_value", "ci_lower", "ci_upper"]},
                        "reported": {"type": ["number", "null"]},
                        "term": {"type": "string", "minLength": 1, "maxLength": 300},
                        "text": {"type": "string", "minLength": 1, "maxLength": 300},
                    }, "additionalProperties": False}},
            }, "additionalProperties": False}, handler=check)
