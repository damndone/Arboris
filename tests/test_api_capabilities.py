"""API coverage for the V1.5.4.1 capability manifest."""
from __future__ import annotations

import jsonschema
from fastapi.testclient import TestClient

# Importing these modules registers built-in model and imputation handlers.
import workbench.engine.stages.estimation  # noqa: F401
import workbench.engine.stages.imputation  # noqa: F401
from tests.contracts.test_schema_capabilities import SCHEMA
from workbench.api import app
from workbench.engine.capabilities import build_capabilities


def test_get_capabilities_matches_contract_schema():
    response = TestClient(app).get("/capabilities")

    assert response.status_code == 200
    jsonschema.validate(response.json(), SCHEMA)


def test_get_capabilities_returns_derived_manifest():
    response = TestClient(app).get("/capabilities")

    assert response.status_code == 200
    assert response.json() == build_capabilities()
