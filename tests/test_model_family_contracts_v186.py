from __future__ import annotations

from types import SimpleNamespace

import pytest

from workbench.agent.workflow_contracts import (
    MODEL_FAMILY_CONTRACTS,
    OperationValidationError,
    validate_model_genesis_spec,
)
from workbench.engine.capabilities import V186_MODEL_CAPABILITY_METADATA, build_capabilities
from workbench.engine.packs.loader import bootstrap_builtin_packs
from workbench.engine.registry import DEFAULT_BY_Y_TYPE, resolve
from workbench.contracts.model.multinomial_logit import MultinomialLogitRequest
from workbench.contracts.model.ordered_logit import OrderedLogitRequest
from workbench.contracts.model.quantile_regression import QuantileRegressionRequest
from workbench.contracts.model.survival import SurvivalCoxRequest


def _spec(model_family: str, model_options: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "model_family": model_family,
        "model_options": model_options or {},
        "branches": [{"branch_id": "main", "outcome": "y", "predictors": ["x"]}],
    }


def test_v186_packs_register_real_ordinal_and_nominal_y_type_routes() -> None:
    bootstrap_builtin_packs()

    assert DEFAULT_BY_Y_TYPE["ordinal"] == "ordinal_logit"
    assert DEFAULT_BY_Y_TYPE["nominal"] == "multinomial_logit"
    assert resolve(SimpleNamespace(requested_model_type="auto", y_type="ordinal")).model_type == "ordinal_logit"
    assert resolve(SimpleNamespace(requested_model_type="auto", y_type="nominal")).model_type == "multinomial_logit"


def test_ordered_family_contract_admits_logit_and_probit_links() -> None:
    for link in ("logit", "probit"):
        contract = validate_model_genesis_spec(
            _spec("ordinal_logit", {"link": link})
        )
        assert contract.model_options_fields == ("optimizer", "maxiter", "link", "outcome_order")

    with pytest.raises(OperationValidationError, match="ordinal_logit.*link"):
        validate_model_genesis_spec(_spec("ordinal_logit", {"link": "cloglog"}))


def test_survival_contract_declares_independent_time_to_event_options() -> None:
    contract = validate_model_genesis_spec(
        _spec(
            "survival_cox",
            {"event_column": "event", "entry_column": "entry", "ties": "efron"},
        )
    )
    assert contract.model_options_required_fields == ("event_column",)
    assert contract.model_options_column_fields == ("event_column", "group_column", "entry_column")
    assert contract.expected_artifacts == ("survival_cox_1", "survival_evidence")


def test_v186_capability_vocabulary_exposes_ordering_and_link_contracts() -> None:
    payload = build_capabilities()
    entries = {entry["key"]: entry for entry in payload["model_types"]}
    ordinal_options = next(
        item for item in entries["ordinal_logit"]["params"] if item["key"] == "model_options"
    )
    assert ordinal_options["options"] == ["optimizer", "maxiter", "link", "outcome_order"]
    assert V186_MODEL_CAPABILITY_METADATA["ordinal_logit"]["model_options_fields"] == [
        "optimizer", "maxiter", "link", "outcome_order"
    ]


def test_each_model_family_has_an_independent_typed_request_contract() -> None:
    ordinal = OrderedLogitRequest.from_mapping({"link": "probit"})
    multinomial = MultinomialLogitRequest.from_mapping({"base_category": "control"})
    survival = SurvivalCoxRequest.from_mapping({"event_column": "event"})
    quantile = QuantileRegressionRequest.from_mapping({"quantiles": [0.25, 0.5, 0.75]})

    assert ordinal.to_dict()["link"] == "probit"
    assert multinomial.to_dict()["base_category"] == "control"
    assert survival.to_dict()["event_column"] == "event"
    assert quantile.to_dict()["quantiles"] == [0.25, 0.5, 0.75]
