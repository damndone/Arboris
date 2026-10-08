"""Shapes shared by several routes."""

from __future__ import annotations

import dataclasses
import types
import typing
from typing import Any, NotRequired

from pydantic import BaseModel
from typing_extensions import TypedDict

JsonSchema = dict[str, Any]
"""An embedded JSON Schema document, typed by its own standard."""


class MissingRange(TypedDict):
    low: int | float
    high: int | float


class RunLabels(TypedDict):
    """Column metadata a run carries (SPSS/Stata labels and declarations)."""

    variable_labels: NotRequired[dict[str, str]]
    value_labels: NotRequired[dict[str, dict[str, str]]]
    measurement_level: NotRequired[dict[str, str]]
    user_missing_values: NotRequired[dict[str, list[str | int | float | MissingRange]]]


def view_of(
    source: type,
    name: str,
    /,
    *,
    omit: tuple[str, ...] = (),
    inline: tuple[Any, ...] = (),
    stored: bool = False,
    **extra: Any,
) -> Any:
    """A TypedDict of a dataclass's or pydantic model's fields as serialized,
    adjusted per route.

    For domain types whose JSON form is their fields (enums by value, tuples as
    lists, nested dataclasses as objects), the response type is derived from
    the type itself, so the two cannot drift. ``omit`` drops fields the
    serializer leaves out, ``inline`` flattens another TypedDict's fields in
    (as ``{**spec.to_dict(), ...}`` does), ``stored`` marks fields with a
    default as possibly absent (records written before the field existed), and
    ``extra`` adds fields attached at response time (use NotRequired[...] when
    conditional).
    """

    fields: dict[str, Any] = {}
    if isinstance(source, type) and issubclass(source, BaseModel):
        for key, info in source.model_fields.items():
            if key not in omit:
                fields[key] = info.annotation if info.is_required() or not stored else NotRequired[info.annotation]
    else:
        hints = typing.get_type_hints(source)
        for field in dataclasses.fields(source):
            if field.name in omit or field.name in extra:
                continue
            annotation = viewed(hints[field.name])
            has_default = field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING
            fields[field.name] = NotRequired[annotation] if stored and has_default else annotation
    for flattened in inline:
        inner = typing.get_type_hints(flattened, include_extras=True)
        required = getattr(flattened, "__required_keys__", frozenset(inner))
        for key, annotation in inner.items():
            if key not in omit:
                fields[key] = annotation if key in required else NotRequired[annotation]
    return TypedDict(name, {**fields, **extra})  # type: ignore[operator]


_VIEWS: dict[type, Any] = {}


def define_view(source: type, /, **adjust: Any) -> Any:
    """The view of a dataclass whose serializer departs from its fields (for
    example omits a field that is None); every nested use resolves to it.

    Call it before any view that nests the dataclass.
    """

    if _VIEWS.get(source) is not None:
        raise TypeError(f"{source.__name__} was already viewed; define its view first")
    _VIEWS[source] = view_of(source, source.__name__, **adjust)
    return _VIEWS[source]


def viewed(annotation: Any) -> Any:
    """``annotation`` with every dataclass in it replaced by its view (one per class).

    A dataclass serializes every field, defaults included; referenced as is,
    a field with a default would be documented as optional.
    """

    if dataclasses.is_dataclass(annotation) and isinstance(annotation, type):
        if annotation not in _VIEWS:
            _VIEWS[annotation] = None  # a recursive dataclass needs an explicit view
            _VIEWS[annotation] = view_of(annotation, annotation.__name__)
        if _VIEWS[annotation] is None:
            raise TypeError(f"{annotation.__name__} is recursive; declare its view explicitly")
        return _VIEWS[annotation]
    args = typing.get_args(annotation)
    if not args:
        return annotation
    inner = tuple(viewed(arg) for arg in args)
    if inner == args:
        return annotation
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return typing.Annotated[(inner[0], *annotation.__metadata__)]
    if origin is typing.Union or origin is types.UnionType:
        return typing.Union[inner]
    if origin is typing.Literal:
        return annotation
    return origin[inner if len(inner) > 1 else inner[0]]
