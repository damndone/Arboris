"""Persisted request profiles projected from model-family declarations."""
from typing import Any, Mapping


def family_takes_covariance(model_type: str) -> bool:
    from .family import MODEL_FAMILY_CONTRACTS
    contract = MODEL_FAMILY_CONTRACTS.get(model_type)
    # Auto routing and unknown future requests retain their requested option.
    return True if contract is None else bool(contract.allows_covariance)


def resolve_request_covariance(model_type: str, covariance: str, options: Mapping[str, Any]) -> str:
    from .family import MODEL_FAMILY_CONTRACTS
    contract = MODEL_FAMILY_CONTRACTS.get(model_type)
    if contract is None or contract.request_covariance is None:
        return covariance
    return contract.request_covariance(covariance, options)


def request_contract_summary(model_type: str, requested_covariance: str, *, entity_col, y, x) -> dict[str, Any]:
    from .family import MODEL_FAMILY_CONTRACTS
    contract = MODEL_FAMILY_CONTRACTS.get(model_type)
    applies = family_takes_covariance(model_type)
    return {
        "contract_version": contract.request_contract_version if contract else None,
        "model": model_type,
        "model_type": model_type,
        "covariance": (requested_covariance or "robust") if applies else None,
        "covariance_applies": applies,
        "covariance_explicit": bool(requested_covariance),
        "entity_col": entity_col,
        "y": y,
        "x": list(x),
        "source_eligible": bool(contract and requested_covariance in contract.source_eligible_covariances),
    }


def ols_request_covariance(covariance, options):
    from .ols import effective_ols_covariance
    return effective_ols_covariance(covariance, options) if options else covariance


def panel_request_covariance(covariance, options):
    from .ols import effective_panel_covariance
    return effective_panel_covariance(covariance, options)[0]
