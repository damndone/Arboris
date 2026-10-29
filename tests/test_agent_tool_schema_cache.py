"""Schema admission cache retains exact content, mutation and error boundaries."""
from copy import deepcopy

import pytest
from jsonschema.exceptions import SchemaError

from workbench.agent import tools


def definition(schema, name="inspect"):
    return tools.ToolDefinition(name, "v1", schema, "none", lambda args, ctx: {})


@pytest.fixture
def checked(monkeypatch):
    cache = getattr(tools, "_SCHEMA_CHECK_CACHE", None)
    if cache is not None:
        cache.clear()
    calls = []
    original = tools.Draft202012Validator.check_schema
    def check(schema):
        calls.append(deepcopy(schema))
        return original(schema)
    monkeypatch.setattr(tools.Draft202012Validator, "check_schema", check)
    yield calls
    if cache is not None:
        cache.clear()


def test_same_content_across_registries_is_admitted_once(checked):
    schema = {"type": "object", "properties": {"lags": {"type": "array", "items": {"type": "integer"}}}}
    tools.ToolRegistry().register(definition(schema))
    tools.ToolRegistry().register(definition(deepcopy(schema)))
    assert len(checked) == 1


def test_nested_mutation_requires_new_schema_check(checked):
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    tools.ToolRegistry().register(definition(schema))
    schema["properties"]["x"]["type"] = "string"
    tools.ToolRegistry().register(definition(schema))
    assert len(checked) == 2
    assert tools.validation_details(schema, {"x": 7})[0]["path"] == "x"
    assert tools.validation_details(schema, {"x": "seven"}) == []


def test_mutation_to_invalid_schema_is_never_hidden_by_cache(checked):
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    tools.ToolRegistry().register(definition(schema))
    schema["properties"]["x"]["type"] = "invalid-type"
    for _ in range(2):
        with pytest.raises(SchemaError) as error:
            tools.ToolRegistry().register(definition(schema))
        assert list(error.value.path) == ["properties", "x", "type"]
    assert len(checked) == 3


def test_invalid_errors_are_not_cached_or_converted(checked):
    schema = {"type": "invalid-type"}
    errors = []
    for _ in range(2):
        with pytest.raises(SchemaError) as error:
            tools.ToolRegistry().register(definition(schema))
        errors.append((type(error.value), str(error.value), list(error.value.path)))
    assert errors[0] == errors[1]
    assert len(checked) == 2


def test_positive_cache_is_bounded_and_eviction_rechecks(checked):
    for index in range(129):
        tools.ToolRegistry().register(definition({"type": "object", "title": str(index)}))
    assert len(tools._SCHEMA_CHECK_CACHE) == 128
    tools.ToolRegistry().register(definition({"type": "object", "title": "0"}))
    assert len(checked) == 130


def test_non_plain_schema_is_checked_without_cache(checked):
    class Schema(dict):
        pass
    schema = Schema(type="object")
    tools.ToolRegistry().register(definition(schema))
    tools.ToolRegistry().register(definition(schema))
    assert len(checked) == 2


def test_integer_object_keys_cannot_collide_with_text_keys(checked):
    for schema in ({"x-custom": {1: "one"}}, {"x-custom": {"1": "one"}}):
        tools.ToolRegistry().register(definition(schema))
    assert len(checked) == 2
