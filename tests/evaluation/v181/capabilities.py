"""Capability probes: what of the v1.8.1 wave actually exists yet.

The evaluation lane branches from the contract lock, not from any feature
branch, so at the time this harness was written none of the three feature lanes
had landed. Rather than write tests that pass vacuously (a vacuous pass is
counted as evidence and is therefore worse than a missing test), every check
that needs a lane's code is bound to a probe here and marked
``xfail(strict=True)`` while its capability is absent:

* capability absent  -> the test body still runs, still fails, and is reported
  as ``xfailed`` with the lane it is waiting on;
* capability present -> the marker does not apply and the test must pass on its
  own merits;
* capability present but the check would have passed only by accident -> strict
  xfail turns an unexpected pass into a failure.

Probes never import a lane's internals by file path. They ask the *public*
seams the contracts imply: the model registry for ``time_series.ets``, and an
importable public callable for notebook option batch generation.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable

from workbench.contracts.model.ets import ETS_MODEL_TYPE


@dataclass(frozen=True)
class Capability:
    """One probed seam."""

    name: str
    lane: str
    present: bool
    detail: str
    handle: Any = None

    @property
    def reason(self) -> str:
        return f"awaiting {self.lane} lane: {self.name} not available ({self.detail})"


def _model_registry() -> dict[str, Any]:
    from workbench.engine.packs import bootstrap_builtin_packs
    from workbench.engine.registry import MODEL_REGISTRY

    try:
        bootstrap_builtin_packs()
    except Exception:  # pragma: no cover - bootstrap is idempotent in practice
        pass
    return dict(MODEL_REGISTRY)


def ets_model_pack() -> Capability:
    """Model Pack Lane: ``time_series.ets`` registered in the model registry."""

    registry = _model_registry()
    handler = registry.get(ETS_MODEL_TYPE)
    return Capability(
        name=f"MODEL_REGISTRY[{ETS_MODEL_TYPE!r}]",
        lane="Model Pack",
        present=handler is not None,
        detail=(
            "registered"
            if handler is not None
            else f"registry currently exposes {sorted(registry)}"
        ),
        handle=handler,
    )


# Public seams the harness will accept for notebook option batch generation.
# None of these is invented by the evaluation lane out of nothing: the contract
# module is ``workbench.contracts.agent.notebook_option``, so the producer is
# expected to live under ``workbench.agent``. If the Agent Lane exposes a
# different public name, that is a contract gap to report, not something the
# evaluation lane may go read the implementation to discover.
_OPTION_BATCH_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("workbench.agent.notebook", "generate_option_batch"),
    ("workbench.agent.notebook", "propose_option_batch"),
    ("workbench.agent.notebook_options", "generate_option_batch"),
    ("workbench.agent.notebook_options", "propose_options"),
    ("workbench.agent.options", "generate_option_batch"),
    ("workbench.services.notebook_service", "generate_option_batch"),
)


def notebook_option_batch() -> Capability:
    """Agent Lane: a public callable that produces a batch of option revisions."""

    tried: list[str] = []
    for module_name, attribute in _OPTION_BATCH_CANDIDATES:
        tried.append(f"{module_name}.{attribute}")
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        candidate: Callable[..., Any] | None = getattr(module, attribute, None)
        # A public fail-closed placeholder may exist before the configured
        # provider-backed seam lands.  Importability alone is not evidence of
        # a real producer: the module must explicitly advertise availability.
        status = getattr(module, "NOTEBOOK_OPTION_BATCH_STATUS", "available")
        if callable(candidate) and status == "available":
            return Capability(
                name=f"{module_name}.{attribute}",
                lane="Agent",
                present=True,
                detail="importable",
                handle=candidate,
            )
    return Capability(
        name="notebook option batch generator",
        lane="Agent",
        present=False,
        detail="none of " + ", ".join(tried) + " is an available provider-backed seam",
    )


def ets_compare_adapter() -> Capability:
    """Model Pack / Agent: a compare adapter that can be handed two families."""

    tried = []
    for module_name, attribute in (
        ("workbench.analysis_loop.time_series_compare", "build_compare_packet"),
        ("workbench.analysis_loop.time_series_compare", "compare_time_series_runs"),
    ):
        tried.append(f"{module_name}.{attribute}")
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        candidate = getattr(module, attribute, None)
        if callable(candidate):
            return Capability(
                name=f"{module_name}.{attribute}",
                lane="Model Pack",
                present=True,
                detail="importable",
                handle=candidate,
            )
    return Capability(
        name="cross-family compare adapter",
        lane="Model Pack",
        present=False,
        detail="none of " + ", ".join(tried) + " is importable",
    )


ALL_PROBES = (ets_model_pack, notebook_option_batch, ets_compare_adapter)


def inventory() -> list[Capability]:
    return [probe() for probe in ALL_PROBES]


__all__ = [
    "ALL_PROBES",
    "Capability",
    "ets_compare_adapter",
    "ets_model_pack",
    "inventory",
    "notebook_option_batch",
]
