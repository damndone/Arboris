"""Auxiliary dispersion inference stays visible without joining beta hypotheses."""
from workbench.agent.family_evidence import bounded_model_family_evidence
from workbench.services.family_evidence import report_family_evidence


def packet():
    return {"model_type":"negative_binomial", "alpha_estimated":True, "alpha_fixed_value":None,
        "dispersion":"mean", "information_matrix":"observed",
        "ancillary_parameters":[{"name":"alpha","scale":"natural","estimate":.7,
            "std_error":.1,"conf_low":.5,"conf_high":.9,"secret":"must omit"}],
        "overdispersion_test":{"statistic":12.,"df":1,"p_value":.0002,
            "distribution":"chibar2(01)","restricted_model":"poisson",
            "log_likelihood_restricted":-100.,"raw_rows":["must omit"]}}


def test_agent_and_report_expose_separate_dispersion_inference(tmp_path):
    primary=packet()
    agent=bounded_model_family_evidence(tmp_path,[primary])
    assert agent["alpha_estimated"] is True
    assert agent["ancillary_parameters"][0]["estimate"] == .7
    assert "secret" not in agent["ancillary_parameters"][0]
    assert agent["overdispersion_test"]["distribution"] == "chibar2(01)"
    assert "raw_rows" not in agent["overdispersion_test"]
    assert report_family_evidence(tmp_path,primary)["ancillary_parameters"] == primary["ancillary_parameters"]


def test_qualified_kernel_family_resolves_glm_fixed_alpha_evidence(tmp_path):
    primary={**packet(),"model_type":"glm","kernel_family":"glm:negative_binomial",
        "alpha_estimated":False,"alpha_fixed_value":1.,"ancillary_parameters":[],"overdispersion_test":None}
    agent=bounded_model_family_evidence(tmp_path,[primary])
    assert agent["alpha_estimated"] is False
    assert agent["alpha_fixed_value"] == 1.
    assert agent["ancillary_parameters"] == []
    assert report_family_evidence(tmp_path,primary)["alpha_fixed_value"] == 1.


def test_agent_numeric_evidence_drops_unrepresentable_values(tmp_path):
    primary=packet()
    primary["alpha_fixed_value"]=10**1000
    primary["ancillary_parameters"][0]["estimate"]=10**1000
    evidence=bounded_model_family_evidence(tmp_path,[primary])
    assert evidence["alpha_fixed_value"] is None
    assert "estimate" not in evidence["ancillary_parameters"][0]
