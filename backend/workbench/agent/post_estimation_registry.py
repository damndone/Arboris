"""Family-aware, declaration-only post-estimation registry.

The registry owns admission of a post-estimation identity.  It does not import
or execute providers: runtime adapters remain server-owned call sites, and the
builtin JSON is only a published declaration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


POST_ESTIMATION_UNKNOWN_FAMILY = "POST_ESTIMATION_UNKNOWN_FAMILY"
POST_ESTIMATION_UNSUPPORTED_FAMILY = "POST_ESTIMATION_UNSUPPORTED_FAMILY"
POST_ESTIMATION_UNKNOWN_OPERATION = "POST_ESTIMATION_UNKNOWN_OPERATION"
POST_ESTIMATION_UNKNOWN_OUTPUT = "POST_ESTIMATION_UNKNOWN_OUTPUT"


class PostEstimationRegistryError(ValueError):
    """A post-estimation request is outside the closed family contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class PostEstimationAdapter:
    model_family: str
    operation_id: str
    output_id: str
    adapter_key: str

    def to_dict(self) -> dict[str, str]:
        return {
            "model_family": self.model_family,
            "operation_id": self.operation_id,
            "output_id": self.output_id,
            "adapter_key": self.adapter_key,
        }


_OLS_ADAPTERS = (
    PostEstimationAdapter(
        model_family="ols",
        operation_id="model.joint_f_test",
        output_id="result",
        adapter_key="ols.joint_f_test",
    ),
    PostEstimationAdapter(
        model_family="ols",
        operation_id="model.white_test",
        output_id="result",
        adapter_key="ols.white_test",
    ),
    PostEstimationAdapter(
        model_family="ols",
        operation_id="model.quadratic_stationary_point",
        output_id="result",
        adapter_key="ols.quadratic_stationary_point",
    ),
)


class PostEstimationRegistry:
    """Closed family/operation/output admission for existing adapters."""

    def __init__(self, adapters: tuple[PostEstimationAdapter, ...] = _OLS_ADAPTERS) -> None:
        self._adapters = tuple(adapters)
        from .workflow_contracts import MODEL_FAMILY_CONTRACTS

        self._known_families = frozenset(MODEL_FAMILY_CONTRACTS)
        self._by_family = {adapter.model_family for adapter in self._adapters}
        self._by_operation = {adapter.operation_id for adapter in self._adapters}
        self._by_identity = {
            (adapter.model_family, adapter.operation_id, adapter.output_id): adapter
            for adapter in self._adapters
        }

    @property
    def adapters(self) -> tuple[PostEstimationAdapter, ...]:
        return self._adapters

    def resolve(
        self,
        *,
        model_family: str,
        operation_id: str,
        output_id: str = "result",
    ) -> PostEstimationAdapter:
        if not isinstance(model_family, str) or not model_family:
            raise PostEstimationRegistryError(
                POST_ESTIMATION_UNKNOWN_FAMILY,
                "model family is missing",
            )
        if model_family not in self._known_families:
            code = POST_ESTIMATION_UNKNOWN_FAMILY
            raise PostEstimationRegistryError(code, f"no post-estimation adapter for {model_family!r}")
        if model_family not in self._by_family:
            code = POST_ESTIMATION_UNSUPPORTED_FAMILY
            raise PostEstimationRegistryError(code, f"no post-estimation adapter for {model_family!r}")
        if not isinstance(operation_id, str) or operation_id not in self._by_operation:
            raise PostEstimationRegistryError(
                POST_ESTIMATION_UNKNOWN_OPERATION,
                f"operation {operation_id!r} is not registered",
            )
        if not isinstance(output_id, str) or not output_id:
            raise PostEstimationRegistryError(
                POST_ESTIMATION_UNKNOWN_OUTPUT,
                "post-estimation output identity is missing",
            )
        adapter = self._by_identity.get((model_family, operation_id, output_id))
        if adapter is None:
            if any(
                item.model_family == model_family and item.operation_id == operation_id
                for item in self._adapters
            ):
                raise PostEstimationRegistryError(
                    POST_ESTIMATION_UNKNOWN_OUTPUT,
                    f"output {output_id!r} is not registered for {operation_id!r}",
                )
            raise PostEstimationRegistryError(
                POST_ESTIMATION_UNKNOWN_OPERATION,
                f"operation {operation_id!r} is not registered for {model_family!r}",
            )
        return adapter

    def require_from_branch(
        self,
        branch: Mapping[str, Any],
        *,
        operation_id: str,
        output_id: str = "result",
    ) -> PostEstimationAdapter:
        branch_spec = branch.get("branch_spec")
        if not isinstance(branch_spec, Mapping):
            raise PostEstimationRegistryError(
                POST_ESTIMATION_UNKNOWN_FAMILY,
                "completed model branch has no model family",
            )
        family = branch_spec.get("model_family")
        if not isinstance(family, str) or not family:
            raise PostEstimationRegistryError(
                POST_ESTIMATION_UNKNOWN_FAMILY,
                "completed model branch has no model family",
            )
        adapter = self.resolve(
            model_family=family,
            operation_id=operation_id,
            output_id=output_id,
        )
        # Current canonical branches carry the family twice: once as the
        # branch identity and once inside the persisted branch specification.
        # The latter is the historical source for this registry, but trusting
        # it alone lets a foreign top-level identity borrow an OLS adapter.
        # Older restored aliases may omit the top-level field, so absence
        # remains a bounded compatibility case; an explicit value must agree
        # with the registered specification.
        if "model_family" not in branch:
            return adapter
        branch_family = branch.get("model_family")
        if not isinstance(branch_family, str) or not branch_family:
            raise PostEstimationRegistryError(
                POST_ESTIMATION_UNKNOWN_FAMILY,
                "completed model branch has an invalid model family identity",
            )
        if branch_family != family:
            # Resolve the foreign identity independently so known unsupported
            # families and unknown families retain their existing typed codes.
            self.resolve(
                model_family=branch_family,
                operation_id=operation_id,
                output_id=output_id,
            )
            raise PostEstimationRegistryError(
                POST_ESTIMATION_UNSUPPORTED_FAMILY,
                f"branch model family {branch_family!r} does not match its specification {family!r}",
            )
        return adapter


post_estimation_registry = PostEstimationRegistry()


__all__ = [
    "POST_ESTIMATION_UNKNOWN_FAMILY",
    "POST_ESTIMATION_UNSUPPORTED_FAMILY",
    "POST_ESTIMATION_UNKNOWN_OPERATION",
    "POST_ESTIMATION_UNKNOWN_OUTPUT",
    "PostEstimationAdapter",
    "PostEstimationRegistry",
    "PostEstimationRegistryError",
    "post_estimation_registry",
]
