"""Server-owned Capability Factory runtime bootstrap.

The factory has several control-plane objects, but the application must see
one immutable installation decision.  This module is the narrow seam between
deployment configuration and the Notebook routes: it never constructs a
binding, grants execution, or invents a fallback when the deployment has no
trusted gateway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dependency_service import DependencyService
from .notebook_bridge import AuthorizedCapabilityExecutionGateway
from .notebook_catalog import CapabilityBindingCatalog


class CapabilityFactoryRuntimeError(ValueError):
    """Raised when a server-owned factory runtime cannot be admitted."""


class DependencyAdmissionGate:
    """Bind the offline dependency admission check to the CF4 gateway seam."""

    def __init__(self, service: DependencyService) -> None:
        if not isinstance(service, DependencyService):
            raise TypeError("service must be a DependencyService")
        self.service = service

    def __call__(self, dispatch_binding: Any) -> None:
        intent = getattr(dispatch_binding, "intent", None)
        bundle_ref = getattr(intent, "bundle_ref", None)
        if not isinstance(bundle_ref, str):
            raise CapabilityFactoryRuntimeError(
                "execution binding has no dependency bundle reference"
            )
        self.service.assert_execution_bundle(bundle_ref)


def _authority_id(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CapabilityFactoryRuntimeError(
            "authority_id must be a non-empty trimmed string"
        )
    if len(value) > 256 or any(ord(char) < 0x20 for char in value):
        raise CapabilityFactoryRuntimeError("authority_id is outside the bound")
    return value


@dataclass(frozen=True, slots=True)
class CapabilityFactoryRuntime:
    """One server-owned installation of the Capability Factory consumers.

    ``execution_gateway=None`` is a valid fail-closed deployment state.  A
    configured gateway must expose the dependency admission validator so the
    final trusted handoff cannot skip the offline dependency-build receipt.
    """

    authority_id: str
    catalog: CapabilityBindingCatalog
    execution_gateway: AuthorizedCapabilityExecutionGateway | None = None
    dependency_service: DependencyService | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "authority_id", _authority_id(self.authority_id))
        if not isinstance(self.catalog, CapabilityBindingCatalog):
            raise CapabilityFactoryRuntimeError(
                "catalog must be a server-owned CapabilityBindingCatalog"
            )
        if self.execution_gateway is not None and not isinstance(
            self.execution_gateway, AuthorizedCapabilityExecutionGateway
        ):
            raise CapabilityFactoryRuntimeError(
                "execution_gateway must be an AuthorizedCapabilityExecutionGateway"
            )
        if self.dependency_service is not None and not isinstance(
            self.dependency_service, DependencyService
        ):
            raise CapabilityFactoryRuntimeError(
                "dependency_service must be a server-owned DependencyService"
            )
        validator = getattr(self.execution_gateway, "dependency_binding_validator", None)
        if self.execution_gateway is not None and not isinstance(
            validator, DependencyAdmissionGate
        ):
            raise CapabilityFactoryRuntimeError(
                "configured execution gateway requires the server-owned dependency gate"
            )
        if self.execution_gateway is not None and self.dependency_service is None:
            raise CapabilityFactoryRuntimeError(
                "configured execution gateway requires a DependencyService"
            )
        if self.execution_gateway is not None and validator.service is not self.dependency_service:
            raise CapabilityFactoryRuntimeError(
                "execution gateway dependency gate is bound to another service"
            )

    @property
    def execution_enabled(self) -> bool:
        return self.execution_gateway is not None

    def public_status(self) -> dict[str, object]:
        """Expose deployment facts, never authority internals or binding refs."""

        return {
            "configured": True,
            "authority_id": self.authority_id,
            "catalog_configured": True,
            "execution_gateway_configured": self.execution_gateway is not None,
            "dependency_gate_configured": self.execution_gateway is not None
            and isinstance(
                getattr(self.execution_gateway, "dependency_binding_validator", None),
                DependencyAdmissionGate,
            ),
        }

    def validate_for_bootstrap(self) -> None:
        """Recheck the immutable deployment boundary before serving requests."""

        if not isinstance(self.catalog, CapabilityBindingCatalog):
            raise CapabilityFactoryRuntimeError("server-owned capability catalog is invalid")
        validator = getattr(self.execution_gateway, "dependency_binding_validator", None)
        if self.execution_gateway is not None and not isinstance(
            validator, DependencyAdmissionGate
        ):
            raise CapabilityFactoryRuntimeError(
                "configured execution gateway requires the server-owned dependency gate"
            )
        if self.execution_gateway is not None and self.dependency_service is None:
            raise CapabilityFactoryRuntimeError(
                "configured execution gateway requires a DependencyService"
            )
        if self.execution_gateway is not None and validator.service is not self.dependency_service:
            raise CapabilityFactoryRuntimeError(
                "execution gateway dependency gate is bound to another service"
            )


__all__ = [
    "CapabilityFactoryRuntime",
    "CapabilityFactoryRuntimeError",
    "DependencyAdmissionGate",
]
