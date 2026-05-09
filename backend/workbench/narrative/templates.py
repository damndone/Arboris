TEMPLATES: dict[str, dict] = {
    "treatment_proxy_high": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": ["r", "treatment", "proxy"],
        "text": (
            "{treatment} and {proxy} are highly correlated (r = {r}). "
            "Interpret their coefficients jointly. The coefficient of {treatment} "
            "should not be treated as a clean treatment effect unless the role of "
            "{proxy} is justified."
        ),
    },
    "treatment_proxy_moderate": {
        "category": "diagnostic",
        "severity": "CAUTION",
        "required_params": ["r", "treatment", "proxy"],
        "text": (
            "{treatment} and {proxy} are moderately correlated (r = {r}). "
            "Interpret their coefficients with awareness of potential overlap."
        ),
    },
    "categorical_auto_dummy": {
        "category": "diagnostic",
        "severity": "INFO",
        "required_params": ["variable", "n_levels", "reference"],
        "text": (
            "{variable} was detected as categorical and automatically dummy-coded "
            "into {n_levels} levels, using {reference} as the reference category."
        ),
    },
    "categorical_candidate": {
        "category": "diagnostic",
        "severity": "CAUTION",
        "required_params": ["variable", "nunique"],
        "text": (
            "{variable} may be categorical ({nunique} unique values). "
            "Consider whether it represents distinct categories rather than a continuous scale."
        ),
    },
    "cook_distance_screening": {
        "category": "diagnostic",
        "severity": "CAUTION",
        "required_params": ["n_exceed", "threshold", "max_d"],
        "text": (
            "{n_exceed} observations exceed the conservative screening threshold "
            "(4/n = {threshold}). However, no single observation dominates the model "
            "(max Cook's D = {max_d}, well below 0.5). "
            "This is a standard screening check, not a model failure."
        ),
    },
    "cook_distance_high": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": ["max_d", "n_severe"],
        "text": (
            "{n_severe} observation(s) have high Cook's D (max = {max_d}). "
            "These observations have disproportionate influence and should be examined."
        ),
    },
    "rare_event_low_epp": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": ["event_rate", "epp", "positive_count"],
        "text": (
            "Only {positive_count} positive cases ({event_rate:.1%}) with "
            "{epp:.1f} events per predictor. Estimates may be unstable. "
            "Consider penalized logistic regression (Firth) or exact logistic."
        ),
    },
    "variable_dropped_control": {
        "category": "diagnostic",
        "severity": "CAUTION",
        "required_params": ["variable"],
        "text": (
            "{variable} was dropped from the model due to collinearity or zero variance."
        ),
    },
    "variable_dropped_core": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": ["variable"],
        "text": (
            "{variable} is a main/core variable and was dropped from the model. "
            "The model structure may be significantly affected."
        ),
    },
    "exposure_detected_not_used": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": ["variable"],
        "text": (
            "{variable} appears to be an exposure/offset variable, but offset handling "
            "is not yet supported in this version. Count-model coefficients may be biased "
            "if exposure duration differs across observations."
        ),
    },
    "id_variable_as_predictor": {
        "category": "diagnostic",
        "severity": "CAUTION",
        "required_params": ["variable"],
        "text": (
            "{variable} appears to be an ID variable but is being used as a predictor. "
            "This may cause overfitting or spurious significance."
        ),
    },
    "perfect_separation": {
        "category": "diagnostic",
        "severity": "BLOCKER",
        "required_params": [],
        "text": "Perfect separation detected in logistic regression. Coefficient estimates are unreliable. Consider penalized regression or additional data."
    },
    "quasi_separation": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": [],
        "text": "Quasi-complete separation detected. Standard errors may be inflated. Consider penalized logistic regression."
    },
    "overdispersion_detected": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": ["ratio"],
        "text": (
            "Overdispersion detected (ratio = {ratio:.2f}). "
            "Poisson standard errors may be underestimated. Consider Negative Binomial or robust SE."
        ),
    },
    "heteroskedasticity_detected": {
        "category": "diagnostic",
        "severity": "CAUTION",
        "required_params": [],
        "text": (
            "Heteroskedasticity detected (Breusch-Pagan p < 0.05). "
            "Robust standard errors have been applied."
        ),
    },
    "heteroskedasticity_detected_no_robust": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": [],
        "text": (
            "Heteroskedasticity detected and robust SE not applied. "
            "Standard errors may be unreliable."
        ),
    },
    "residual_non_normality": {
        "category": "diagnostic",
        "severity": "CAUTION",
        "required_params": [],
        "text": "Residuals are not normally distributed (Jarque-Bera p < 0.05). For large samples this is usually not a concern."
    },
    "autocorrelation_detected": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": ["dw"],
        "text": (
            "Autocorrelation detected (Durbin-Watson = {dw:.3f}). "
            "Standard errors may be underestimated for time-series data."
        ),
    },
    "high_vif": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": ["variable", "vif"],
        "text": (
            "{variable} has high multicollinearity (VIF = {vif:.1f}). "
            "Its coefficient standard error may be inflated."
        ),
    },
    "moderate_vif": {
        "category": "diagnostic",
        "severity": "CAUTION",
        "required_params": ["variable", "vif"],
        "text": (
            "{variable} has moderate multicollinearity (VIF = {vif:.1f}). "
            "Interpret with some caution."
        ),
    },
    "binary_correlation": {
        "category": "diagnostic",
        "severity": "CAUTION",
        "required_params": ["var1", "var2", "r"],
        "text": (
            "{var1} and {var2} are correlated binary variables (r = {r:.3f}). "
            "Interpret their coefficients jointly."
        ),
    },
    "binary_correlation_high": {
        "category": "diagnostic",
        "severity": "WARNING",
        "required_params": ["var1", "var2", "r"],
        "text": (
            "{var1} and {var2} are highly correlated binary variables (r = {r:.3f}). "
            "This may indicate redundancy or near-identity."
        ),
    },
    "coef_continuous_association": {
        "category": "coefficient",
        "required_params": ["variable", "estimate", "p_label", "y"],
        "text": (
            "Holding other selected regressors constant, each one-unit increase in "
            "{variable} is associated with an average change of {estimate} in {y}. "
            "This association is {p_label}."
        ),
    },
    "coef_binary_association": {
        "category": "coefficient",
        "required_params": ["variable", "estimate", "p_label"],
        "text": (
            "Holding other selected regressors constant, the presence of {variable} "
            "is associated with an estimated change of {estimate} compared to its absence. "
            "This association is {p_label}."
        ),
    },
    "coef_warn_joint": {
        "category": "coefficient",
        "required_params": ["variable", "estimate", "p_label"],
        "text": (
            "Holding other selected regressors constant, {variable} is associated with "
            "an estimated change of {estimate}. This result is {p_label}, but should be "
            "interpreted jointly with the related variable — do not interpret independently."
        ),
    },
    "coef_categorical": {
        "category": "coefficient",
        "required_params": ["variable", "level", "estimate", "p_label", "reference"],
        "text": (
            "The {variable}[{level}] coefficient ({estimate}) represents the difference "
            "from the reference category ({reference}). This association is {p_label}."
        ),
    },
    "causal_caution_default": {
        "category": "report",
        "required_params": [],
        "text": (
            "These estimates are associations, not necessarily causal effects. "
            "Statistical significance does not imply causality."
        ),
    },
    "causal_caution_with_treatment": {
        "category": "report",
        "required_params": [],
        "text": (
            "Because this model includes a treatment-like variable, causal interpretation "
            "requires additional design assumptions such as random assignment, parallel trends, "
            "valid controls, or an explicit identification strategy. The treatment coefficient "
            "should not be interpreted as a standalone causal effect."
        ),
    },
    "panel_pooled_note": {
        "category": "diagnostic",
        "severity": "INFO",
        "required_params": ["model_type"],
        "text": (
            "Dataset detected as panel-like, but this run used a pooled {model_type} model "
            "without fixed effects or clustered standard errors."
        ),
    },
    "coerced_dtype_note": {
        "category": "diagnostic",
        "severity": "INFO",
        "required_params": ["variable"],
        "text": (
            "{variable} was automatically converted to numeric format."
        ),
    },
}
