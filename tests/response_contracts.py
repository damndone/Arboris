"""Every declared response is checked strictly in the test suite (V1812-OPENAPI-TYPES).

Production serves handlers' return values unvalidated (see
workbench/http/typed_routes.py). Here, ``ResponseContracts`` validates each 2xx
JSON response of a route that declares its type against that type's JSON
Schema, with undeclared fields forbidden: a missing field, a wrong type or an
extra field fails the test that produced it. tests/conftest.py installs the
middleware and fails a test whose requests broke a contract.
"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

VIOLATIONS: list[str] = []
VALIDATED: set[str] = set()  # "METHOD /route" checked against a real response this session
_VALIDATORS: dict[int, Draft202012Validator] = {}


def _strict(schema: Any) -> Any:
    if isinstance(schema, dict):
        schema = {key: _strict(value) for key, value in schema.items()}
        if schema.get("type") == "object" and "properties" in schema:
            schema.setdefault("additionalProperties", False)
        return schema
    if isinstance(schema, list):
        return [_strict(item) for item in schema]
    return schema


def validator_for(documented: Any) -> Draft202012Validator:
    key = id(documented)
    if key not in _VALIDATORS:
        schema = TypeAdapter(documented).json_schema(mode="serialization")
        _VALIDATORS[key] = Draft202012Validator(_strict(schema))
    return _VALIDATORS[key]


def violations(documented: Any, body: Any) -> list[str]:
    found = []
    for error in sorted(validator_for(documented).iter_errors(body), key=lambda item: list(item.absolute_path)):
        # A union reports only that no branch matched; the branch that matched
        # deepest before failing is the one the body was meant to be.
        while error.context:
            # Prefer, at equal depth, a branch that failed on its content over
            # one whose discriminator simply did not match.
            error = max(
                error.context,
                key=lambda branch: (len(branch.absolute_path), branch.validator not in ("const", "enum")),
            )
        where = "/".join(str(part) for part in error.absolute_path) or "(root)"
        message = error.message if len(error.message) <= 300 else f"...{error.message[-240:]}"
        found.append(f"{where}: [{error.validator}] {message}")
    return found


class ResponseContracts:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 0
        json_body = False
        chunks: list[bytes] = []

        async def capture(message: dict[str, Any]) -> None:
            nonlocal status, json_body
            if message["type"] == "http.response.start":
                status = message["status"]
                json_body = dict(message.get("headers", ())).get(b"content-type", b"").startswith(b"application/json")
            elif message["type"] == "http.response.body" and json_body:
                chunks.append(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, capture)
        route = scope.get("route")
        documented = getattr(route, "documented_type", None)
        if documented is None or not json_body or not 200 <= status < 300:
            return
        try:
            body = json.loads(b"".join(chunks))
        except ValueError:
            VIOLATIONS.append(f"{scope['method']} {route.path}: response is not JSON")
            return
        VALIDATED.add(f"{scope['method']} {route.path}")
        for item in violations(documented, body):
            VIOLATIONS.append(f"{scope['method']} {route.path}: {item}")


def install_on_every_app() -> None:
    """Wrap every FastAPI app's middleware stack with ResponseContracts."""

    from fastapi import FastAPI

    if getattr(FastAPI.build_middleware_stack, "_response_contracts", False):
        return
    original = FastAPI.build_middleware_stack

    def build_middleware_stack(self: Any) -> Any:
        stack = original(self)
        return stack if isinstance(stack, ResponseContracts) else ResponseContracts(stack)

    build_middleware_stack._response_contracts = True  # type: ignore[attr-defined]
    FastAPI.build_middleware_stack = build_middleware_stack  # type: ignore[method-assign]
