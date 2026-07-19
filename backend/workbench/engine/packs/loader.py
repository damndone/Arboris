"""Idempotently load explicit model-pack declarations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import import_module
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class PackDeclaration:
    module: str
    model_type: str


_LOADED_MODEL_TYPES: set[str] = set()
_LOADING_MODEL_TYPES: set[str] = set()
_DECLARED_PACK_MODULES: dict[str, str] = {}
_PACK_LOAD_LOCK = RLock()


@dataclass(frozen=True)
class _EngineStateSnapshot:
    """The shared registries a declaration is allowed to affect.

    Future declarations run third-party-ish feature code at import time.  A
    failed declaration must not leave a handler, stage, action, or capability
    visible to a later retry, so the loader snapshots the complete public
    engine registration surface before invoking it.
    """

    model_registry: dict[str, Any]
    defaults_by_y_type: dict[str, str]
    registered_packs: list[Any]
    rerun_actions: list[Any]
    pipeline: list[Any]
    capability_declarations: dict[str, Any]


def _capture_engine_state() -> _EngineStateSnapshot:
    # Importing stages here establishes the core pipeline before a future pack
    # is allowed to extend it. The empty C1 builtin declaration list never
    # reaches this function.
    from .. import capabilities
    from ..pack import REGISTERED_PACKS, RERUN_ACTION_REGISTRY
    from ..registry import DEFAULT_BY_Y_TYPE, MODEL_REGISTRY
    from ..stages import PIPELINE

    return _EngineStateSnapshot(
        model_registry=dict(MODEL_REGISTRY),
        defaults_by_y_type=dict(DEFAULT_BY_Y_TYPE),
        registered_packs=list(REGISTERED_PACKS),
        rerun_actions=list(RERUN_ACTION_REGISTRY),
        pipeline=list(PIPELINE),
        capability_declarations=dict(capabilities._DECLARED_CAPABILITIES),
    )


def _restore_engine_state(snapshot: _EngineStateSnapshot) -> None:
    from .. import capabilities
    from ..pack import REGISTERED_PACKS, RERUN_ACTION_REGISTRY
    from ..registry import DEFAULT_BY_Y_TYPE, MODEL_REGISTRY
    from ..stages import PIPELINE

    MODEL_REGISTRY.clear()
    MODEL_REGISTRY.update(snapshot.model_registry)
    DEFAULT_BY_Y_TYPE.clear()
    DEFAULT_BY_Y_TYPE.update(snapshot.defaults_by_y_type)
    REGISTERED_PACKS[:] = snapshot.registered_packs
    RERUN_ACTION_REGISTRY[:] = snapshot.rerun_actions
    PIPELINE[:] = snapshot.pipeline
    capabilities._DECLARED_CAPABILITIES.clear()
    capabilities._DECLARED_CAPABILITIES.update(snapshot.capability_declarations)


def _validate_declared_handler(
    declaration: PackDeclaration,
    *,
    before: _EngineStateSnapshot,
) -> None:
    """Bind one declaration to exactly one newly registered handler."""

    from ..registry import MODEL_REGISTRY

    overwritten = sorted(
        model_type
        for model_type, handler in before.model_registry.items()
        if MODEL_REGISTRY.get(model_type) is not handler
    )
    if overwritten:
        raise ValueError(
            "pack declaration overwrote existing model handler(s): "
            + ", ".join(overwritten)
        )

    added = set(MODEL_REGISTRY) - set(before.model_registry)
    if declaration.model_type not in added:
        raise ValueError(
            "pack declaration did not register declared model type: "
            f"{declaration.model_type}"
        )
    unexpected = sorted(added - {declaration.model_type})
    if unexpected:
        raise ValueError(
            "pack declaration registered unexpected model handler(s): "
            + ", ".join(unexpected)
        )


def load_declared_packs(declarations: Iterable[PackDeclaration]) -> None:
    """Load each declared model type once, rejecting unsafe declarations.

    A declaration module owns one newly registered handler. If its import or
    registration fails, the loader restores all shared engine registration
    state before exposing the error to the caller.
    """

    declared = tuple(declarations)
    seen_model_types: set[str] = set()
    seen_modules: set[str] = set()
    for declaration in declared:
        if (
            not isinstance(declaration.module, str)
            or not declaration.module
            or not isinstance(declaration.model_type, str)
            or not declaration.model_type
        ):
            raise ValueError("pack declaration module and model_type must be non-empty strings")
        if declaration.model_type in seen_model_types:
            raise ValueError(
                f"duplicate declared model type: {declaration.model_type}"
            )
        if declaration.module in seen_modules:
            raise ValueError(
                f"duplicate declared pack module: {declaration.module}"
            )
        seen_model_types.add(declaration.model_type)
        seen_modules.add(declaration.module)

    with _PACK_LOAD_LOCK:
        for declaration in declared:
            known_module = _DECLARED_PACK_MODULES.get(declaration.model_type)
            if known_module is not None and known_module != declaration.module:
                raise ValueError(
                    f"duplicate declared model type: {declaration.model_type}"
                )
            known_model_type = next(
                (
                    model_type
                    for model_type, module in _DECLARED_PACK_MODULES.items()
                    if module == declaration.module
                ),
                None,
            )
            if known_model_type is not None and known_model_type != declaration.model_type:
                raise ValueError(
                    f"duplicate declared pack module: {declaration.module}"
                )
            if declaration.model_type in _LOADED_MODEL_TYPES:
                continue
            if declaration.model_type in _LOADING_MODEL_TYPES:
                # A declaration may query capabilities while registering. Its
                # outer load remains authoritative; recursively declaring it
                # again would double-register handlers.
                continue

            snapshot = _capture_engine_state()
            if declaration.model_type in snapshot.model_registry:
                raise ValueError(
                    "pack declaration conflicts with existing model handler: "
                    f"{declaration.model_type}"
                )
            loaded_before = set(_LOADED_MODEL_TYPES)
            modules_before = dict(_DECLARED_PACK_MODULES)
            _DECLARED_PACK_MODULES[declaration.model_type] = declaration.module
            _LOADING_MODEL_TYPES.add(declaration.model_type)
            try:
                declare_pack = getattr(import_module(declaration.module), "declare_pack")
                declare_pack()
                _validate_declared_handler(declaration, before=snapshot)
            except Exception:
                _restore_engine_state(snapshot)
                _LOADED_MODEL_TYPES.clear()
                _LOADED_MODEL_TYPES.update(loaded_before)
                _DECLARED_PACK_MODULES.clear()
                _DECLARED_PACK_MODULES.update(modules_before)
                raise
            else:
                _LOADED_MODEL_TYPES.add(declaration.model_type)
            finally:
                _LOADING_MODEL_TYPES.discard(declaration.model_type)


def bootstrap_builtin_packs() -> None:
    """Load built-ins at every entry point safely; the loader is idempotent."""

    from .builtin_declarations import BUILTIN_PACK_DECLARATIONS

    load_declared_packs(BUILTIN_PACK_DECLARATIONS)
