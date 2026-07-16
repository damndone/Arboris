from pathlib import Path


GATE_SCRIPT = Path(__file__).parents[1] / "scripts" / "gate.sh"
VITE_CONFIG = Path(__file__).parents[1] / "frontend" / "vite.config.ts"


def test_gate_script_exposes_explicit_quick_and_full_modes() -> None:
    source = GATE_SCRIPT.read_text()

    assert "--quick" in source
    assert "--full" in source
    assert "--help" in source


def test_quick_mode_has_a_targeted_agent_llm_suite() -> None:
    source = GATE_SCRIPT.read_text()

    assert "tests/test_agent_*.py" in source
    assert "tests/test_llm_*.py" in source


def test_quick_mode_has_a_conservative_full_backend_fallback() -> None:
    source = GATE_SCRIPT.read_text()

    assert "QUICK backend full fallback" in source


def test_quick_mode_covers_request_independent_rerun_service_slice() -> None:
    source = GATE_SCRIPT.read_text()

    assert "backend/workbench/services/rerun_service.py" in source
    assert "backend/workbench/lineage/run_inputs.py" in source
    assert "tests/test_rerun_service.py" in source


def test_quick_mode_covers_known_v17_rerun_lineage_surface() -> None:
    source = GATE_SCRIPT.read_text()

    assert "backend/workbench/services/run_service.py" in source
    assert "backend/workbench/services/results_service.py" in source
    assert "backend/workbench/lineage/node_write_validation.py" in source
    assert "tests/test_api_run_params.py" in source
    assert "tests/test_node_write_validation.py" in source


def test_quick_mode_keeps_agent_http_wiring_in_the_focused_surface() -> None:
    source = GATE_SCRIPT.read_text()

    assert "backend/workbench/http/agent_routes.py" in source
    assert "backend/workbench/app.py" in source


def test_quick_mode_keeps_llm_provider_settings_in_the_focused_surface() -> None:
    source = GATE_SCRIPT.read_text()

    assert "backend/workbench/http/llm_routes.py" in source
    assert "backend/workbench/llm/provider_store.py" in source


def test_quick_mode_runs_gate_contract_tests_when_the_gate_changes() -> None:
    source = GATE_SCRIPT.read_text()

    assert "run_gate_script_tests" in source


def test_vite_proxy_defaults_to_the_documented_backend_port() -> None:
    source = VITE_CONFIG.read_text()

    assert 'process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000"' in source
