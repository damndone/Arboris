"""Count-family option vocabulary, owned by its statistical contract."""


def build_negative_binomial_option_vocabulary():
    return {"version": "count-model-options/v1", "fields": {
        "dispersion": {"path": "dispersion", "type": "string", "allowed_values": ["mean", "constant"],
            "description": "mean is NB2 (Var=mu+alpha*mu^2); constant is NB1 (Var=(1+delta)*mu). Default NB2 estimates alpha by ML."},
        "alpha": {"path": "alpha", "type": "number", "exclusive_minimum": 0,
            "description": "Advanced fixed positive alpha for NB2 only; omitted or null estimates dispersion. Fixed alpha has no estimated interval or Poisson boundary LR test."}},
        "cross_field_rules": ["Fixed alpha requires dispersion mean; constant estimates delta by ML."],
        "prohibited_claims": ["Do not report fixed alpha as estimated.",
            "Ancillary alpha/delta are excluded from regression coefficient hypotheses."]}


def build_glm_nb_option_vocabulary():
    return {"version": "glm-nb-model-options/v1", "fields": {
        "alpha": {"path": "alpha", "type": "number", "exclusive_minimum": 0,
            "required": True, "description": "Explicit fixed positive alpha, never silently defaulted to 1. Use negative_binomial to estimate alpha by ML."}},
        "cross_field_rules": ["The negative binomial GLM requires explicit fixed alpha."],
        "prohibited_claims": ["Do not claim this GLM estimated alpha."]}
