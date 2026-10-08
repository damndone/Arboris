"""V1812-OPENAPI-TYPES: frontend API types are generated and cannot drift.

frontend/src/generated/api-schema.ts is rendered from the backend's OpenAPI by
scripts/generate_api_types.py. A backend change to any request or response
shape changes the rendering, and this test fails until the file is
regenerated. Every operation must declare its success response.
"""

from __future__ import annotations

import copy

import pytest

from scripts import generate_api_types as generator

# Every operation declares its success response (v1.8.12: 132 -> 0).
UNTYPED_BASELINE = 0


@pytest.fixture(scope="module")
def document():
    return generator.openapi()


def _untyped(document: dict) -> list[str]:
    missing = []
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            responses = operation.get("responses", {})
            success = next((responses[code] for code in sorted(responses) if code.startswith("2")), None)
            content = (success or {}).get("content", {})
            if not content:
                if success is not None and "content" not in success and method.upper() == "DELETE":
                    continue  # an explicit no-content response
                missing.append(f"{method.upper()} {path}")
                continue
            schema = content.get("application/json", {}).get("schema")
            if "application/json" in content and (
                not schema or (schema.get("type") == "object" and not schema.get("properties") and not schema.get("$ref"))
            ):
                missing.append(f"{method.upper()} {path}")
    return sorted(missing)


def test_committed_types_match_the_backend(document):
    committed = generator.OUTPUT.read_text(encoding="utf-8")
    assert generator.render(document) == committed, "run python3 scripts/generate_api_types.py"


def test_a_changed_response_field_is_detected(document):
    changed = copy.deepcopy(document)
    schemas = changed["components"]["schemas"]
    name = sorted(schemas)[0]
    schemas[name].setdefault("properties", {})["drift_probe_field"] = {"type": "string"}
    assert generator.render(changed) != generator.OUTPUT.read_text(encoding="utf-8")


def test_every_operation_declares_its_response(document):
    untyped = _untyped(document)
    assert len(untyped) == UNTYPED_BASELINE, "declare a response type for:\n" + "\n".join(untyped)
