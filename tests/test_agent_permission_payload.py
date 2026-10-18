"""Project permission payloads must never broaden malformed qualifiers."""

import pytest

from workbench.agent.permissions import (
    Mode,
    Outcome,
    PermissionClass,
    Request,
    Rule,
    Rules,
    decide,
    rules_from_payload,
)


def test_invalid_operation_qualifier_cannot_allow_another_operation() -> None:
    request = Request("graph.fork", PermissionClass.DERIVE)
    assert decide(Mode.ASK, request).outcome == Outcome.ASK
    try:
        rules = rules_from_payload({"allow": [{"class": "derive", "operation_id": []}]})
    except ValueError:
        return  # A rejected document grants no authority.
    assert decide(Mode.ASK, request, rules).outcome != Outcome.ALLOW


@pytest.mark.parametrize("payload", [
    None,
    [],
    {"allows": []},
    {"allow": None},
    {"deny": {}},
    {"ask": [None]},
    {"allow": [[]]},
    {"allow": [{"operation_id": "model.genesis"}]},
    {"allow": [{"class": "nonsense"}]},
    {"allow": [{"class": ["derive"]}]},
    {"allow": [{"class": 1}]},
    {"allow": [{"class": "derive", "operation": "model.genesis"}]},
    {"allow": [{"class": "derive", "operation_id": None}]},
    {"allow": [{"class": "derive", "operation_id": []}]},
    {"allow": [{"class": "derive", "operation_id": ""}]},
    {"allow": [{"class": "derive", "operation_id": 1}]},
    {"allow": [{"class": "derive", "operation_id": True}]},
])
def test_invalid_schema_rejects_the_document(payload: object) -> None:
    with pytest.raises(ValueError, match="permission rules"):
        rules_from_payload(payload)


def test_invalid_deny_cannot_be_silently_dropped_beside_valid_allow() -> None:
    with pytest.raises(ValueError, match="deny"):
        rules_from_payload({"allow": [{"class": "derive"}], "deny": [{"class": "unknown"}]})


def test_valid_empty_broad_and_narrow_rules_keep_their_scope() -> None:
    assert rules_from_payload({}) == Rules()
    assert rules_from_payload({"allow": [], "ask": [], "deny": []}) == Rules()
    rules = rules_from_payload({
        "allow": [{"class": "derive", "operation_id": "model.genesis"}],
        "ask": [{"class": "modify"}],
        "deny": [{"class": "external"}],
    })
    assert rules == Rules(
        allow=(Rule(PermissionClass.DERIVE, "model.genesis"),),
        ask=(Rule(PermissionClass.MODIFY),),
        deny=(Rule(PermissionClass.EXTERNAL),),
    )
    assert decide(Mode.ASK, Request("model.genesis", PermissionClass.DERIVE), rules).outcome == Outcome.ALLOW
    assert decide(Mode.ASK, Request("graph.fork", PermissionClass.DERIVE), rules).outcome == Outcome.ASK
    broad = rules_from_payload({"allow": [{"class": "derive"}]})
    assert decide(Mode.ASK, Request("graph.fork", PermissionClass.DERIVE), broad).outcome == Outcome.ALLOW


def test_operation_ids_are_preserved_without_normalizing_or_coercing() -> None:
    rules = rules_from_payload({"allow": [{"class": "derive", "operation_id": " model.genesis "}]})
    assert rules.allow[0].operation_id == " model.genesis "
    assert decide(Mode.ASK, Request("model.genesis", PermissionClass.DERIVE), rules).outcome == Outcome.ASK
