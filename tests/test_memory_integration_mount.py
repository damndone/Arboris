from workbench.app import app


def test_domain_memory_control_routes_are_mounted_without_execution_routes() -> None:
    paths = set(app.openapi()["paths"])
    assert "/domain-memory/retrieve" in paths
    assert "/domain-memory/candidates" in paths
    assert "/domain-memory/review/candidates/{candidate_id}" in paths
    assert not any(path.startswith("/domain-memory/") and path.endswith("/execute") for path in paths)
