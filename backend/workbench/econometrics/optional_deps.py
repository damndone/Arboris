from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import Any


def optional_dependency_error(
    extra: str,
    package: str,
    model_type: str,
    *,
    step: str = "estimation",
    engine: str | None = None,
) -> dict[str, Any]:
    install = f'pip install -e ".[{extra}]"'
    resolved_engine = engine or package
    return {
        "error_code": "OPTIONAL_DEPENDENCY_MISSING",
        "step": step,
        "engine": resolved_engine,
        "model_type": model_type,
        "message": f"Install the {extra} extra to use {model_type}: {install}",
        "details": {
            "extra": extra,
            "package": package,
            "install": install,
        },
    }


@dataclass
class OptionalDependencyNotInstalled(RuntimeError):
    extra: str
    package: str
    model_type: str
    step: str = "estimation"
    engine: str | None = None

    def __str__(self) -> str:
        return str(self.to_issue_details()["message"])

    def to_issue_details(self) -> dict[str, Any]:
        return optional_dependency_error(
            self.extra,
            self.package,
            self.model_type,
            step=self.step,
            engine=self.engine,
        )


def require_optional_dependency(
    module_name: str,
    *,
    extra: str,
    engine: str,
    model_type: str,
    step: str = "estimation",
) -> ModuleType:
    try:
        return import_module(module_name)
    except ImportError as exc:
        raise OptionalDependencyNotInstalled(
            extra=extra,
            package=module_name,
            model_type=model_type,
            step=step,
            engine=engine,
        ) from exc
