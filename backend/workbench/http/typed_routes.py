"""Response shapes declared by return annotation, documented but not enforced.

``TypedAPIRoute`` reads a handler's return annotation (a TypedDict, or a list
or union of them) and records it as the success response in OpenAPI, from
which the frontend types are generated (V1812-OPENAPI-TYPES). It also turns
off FastAPI's response validation for that route (``response_model=Any``,
which keeps the serializer of an untyped dict): what a handler returns is
served exactly as before, so a declaration mistake can neither fail a request
nor drop a field. Declarations are enforced in the test suite instead, where
every JSON response is validated strictly against its route's declared type
(tests/response_contracts.py).
"""

from __future__ import annotations

import inspect
import typing
from typing import Any

from fastapi.datastructures import DefaultPlaceholder
from fastapi.routing import APIRoute
from starlette.responses import Response

_UNDECLARED = (dict, list, typing.Any, inspect.Signature.empty, None, type(None))


class MediaType:
    """Media type of a non-JSON response: ``-> Annotated[FileResponse, MediaType("text/html")]``."""

    def __init__(self, value: str) -> None:
        self.value = value


def declared_media(endpoint: Any) -> tuple[type[Response], str] | None:
    """(response class, media type) for a handler that returns a non-JSON Response."""

    annotation = typing.get_type_hints(endpoint, include_extras=True).get("return")
    metadata: tuple[Any, ...] = ()
    if typing.get_origin(annotation) is typing.Annotated:
        annotation, *rest = typing.get_args(annotation)
        metadata = tuple(rest)
    if not (isinstance(annotation, type) and issubclass(annotation, Response)):
        return None
    named = next((item.value for item in metadata if isinstance(item, MediaType)), None)
    media = named or annotation.media_type or "application/octet-stream"
    if media == "application/json":
        return None
    return annotation, media


def declared_type(endpoint: Any) -> Any | None:
    """The response type a handler declares, or None when it declares none."""

    hints = typing.get_type_hints(endpoint, include_extras=True)
    return _documented(hints.get("return", inspect.Signature.empty))


def _documented(annotation: Any) -> Any | None:
    origin = typing.get_origin(annotation)
    if annotation in _UNDECLARED or origin is dict:
        return None
    if isinstance(annotation, type) and issubclass(annotation, Response):
        return None
    if origin is typing.Union or origin is getattr(__import__("types"), "UnionType", None):
        members = [item for item in typing.get_args(annotation)
                   if not (isinstance(item, type) and issubclass(item, Response))]
        if not members:
            return None
        if len(members) == 1:
            return _documented(members[0])
        if any(item is not type(None) and _documented(item) is None for item in members):
            return None
        annotation = typing.Union[tuple(members)]
    return annotation


class TypedAPIRoute(APIRoute):
    def __init__(self, path: str, endpoint: Any, **kwargs: Any) -> None:
        explicit = kwargs.get("response_model")
        if explicit is not None and not isinstance(explicit, DefaultPlaceholder):
            # A route that names its response_model keeps FastAPI's behaviour.
            super().__init__(path, endpoint, **kwargs)
            self.documented_type = explicit
            return
        media = declared_media(endpoint)
        if media is not None:
            response_class, media_type = media
            status = kwargs.get("status_code") or 200
            responses = dict(kwargs.get("responses") or {})
            schema = {"type": "string"} if media_type.startswith("text/") else {"type": "string", "format": "binary"}
            responses[status] = {"description": "Successful Response", "content": {media_type: {"schema": schema}}}
            kwargs["responses"] = responses
            # Documentation only: the handler returns its Response object, which
            # is served as is; a class without a media type adds no JSON entry.
            kwargs["response_class"] = response_class
            kwargs["response_model"] = None
            super().__init__(path, endpoint, **kwargs)
            self.documented_type = None
            return
        documented = declared_type(endpoint)
        if documented is not None:
            status = kwargs.get("status_code") or 200
            responses = dict(kwargs.get("responses") or {})
            entry = dict(responses.get(status, responses.get(str(status), {})))
            entry.setdefault("model", documented)
            entry.setdefault("description", "Successful Response")
            responses[status] = entry
            kwargs["responses"] = responses
            # Any keeps FastAPI's serialization exactly as for an untyped dict
            # (NaN -> null, tuples -> lists) and skips validation; None would
            # switch to jsonable_encoder, which fails on NaN.
            kwargs["response_model"] = Any
        super().__init__(path, endpoint, **kwargs)
        self.documented_type = documented
