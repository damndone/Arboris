"""Declared response shapes of the HTTP API (V1812-OPENAPI-TYPES).

Handlers name one of these TypedDicts as their return annotation; see
workbench/http/typed_routes.py for how a declaration is documented in OpenAPI
(and so in the generated frontend types) without changing what is served,
and tests/response_contracts.py for how the suite holds every declaration to
the real responses. A shape used by more than one route is defined once in
``common`` and composed.
"""
