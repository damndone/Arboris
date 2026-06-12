from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .registry import ModelHandler, register_model, set_default


# Forward type — V1.5.4 does NOT build a DiagnosticRule engine; existing
# orchestrator `_check_*` helpers remain. This is the declared contract slot
# for future packs (V1.5.6+ / agent) and is intentionally permissive in V1.5.4.
DiagnosticRule = Any


class PackContractError(ValueError):
    """Raised when a pack declares a contribution the engine does not yet wire."""


# Fields declared on AnalysisPack but NOT yet consumed by the engine.
# Maps field -> planned wiring version (kept in code so the roadmap is
# self-documenting). register_pack refuses to register a pack that
# populates any of these — silent no-ops become loud errors.
_UNWIRED_FIELDS: dict[str, str] = {
    "diagnostics": "V1.5.6",
    "report_blocks": "V1.5.6",
    "recommended_actions": "when a pack needs it",
    "interpretation_restrictions": "V1.5.6",
}


REGISTERED_PACKS: list["AnalysisPack"] = []


@dataclass
class RerunAction:
    """A pack-declared one-click re-run option. param_overrides maps run-form
    fields to override values (mapped to the FailureCard form_overrides schema)."""
    key: str
    label: str
    param_overrides: dict = field(default_factory=dict)
    applies_to: list[str] | None = None   # model_types this action is relevant for; None = all


RERUN_ACTION_REGISTRY: list[RerunAction] = []


@dataclass
class StageInsertion:
    """Declares a pipeline stage contribution and where it goes.
    `after` (or `before`) names an existing PIPELINE stage by `.name`."""
    stage: Any
    after: str | None = None
    before: str | None = None


@dataclass
class AnalysisPack:
    """Container that future feature packs (Panel / DID / RDD / TimeSeries /
    ML) and the kernel itself use to declare contributions. V1.5.4 fully wires
    `model_handlers` (and `defaults_by_y_type` so the pack can set y_type→default
    routing) and lets a pack append `stages` to PIPELINE. The remaining slots
    are declared-but-not-implemented and reserved for V1.5.6+ / agent."""

    pack_id: str
    model_handlers: list[ModelHandler] = field(default_factory=list)
    defaults_by_y_type: dict[str, str] = field(default_factory=dict)
    stages: list[Any] = field(default_factory=list)
    diagnostics: list[DiagnosticRule] = field(default_factory=list)  # NOT wired -> V1.5.6

    # ---- declared, NOT implemented in V1.5.4 (-> V1.5.6+ / agent) ----
    report_blocks: list[Any] = field(default_factory=list)  # NOT wired -> V1.5.6
    recommended_actions: list[Any] = field(default_factory=list)  # NOT wired -> when a pack needs it
    interpretation_restrictions: list[Any] = field(default_factory=list)  # NOT wired -> V1.5.6
    rerun_actions: list[Any] = field(default_factory=list)


def register_pack(pack: AnalysisPack) -> None:
    """Register a pack's contributions. Wired: model_handlers, defaults_by_y_type,
    stages (explicit insertion, Task 2), rerun_actions (Task 3). Declaring a
    not-yet-wired field raises PackContractError (no silent no-ops)."""
    for field_name, planned in _UNWIRED_FIELDS.items():
        if getattr(pack, field_name):
            raise PackContractError(
                f"AnalysisPack.{field_name} is declared but not wired "
                f"(planned: {planned}). Remove it or wire it before registering "
                f"pack {pack.pack_id!r}."
            )
    for handler in pack.model_handlers:
        register_model(handler)
    for y_type, model_type in pack.defaults_by_y_type.items():
        set_default(y_type, model_type)
    if pack.stages:
        from .stages import splice_stage
        for insertion in pack.stages:
            splice_stage(insertion)
    if pack.rerun_actions:
        from .recommended_actions import BUILTIN_ACTION_KEYS
        existing_keys = {ra.key for ra in RERUN_ACTION_REGISTRY}
        seen_in_pack: set[str] = set()
        # Two-pass: validate ALL keys before appending any, so a collision
        # rejects the whole pack atomically (no partial registration).
        for rerun in pack.rerun_actions:
            if rerun.key in BUILTIN_ACTION_KEYS:
                raise PackContractError(
                    f"RerunAction key {rerun.key!r} (pack {pack.pack_id!r}) clashes "
                    f"with a built-in action key. The frontend treats 'key' as "
                    f"unique; rename it. Built-in keys: "
                    f"{sorted(BUILTIN_ACTION_KEYS)}."
                )
            if rerun.key in existing_keys:
                raise PackContractError(
                    f"RerunAction key {rerun.key!r} (pack {pack.pack_id!r}) is "
                    f"already registered by another pack. The frontend treats "
                    f"'key' as unique; keys must be globally unique."
                )
            if rerun.key in seen_in_pack:
                raise PackContractError(
                    f"RerunAction key {rerun.key!r} is declared twice within pack "
                    f"{pack.pack_id!r}. The frontend treats 'key' as unique."
                )
            seen_in_pack.add(rerun.key)
        for rerun in pack.rerun_actions:
            RERUN_ACTION_REGISTRY.append(rerun)
    REGISTERED_PACKS.append(pack)
