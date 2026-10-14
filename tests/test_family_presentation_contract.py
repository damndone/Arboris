"""Legacy result aliases and request metadata keep their declared semantics."""
from dataclasses import replace
from types import SimpleNamespace



def test_result_presentation_preserves_legacy_summary_diagnostics_and_claim_scope():
    from workbench.contracts.model.presentation import diagnostic_family, model_summary, result_presentation
    expected = {
        "ols": ("ols", "OLS (HC1, n=8)", "difference"),
        "ols_robust": ("ols", "OLS (HC1, n=8)", "difference"),
        "ols_hac": ("ols", "OLS (HC1, n=8)", "difference"),
        "logit": ("logit", "Logit (n=8)", "log_odds"),
        "poisson": ("poisson", "Poisson (n=8)", "log_count"),
        "poisson_rate": ("poisson", "Poisson rate (exposure=time, n=8)", "log_count"),
        "probit": ("probit", None, "difference"),
        "negative_binomial": ("negative_binomial", None, "difference"),
        "future_family": ("future_family", None, "difference"),
    }
    for name, (diagnostic, summary, interpretation) in expected.items():
        assert diagnostic_family({"model_type": name}) == diagnostic
        assert model_summary(name, {}, robust_se_dp=None, exposure_col="time", fallback_n=8) == summary
        assert result_presentation(name).coefficient_interpretation == interpretation
    assert diagnostic_family({"model_type": "glm", "glm_family": "binomial"}) == "binomial"
    assert diagnostic_family({"model_type": "glm", "glm_family": ""}) == "glm"
    assert diagnostic_family({}) == "ols"
    assert diagnostic_family({"model_type": "fixed_effects"}) == "ols"
    assert result_presentation("logit").rare_event_check
    assert not result_presentation("probit").rare_event_check
    dp = SimpleNamespace(reason=SimpleNamespace(chosen_params={"variant": "HAC"}), selected="HC1")
    assert model_summary("ols", {"nobs": 9}, robust_se_dp=dp, exposure_col=None, fallback_n=8) == "OLS (HAC, n=9)"


def test_request_profile_preserves_source_eligibility_and_covariance_fallbacks(monkeypatch):
    from workbench.contracts.model.execution_profile import request_contract_summary, resolve_request_covariance
    from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS
    def summary(family, covariance):
        return request_contract_summary(family, covariance, entity_col="id", y="y", x=["x"])
    assert summary("ols", "unadjusted") == {
        "contract_version": "ols_result_contract_v1", "model": "ols", "model_type": "ols",
        "covariance": "unadjusted", "covariance_applies": True, "covariance_explicit": True,
        "entity_col": "id", "y": "y", "x": ["x"], "source_eligible": True,
    }
    assert not summary("ols", "robust")["source_eligible"]
    assert not summary("logit", "unadjusted")["source_eligible"]
    assert summary("auto", "")["covariance"] == "robust"
    assert summary("anova", "robust")["covariance"] is None
    from workbench.contracts.model.ols import effective_panel_covariance, effective_ols_covariance
    for family in ("panel_ols", "did"):
        for covariance in ("", "robust", "unadjusted"):
            assert resolve_request_covariance(family, covariance, {}) == effective_panel_covariance(covariance, {})[0]
    options = {"covariance": "hac", "hac_lags": 2, "time_order": "t"}
    assert resolve_request_covariance("ols", "", options) == effective_ols_covariance("", options)
    assert resolve_request_covariance("ols", "", {}) == ""
    assert resolve_request_covariance("future_family", "custom", {}) == "custom"
    declared = replace(MODEL_FAMILY_CONTRACTS["ols"], family="future_family", request_contract_version="future_v1", source_eligible_covariances=("custom",), request_covariance=lambda covariance, options: "custom")
    monkeypatch.setitem(MODEL_FAMILY_CONTRACTS, "future_family", declared)
    assert summary("future_family", "custom")["source_eligible"]
    assert summary("future_family", "custom")["contract_version"] == "future_v1"
    assert resolve_request_covariance("future_family", "", {}) == "custom"


def test_shared_consumers_read_result_declarations(monkeypatch):
    from workbench.contracts.model.presentation import RESULT_PRESENTATIONS, ResultPresentation
    from workbench.orchestrator._reliability_checks import _diagnostic_family
    from workbench.orchestrator._report_build import _model_summary
    from workbench.narrative.claims import build_claims
    monkeypatch.setitem(RESULT_PRESENTATIONS, "future_family", ResultPresentation(diagnostic_family="declared", summary=lambda result, decision, exposure, n: f"Future (n={n})"))
    assert _diagnostic_family({"model_type": "future_family"}) == "declared"
    assert _model_summary("future_family", {}, robust_se_dp=None, exposure_col=None, fallback_n=7) == "Future (n=7)"
    monkeypatch.setitem(RESULT_PRESENTATIONS, "future_family", ResultPresentation(coefficient_interpretation="log_count"))
    claims = build_claims([{"coefficients": {"x": {"estimate": 0.4, "p_value": 0.01, "source_id": "coefficient:x"}}}], [], model_type="future_family")
    assert "expected count" in str(claims)
