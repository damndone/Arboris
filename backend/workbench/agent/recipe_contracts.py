"""Server-owned admission contracts for single-series analysis Recipes.

Recipes share the Notebook Draft lifecycle with regression model families, but
their input shape is deliberately different: a time column and a value column
live inside the model-options payload instead of an outcome/predictor branch.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


class RecipeValidationError(ValueError):
    """A typed Recipe proposal is incomplete or uses the wrong field shape."""


def _error(code: str, message: str) -> RecipeValidationError:
    return RecipeValidationError(f"{code}: {message}")


@dataclass(frozen=True)
class RecipeContract:
    """The public input and result boundary for one time-series Recipe."""

    recipe_id: str
    source_option_fields: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    artifact_types: Mapping[str, str]
    result_projection: str
    parameter_vocabulary: Mapping[str, object]
    runtime_outcome_option_field: str
    server_owned_option_fields: tuple[str, ...] = ()
    planning_required_option_fields: tuple[str, ...] = ()
    memory_target_refs: tuple[str, ...] = ()
    model_family: str = "time_series"
    requires_nonempty_predictors: bool = False

    @property
    def allowed_model_param_fields(self) -> frozenset[str]:
        return frozenset({"model_type", "model_options"})

    def public_result_projection(self):
        """Resolve the server-owned builder for this published Recipe."""

        from .recipes.registry import resolve_public_result_projection

        declaration = resolve_public_result_projection(self.recipe_id)
        if declaration.projection_id != self.result_projection:
            raise RuntimeError(
                f"Recipe {self.recipe_id} projection id does not match its registry"
            )
        return declaration

    def source_columns(self, model_params: Mapping[str, object]) -> tuple[str, ...]:
        options = model_params.get("model_options")
        if not isinstance(options, Mapping):
            raise _error(
                "RECIPE_MODEL_OPTIONS_REQUIRED",
                f"{self.recipe_id} requires a model_options object.",
            )
        columns: list[str] = []
        for field_name in self.source_option_fields:
            value = options.get(field_name)
            if not isinstance(value, str) or not value:
                raise _error(
                    "RECIPE_SOURCE_COLUMN_REQUIRED",
                    f"{self.recipe_id} requires model_options.{field_name}.",
                )
            columns.append(value)
        return tuple(columns)

    def runtime_outcome_column(self, model_params: Mapping[str, object]) -> str:
        """Project the Recipe-owned outcome into the legacy workflow seam.

        Recipe Drafts deliberately do not expose regression ``y``/``x``.  The
        shared execution pipeline still uses a single outcome column for its
        early column checks, so the owning Recipe contract declares which
        option field supplies that internal value.
        """

        options = model_params.get("model_options")
        if not isinstance(options, Mapping):
            raise _error(
                "RECIPE_MODEL_OPTIONS_REQUIRED",
                f"{self.recipe_id} requires a model_options object.",
            )
        value = options.get(self.runtime_outcome_option_field)
        if not isinstance(value, str) or not value:
            raise _error(
                "RECIPE_RUNTIME_OUTCOME_REQUIRED",
                f"{self.recipe_id} requires model_options."
                f"{self.runtime_outcome_option_field} for execution.",
            )
        return value

    def validate_genesis_params(
        self, model_params: Mapping[str, object], *, columns: tuple[str, ...]
    ) -> None:
        if model_params.get("model_type") != self.recipe_id:
            raise _error("RECIPE_ID_MISMATCH", "Recipe model_type does not match its contract.")
        regression_fields = sorted(
            set(model_params) & {"y", "x", "focal_x", "covariance", "entity_col", "time_col"}
        )
        if regression_fields:
            raise _error(
                "RECIPE_REGRESSION_FIELD_FORBIDDEN",
                f"{self.recipe_id} does not accept regression field(s): {', '.join(regression_fields)}.",
            )
        unknown = sorted(set(model_params) - self.allowed_model_param_fields)
        if unknown:
            raise _error(
                "RECIPE_MODEL_PARAM_UNKNOWN",
                f"{self.recipe_id} received unknown model param(s): {', '.join(unknown)}.",
            )
        missing = sorted(set(self.source_columns(model_params)) - set(columns))
        if missing:
            raise _error(
                "RECIPE_SOURCE_COLUMN_MISSING",
                f"{self.recipe_id} source column(s) are absent from the verified dataset: {', '.join(missing)}.",
            )

    def validate_planning_params(
        self, model_params: Mapping[str, object], *, columns: tuple[str, ...]
    ) -> None:
        """Apply the stricter disclosure gate used by Agent-generated options.

        Existing human-authored Drafts retain the pack contract's backwards-
        compatible defaults. An Agent recommendation must resolve time-index
        semantics before confirmation, either from its explicit field or from
        an eligible server-applied, provenance-bearing memory default.
        """

        self.validate_genesis_params(model_params, columns=columns)
        options = model_params.get("model_options")
        if not isinstance(options, Mapping):
            raise _error(
                "RECIPE_MODEL_OPTIONS_REQUIRED",
                f"{self.recipe_id} requires a model_options object.",
            )
        missing = [
            field_name
            for field_name in self.planning_required_option_fields
            if not isinstance(options.get(field_name), str) or not options[field_name]
        ]
        if missing:
            raise _error(
                "RECIPE_PLANNING_OPTION_REQUIRED",
                f"{self.recipe_id} requires resolved planning option(s): "
                + ", ".join(missing)
                + ".",
            )

    def validate_input_preflight(
        self, model_params: Mapping[str, object], *, source: object
    ) -> None:
        """Apply the owning Pack's blocking input gate before Draft persistence.

        This contract deliberately dispatches to the Pack rather than copying
        time-series rules into Notebook code.  The caller must supply a fully
        read, server-verified source containing exactly the declared columns;
        partial source scans are never accepted as a successful preflight.
        """

        options = model_params.get("model_options")
        if not isinstance(options, Mapping):
            raise _error(
                "RECIPE_MODEL_OPTIONS_REQUIRED",
                f"{self.recipe_id} requires a model_options object.",
            )
        if self.recipe_id == "time_series.ets":
            from ..engine.packs.ets.errors import ETSInputError
            from ..engine.packs.ets.input import ETSModelOptions, prepare_ets_input

            try:
                prepare_ets_input(source, ETSModelOptions.from_dict(options))
            except ETSInputError as exc:
                raise _error(
                    "RECIPE_INPUT_PREFLIGHT_FAILED",
                    f"{self.recipe_id} {exc.code}: {exc}",
                ) from exc
            except (TypeError, ValueError) as exc:
                raise _error(
                    "RECIPE_INPUT_PREFLIGHT_INVALID",
                    f"{self.recipe_id} owner contract rejected the verified source.",
                ) from exc
            return
        if self.recipe_id == "time_series.arma_garch":
            from ..contracts.model.arma_garch import ArmaGarchAnalysisContract
            from ..engine.packs.arma_garch.errors import ArmaGarchInputError
            from ..engine.packs.arma_garch.input import prepare_arma_garch_input

            try:
                prepare_arma_garch_input(
                    source, ArmaGarchAnalysisContract.from_dict(options)
                )
            except ArmaGarchInputError as exc:
                raise _error(
                    "RECIPE_INPUT_PREFLIGHT_FAILED",
                    f"{self.recipe_id} {exc.code}: {exc}",
                ) from exc
            except (TypeError, ValueError) as exc:
                raise _error(
                    "RECIPE_INPUT_PREFLIGHT_INVALID",
                    f"{self.recipe_id} owner contract rejected the verified source.",
                ) from exc
            return
        raise _error(
            "RECIPE_INPUT_PREFLIGHT_UNSUPPORTED",
            f"{self.recipe_id} has no registered input preflight.",
        )

    def bind_server_owned_options(
        self,
        value: object,
        *,
        source_reference: str,
    ) -> dict[str, object]:
        """Add immutable source facts before validating the owner contract.

        A Recipe proposal is pinned to a Notebook dataset by its typed target.
        The model must not choose a second identity inside model_options, even
        when a legacy pack contract needs that identity for lineage output.
        """

        if not isinstance(value, Mapping):
            raise _error(
                "RECIPE_MODEL_OPTIONS_REQUIRED",
                f"{self.recipe_id} requires a model_options object.",
            )
        if not isinstance(source_reference, str) or not source_reference:
            raise _error(
                "RECIPE_SOURCE_BINDING_INVALID",
                f"{self.recipe_id} requires a server-owned source reference.",
            )
        supplied = sorted(set(value) & set(self.server_owned_option_fields))
        if supplied:
            raise _error(
                "RECIPE_SERVER_OWNED_OPTION_FORBIDDEN",
                f"{self.recipe_id} must not receive server-owned option(s): {', '.join(supplied)}.",
            )
        bound = dict(value)
        for field_name in self.server_owned_option_fields:
            if field_name == "dataset_ref":
                bound[field_name] = source_reference
            else:
                raise _error(
                    "RECIPE_SERVER_OWNED_OPTION_UNRESOLVED",
                    f"{self.recipe_id} cannot bind server-owned option {field_name!r}.",
                )
        return bound

    def _agent_parameter_vocabulary(self) -> dict[str, object]:
        """Publish only fields a provider may supply in a typed proposal."""

        vocabulary = dict(self.parameter_vocabulary)
        fields = vocabulary.get("fields")
        if isinstance(fields, list):
            vocabulary["fields"] = [
                dict(field)
                for field in fields
                if isinstance(field, Mapping)
                and field.get("path") not in self.server_owned_option_fields
            ]
        elif isinstance(fields, Mapping):
            vocabulary["fields"] = {
                str(name): dict(spec) if isinstance(spec, Mapping) else spec
                for name, spec in fields.items()
                if name not in self.server_owned_option_fields
            }
        return vocabulary

    def to_payload(self) -> dict[str, object]:
        return {
            "recipe_id": self.recipe_id,
            "required_inputs": list(self.source_option_fields),
            "server_owned_option_fields": list(self.server_owned_option_fields),
            "planning_required_option_fields": list(self.planning_required_option_fields),
            "requires_nonempty_predictors": self.requires_nonempty_predictors,
            "parameter_vocabulary": self._agent_parameter_vocabulary(),
            "expected_artifacts": dict(self.artifact_types),
            "result_projection": self.result_projection,
            "memory_targets": list(self.memory_target_refs),
        }


def _ets_vocabulary() -> Mapping[str, object]:
    """Publish ETS choices from the contract that validates the fit payload."""

    from ..contracts.model.ets import (
        ERROR_COMPONENTS,
        SEASONAL_COMPONENTS,
        TIME_INDEX_SEMANTICS,
        TREND_COMPONENTS,
    )

    return MappingProxyType(
        {
            "fields": {
                "time_column": {"kind": "column", "required": True},
                "value_column": {"kind": "column", "required": True},
                "time_index_semantics": {
                    "allowed_values": list(TIME_INDEX_SEMANTICS),
                    "required": False,
                },
                "error": {"allowed_values": list(ERROR_COMPONENTS), "required": True},
                "trend": {"allowed_values": list(TREND_COMPONENTS), "required": True},
                "seasonal": {
                    "allowed_values": list(SEASONAL_COMPONENTS),
                    "required": True,
                },
                "seasonal_periods": {
                    "kind": "positive_integer",
                    "required_when": "seasonal is not null",
                },
                "damped_trend": {"kind": "boolean", "required": True},
            },
            "owner_contract": "time_series.ets@v1",
        }
    )


def _arma_garch_vocabulary() -> Mapping[str, object]:
    """Reuse the pack-owned vocabulary rather than recreating its order rules."""

    from .recipes.arma_garch_vocabulary import build_arma_garch_option_vocabulary

    return MappingProxyType(dict(build_arma_garch_option_vocabulary()))


RECIPE_CONTRACTS: Mapping[str, RecipeContract] = MappingProxyType(
    {
        "time_series.ets": RecipeContract(
            recipe_id="time_series.ets",
            source_option_fields=("time_column", "value_column"),
            expected_artifacts=("ets_1",),
            artifact_types=MappingProxyType({"ets_1": "model_result"}),
            result_projection="forecast_summary",
            parameter_vocabulary=_ets_vocabulary(),
            runtime_outcome_option_field="value_column",
            planning_required_option_fields=("time_index_semantics",),
            memory_target_refs=(
                "model.genesis.time_series.ets.time_index_semantics.regular_calendar",
                "model.genesis.time_series.ets.time_index_semantics.business_or_trading_observations",
                "model.genesis.time_series.ets.time_index_semantics.observation_order",
            ),
        ),
        "time_series.arma_garch": RecipeContract(
            recipe_id="time_series.arma_garch",
            source_option_fields=("time_column", "value_column"),
            expected_artifacts=("ts.artifact_manifest",),
            artifact_types=MappingProxyType(
                {"ts.artifact_manifest": "time_series_manifest"}
            ),
            result_projection="time_series_manifest",
            parameter_vocabulary=_arma_garch_vocabulary(),
            runtime_outcome_option_field="value_column",
            server_owned_option_fields=("dataset_ref",),
            planning_required_option_fields=("time_index_semantics",),
            memory_target_refs=(
                "model.genesis.time_series.arma_garch.time_index_semantics.regular_calendar",
                "model.genesis.time_series.arma_garch.time_index_semantics.business_or_trading_observations",
                "model.genesis.time_series.arma_garch.time_index_semantics.observation_order",
            ),
        ),
    }
)


def recipe_contract(model_type: object) -> RecipeContract:
    if not isinstance(model_type, str) or model_type not in RECIPE_CONTRACTS:
        raise _error("RECIPE_CONTRACT_UNKNOWN", f"No RecipeContract is published for {model_type!r}.")
    return RECIPE_CONTRACTS[model_type]


def recipe_contract_for_model_type(model_type: object) -> RecipeContract | None:
    return RECIPE_CONTRACTS.get(model_type) if isinstance(model_type, str) else None


def validate_recipe_genesis_params(
    model_params: Mapping[str, object], *, columns: tuple[str, ...]
) -> RecipeContract:
    contract = recipe_contract(model_params.get("model_type"))
    contract.validate_genesis_params(model_params, columns=columns)
    return contract


__all__ = [
    "RECIPE_CONTRACTS",
    "RecipeContract",
    "RecipeValidationError",
    "recipe_contract",
    "recipe_contract_for_model_type",
    "validate_recipe_genesis_params",
]
