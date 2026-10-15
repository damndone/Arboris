"""The manual result view and Agent share validated LMM coefficients."""
from workbench.http import runs_routes
from workbench.services import lmm_coefficients


def test_run_detail_keeps_packet_and_exposes_matching_coefficient_view(tmp_path, monkeypatch):
    packet = {"model_id": "lmm_1", "model_type": "linear_mixed_effects", "source_contract": "linear_mixed_effects.result"}
    view = {"model_id": "lmm_1", "coefficients": {"Q('time')": {"estimate": 0.4}}}
    monkeypatch.setattr(runs_routes, "_resolve_run_root", lambda *args: tmp_path)
    monkeypatch.setattr(runs_routes, "_read_manifest", lambda *args: {})
    monkeypatch.setattr(runs_routes, "_mark_interrupted_if_dead", lambda *args: None)
    monkeypatch.setattr(runs_routes, "_summarize_manifest", lambda *args, **kwargs: {})
    monkeypatch.setattr(runs_routes, "_model_results", lambda *args: [packet])
    monkeypatch.setattr(runs_routes, "build_diagnostic_summary_preview", lambda *args: {})
    monkeypatch.setattr(runs_routes, "bounded_model_family_evidence", lambda *args: {})
    monkeypatch.setattr(runs_routes, "collect_post_estimation_results", lambda *args, **kwargs: [])
    monkeypatch.setattr(runs_routes, "count_post_estimation_results", lambda *args: 0)
    monkeypatch.setattr(lmm_coefficients, "_lmm_published_results", lambda *args: [view])
    detail = runs_routes.get_run_endpoint("run", str(tmp_path))
    assert detail["model_results"] == [packet]
    assert detail["model_family_evidence"] == view
    assert detail["term_labels"]["Q('time')"] == "time"


def test_agent_and_manual_use_identical_projection():
    from workbench.agent.context_tools_support import coefficients
    assert coefficients._lmm_published_results is lmm_coefficients._lmm_published_results
    assert coefficients._kernel_fixed_effects is lmm_coefficients._kernel_fixed_effects
