from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .registry import ModelHandler, register_model, set_default


# Forward type — V1.5.4 does NOT build a DiagnosticRule engine; existing
# orchestrator `_check_*` helpers remain. This is the declared contract slot
# for future packs (V1.5.6+ / agent) and is intentionally permissive in V1.5.4.
DiagnosticRule = Any


REGISTERED_PACKS: list["AnalysisPack"] = []


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
    diagnostics: list[DiagnosticRule] = field(default_factory=list)

    # ---- declared, NOT implemented in V1.5.4 (-> V1.5.6+ / agent) ----
    report_blocks: list[Any] = field(default_factory=list)
    recommended_actions: list[Any] = field(default_factory=list)
    interpretation_restrictions: list[Any] = field(default_factory=list)
    rerun_actions: list[Any] = field(default_factory=list)


def register_pack(pack: AnalysisPack) -> None:
    """Register a pack's contributions. V1.5.4 wires model_handlers and
    defaults_by_y_type; stage appending to PIPELINE is the importing
    module's responsibility (so insertion order stays explicit)."""
    for handler in pack.model_handlers:
        register_model(handler)
    for y_type, model_type in pack.defaults_by_y_type.items():
        set_default(y_type, model_type)
    REGISTERED_PACKS.append(pack)
