"""Node-level Ask AI route (v1.6.11 slice A).

``POST /llm/chat`` — advisory-only Q&A over the frontend's sanitized
``ask-ai-context/v1`` packet. The model sees exactly what the packet carries
(previews already truncated client-side); guardrails are restated server-side
in the system prompt. The response is text plus provenance
(``model`` + echoed ``context_fingerprint``) — the seed of the typed,
inspectable AI-operation record targeted for the report slice and v1.7.
"""
from __future__ import annotations

import json
import math
import os
import re
from contextlib import contextmanager
from threading import RLock
from urllib.parse import urlparse
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from ..api_errors import WorkbenchAPIError
from ..llm import (
    LLMNotConfiguredError,
    LLMUpstreamError,
    chat_completion,
    load_llm_config,
)
from ..llm.client import fetch_models
from ..llm.config import validate_provider_url as _validate_provider_url
from ..llm.provider_store import (
    DEFAULT_TIMEOUT_S,
    MAX_TIMEOUT_S,
    ModelRecord,
    ProviderRecord,
    ProviderStore,
    load_provider_store,
    load_provider_store_strict,
    provider_public_dict,
    provider_store_lock,
    save_provider_store,
    environment_provider_from_env,
    ProviderStoreInvalidError,
    ProviderStoreUnavailableError,
)



class _SanitizedValidationRoute(APIRoute):
    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def sanitized_route_handler(request: Request):
            try:
                return await original_route_handler(request)
            except RequestValidationError as exc:
                errors = [
                    {
                        key: value
                        for key, value in error.items()
                        if key not in {"input", "ctx"}
                    }
                    for error in exc.errors()
                ]
                return JSONResponse(status_code=422, content={"detail": errors})

        return sanitized_route_handler


router = APIRouter(route_class=_SanitizedValidationRoute)

SUPPORTED_MODE = "workbench_node_context_v1"
REPORT_MODE = "workbench_report_v1"
FIGURE_MODE = "workbench_figure_context_v1"
MAX_QUESTION_CHARS = 4_000
PROVIDER_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_PROVIDER_MUTATION_LOCK = RLock()


@contextmanager
def _provider_store_mutation_lock():
    try:
        with _PROVIDER_MUTATION_LOCK, provider_store_lock():
            yield
    except OSError as exc:
        raise WorkbenchAPIError(
            status_code=503,
            code="LLM_PROVIDER_STORE_UNAVAILABLE",
            message="LLM provider store is unavailable.",
        ) from exc


def _safe_public_base_url(value: str | None) -> str | None:
    """Return only safe URL components for public provider metadata."""
    if not value:
        return None
    try:
        parsed = urlparse(value)
        port = parsed.port  # Force validation of malformed/out-of-range ports.
    except (TypeError, ValueError):
        return None
    if (
        any(character.isspace() for character in value)
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
    ):
        return None

    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    authority = hostname if port is None else f"{hostname}:{port}"
    return f"{parsed.scheme}://{authority}{parsed.path}"


def _public_provider_dict(provider: ProviderRecord) -> dict[str, Any]:
    public = provider_public_dict(provider)
    public["website_url"] = _safe_public_base_url(provider.website_url)
    public["base_url"] = _safe_public_base_url(provider.base_url)
    return public


def _public_config_base_url(config) -> str | None:
    base_url = config.base_url
    if not base_url and config.source == "local":
        store = load_provider_store()
        provider = next(
            (item for item in store.providers if item.id == config.provider_id),
            None,
        )
        base_url = provider.base_url if provider is not None else ""
    elif not base_url and config.source == "environment":
        base_url = os.environ.get("WORKBENCH_LLM_BASE_URL", "")
    return _safe_public_base_url(base_url)

# v1.6.11 slice C — cite-chip report generation. The packet carries a
# deterministic fact_table built client-side from the lineage contexts; the
# model may only reference numbers through [[c:ID]] markers, and the client
# renders every marker from ITS OWN table (never from model output), so a
# hallucinated number cannot become a chip.
_REPORT_PROMPT_HEADER = (
    "You are the report writer of a local econometrics workbench. The JSON "
    "packet below contains a fact_table: the ONLY numbers you may use. Each "
    "fact has an id.\n"
    "Hard rules (non-negotiable):\n"
    "- Write a structured empirical report in Markdown with these sections: "
    "Title (# heading), Data, Methods, Results, Limitations.\n"
    "- Every number, parameter value or decision you mention MUST come from "
    "the fact_table and MUST be immediately followed by its citation marker "
    "in the exact form [[c:ID]] (e.g. 'R² of 0.86 [[c:c12]]').\n"
    "- Never invent, round differently, or combine numbers not present in "
    "the fact_table. If something is missing, name the gap in Limitations "
    "instead of guessing.\n"
    "- Advisory text only: no executable actions, no code, no backend payloads.\n"
    "- Write in the language of the user's instruction."
)

_SYSTEM_PROMPT_HEADER = (
    "You are the node assistant of a local econometrics workbench. The user "
    "selected one node of a lineage graph (data -> cleaning -> model -> "
    "diagnostics); the JSON context packet below describes that node, its "
    "upstream path, parameters, metrics and artifact previews.\n"
    "Hard rules (non-negotiable):\n"
    "- Advisory text only. Never output executable actions, code to mutate "
    "the graph, or backend payloads.\n"
    "- Ground every number you cite in the packet. If the packet does not "
    "contain the answer, say so instead of guessing.\n"
    "- The packet holds truncated previews, not full datasets or reports. "
    "Disclose this limit whenever it affects your answer.\n"
    "- Answer in the language the user asked in."
)

_FIGURE_PROMPT_HEADER = (
    "You are the figure assistant of a local econometrics workbench. The user "
    "selected one generated chart. You CANNOT see the image. The JSON packet "
    "below gives the chart type and a safe preview of the numeric artifact the "
    "chart was drawn from.\n"
    "Hard rules (non-negotiable):\n"
    "- Interpret the chart ONLY from the numeric source in the packet; never "
    "claim to see colours, shapes, or pixels.\n"
    "- Ground every statement in the numbers. If the source does not support a "
    "reading, say so instead of guessing.\n"
    "- The preview may be truncated; disclose this limit whenever it affects "
    "your answer.\n"
    "- Advisory text only. Never output executable actions or backend payloads.\n"
    "- Answer in the language the user asked in."
)

# v1.7 G2 step 2 — the user explicitly opted into sending the rendered chart to
# a vision-capable provider. The text-only header above would now be a lie, so
# vision requests get their own header: the image is admissible for visual
# structure, but numbers must still come from the numeric source (a model
# reading values off pixels is exactly the failure mode we avoid).
_FIGURE_VISION_PROMPT_HEADER = (
    "You are the figure assistant of a local econometrics workbench. The user "
    "selected one generated chart and explicitly chose to send you the rendered "
    "image. You are given BOTH the chart image and the JSON packet with its "
    "chart type and a safe preview of the numeric artifact it was drawn from.\n"
    "Hard rules (non-negotiable):\n"
    "- Every NUMBER you state must come from the numeric source in the packet, "
    "never read off the image. Use the image only for visual structure the "
    "numbers cannot show (shape, outliers, overplotting, layout problems).\n"
    "- If image and numbers disagree, trust the numbers and say so.\n"
    "- The preview may be truncated; disclose this limit whenever it affects "
    "your answer.\n"
    "- Advisory text only. Never output executable actions or backend payloads.\n"
    "- Answer in the language the user asked in."
)

# Bound the opt-in payload: these are matplotlib PNGs (tens to hundreds of KB).
MAX_IMAGE_DATA_URL_CHARS = 6_000_000
_IMAGE_DATA_URL_PREFIX = "data:image/png;base64,"


# v1.6.12 T5 (A4) — read-only provider visibility. Returns WHICH provider and
# model /llm/chat will use and whether a key is present — never the key itself
# (not even masked; no prefix, no length). Key management stays in the env
# file by design.
@router.get("/llm/config")
def llm_config() -> dict[str, Any]:
    config = load_llm_config()
    return {
        "configured": config.is_configured(),
        "base_url": _public_config_base_url(config),
        "model": config.model or None,
        "key_present": bool(config.api_key and config.api_key.strip()),
        "timeout_s": config.timeout_s,
        "provider_id": config.provider_id or None,
        "provider_name": config.provider_name or None,
        "source": config.source,
        "context_window_tokens": config.context_window_tokens,
        "supports_1m": config.supports_1m,
        "supports_vision": config.supports_vision,
    }


class ProviderModelRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    display_name: str = Field(min_length=1)
    request_model: str = Field(min_length=1)
    context_window_tokens: int | None = Field(default=None, ge=1)
    supports_1m: bool = False
    supports_vision: bool = False

    @field_validator("display_name", "request_model")
    @classmethod
    def validate_model_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model text must not be blank")
        return value


class ProviderUpsertRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    id: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, min_length=1)
    icon: str | None = None
    notes: str | None = None
    website_url: str | None = None
    base_url: str | None = None
    model: str | None = Field(default=None, min_length=1)
    api_key: str | None = None
    timeout_s: float | None = Field(default=None, gt=0, le=MAX_TIMEOUT_S)
    models: list[ProviderModelRequest] | None = None
    clear_api_key: bool = False

    @field_validator("id", "name", "model")
    @classmethod
    def validate_provider_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("provider text must not be blank")
        return value

    @field_validator("id")
    @classmethod
    def validate_provider_id(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(PROVIDER_ID_PATTERN, value) is None:
            raise ValueError(
                "provider id must be a route-safe non-empty slug"
            )
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        return _validate_provider_url(value, "base_url")

    @field_validator("website_url")
    @classmethod
    def validate_website_url(cls, value: str | None) -> str | None:
        return _validate_provider_url(value, "website_url")

    @field_validator("timeout_s")
    @classmethod
    def validate_timeout(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("timeout_s must be finite")
        return value

    @model_validator(mode="after")
    def validate_unique_request_models(self) -> "ProviderUpsertRequest":
        request_models = [model.request_model for model in self.models or []]
        if len(request_models) != len(set(request_models)):
            raise ValueError("models request_model values must be unique")
        return self


ProviderID = Annotated[str, Path(pattern=PROVIDER_ID_PATTERN)]


def _provider_or_error(provider_id: str) -> ProviderRecord:
    store = _load_provider_store_for_mutation()
    provider = next((item for item in store.providers if item.id == provider_id), None)
    if provider is None and not store.providers and provider_id == "environment":
        provider = environment_provider_from_env()
    if provider is None:
        raise WorkbenchAPIError(
            status_code=404,
            code="LLM_PROVIDER_NOT_FOUND",
            message=f"LLM provider {provider_id!r} was not found.",
        )
    return provider


def _provider_configuration_gaps(provider: ProviderRecord) -> list[str]:
    gaps: list[str] = []
    try:
        validated_base_url = _validate_provider_url(provider.base_url, "base_url")
    except (TypeError, ValueError):
        validated_base_url = None
    if not validated_base_url or not validated_base_url.strip():
        gaps.append("base_url")

    for field in ("api_key", "model"):
        value = getattr(provider, field, None)
        if not value or not value.strip():
            gaps.append(field)
    return gaps


def _is_provider_configured(provider: ProviderRecord) -> bool:
    return not _provider_configuration_gaps(provider)


def _stored_api_key(value: str | None) -> str:
    return value if value is not None and value.strip() else ""


def _require_create_fields(request: ProviderUpsertRequest) -> None:
    if request.clear_api_key:
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_PROVIDER_INVALID",
            message="clear_api_key is only valid when updating an existing provider.",
            details={"field": "clear_api_key"},
        )
    missing = [
        field
        for field in ("id", "name", "base_url", "model")
        if getattr(request, field) in (None, "")
    ]
    if missing:
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_PROVIDER_INVALID",
            message="Provider id, name, base_url and model are required.",
            details={"fields": missing},
        )


def _to_provider_record(
    request: ProviderUpsertRequest,
    *,
    provider_id: str | None = None,
    existing: ProviderRecord | None = None,
) -> ProviderRecord:
    if existing is None:
        _require_create_fields(request)
        assert request.id is not None
        assert request.name is not None
        assert request.base_url is not None
        assert request.model is not None
        return ProviderRecord(
            id=request.id,
            name=request.name,
            icon=request.icon or "",
            notes=request.notes or "",
            website_url=request.website_url or "",
            base_url=request.base_url,
            model=request.model,
            api_key=_stored_api_key(request.api_key),
            timeout_s=request.timeout_s or DEFAULT_TIMEOUT_S,
            models=[ModelRecord(**model.model_dump()) for model in request.models or []],
        )

    if request.id is not None and request.id != provider_id:
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_PROVIDER_INVALID",
            message="Provider id cannot be changed.",
            details={"field": "id"},
        )
    api_key = (
        ""
        if request.clear_api_key
        else (
            request.api_key
            if request.api_key is not None and request.api_key.strip()
            else existing.api_key
        )
    )
    return ProviderRecord(
        id=existing.id,
        name=request.name if request.name is not None else existing.name,
        icon=request.icon if request.icon is not None else existing.icon,
        notes=request.notes if request.notes is not None else existing.notes,
        website_url=(
            request.website_url if request.website_url is not None else existing.website_url
        ),
        base_url=request.base_url if request.base_url is not None else existing.base_url,
        model=request.model if request.model is not None else existing.model,
        api_key=api_key,
        timeout_s=request.timeout_s if request.timeout_s is not None else existing.timeout_s,
        models=(
            [ModelRecord(**model.model_dump()) for model in request.models]
            if request.models is not None
            else existing.models
        ),
    )


def _replace_provider(store: ProviderStore, replacement: ProviderRecord) -> ProviderStore:
    return ProviderStore(
        active_provider_id=store.active_provider_id,
        providers=[
            replacement if provider.id == replacement.id else provider
            for provider in store.providers
        ],
    )


def _upstream_error(exc: LLMUpstreamError) -> WorkbenchAPIError:
    return WorkbenchAPIError(
        status_code=502,
        code="LLM_UPSTREAM_ERROR",
        message=str(exc),
        details={"upstream_status": exc.upstream_status},
    )


def _save_provider_store_or_error(store: ProviderStore) -> None:
    save_provider_store(store)


def _load_provider_store_for_mutation() -> ProviderStore:
    try:
        return load_provider_store_strict()
    except ProviderStoreInvalidError as exc:
        raise WorkbenchAPIError(
            status_code=500,
            code="LLM_PROVIDER_STORE_INVALID",
            message="LLM provider store is invalid.",
        ) from exc
    except ProviderStoreUnavailableError as exc:
        raise WorkbenchAPIError(
            status_code=503,
            code="LLM_PROVIDER_STORE_UNAVAILABLE",
            message="LLM provider store is unavailable.",
        ) from exc


@router.get("/llm/providers")
def list_llm_providers() -> dict[str, Any]:
    store = _load_provider_store_for_mutation()
    if not store.providers:
        environment_provider = environment_provider_from_env()
        if environment_provider is not None:
            return {
                "active_provider_id": environment_provider.id,
                "providers": [_public_provider_dict(environment_provider)],
            }
    return {
        "active_provider_id": store.active_provider_id,
        "providers": [_public_provider_dict(provider) for provider in store.providers],
    }


@router.post("/llm/providers")
def create_llm_provider(request: ProviderUpsertRequest) -> dict[str, Any]:
    with _provider_store_mutation_lock():
        _require_create_fields(request)
        store = _load_provider_store_for_mutation()
        assert request.id is not None
        if any(provider.id == request.id for provider in store.providers):
            raise WorkbenchAPIError(
                status_code=409,
                code="LLM_PROVIDER_ALREADY_EXISTS",
                message=f"LLM provider {request.id!r} already exists.",
            )
        provider = _to_provider_record(request)
        _save_provider_store_or_error(
            ProviderStore(
                active_provider_id=store.active_provider_id,
                providers=[*store.providers, provider],
            )
        )
        return _public_provider_dict(provider)


@router.put("/llm/providers/{provider_id}")
def update_llm_provider(
    provider_id: ProviderID, request: ProviderUpsertRequest
) -> dict[str, Any]:
    with _provider_store_mutation_lock():
        store = _load_provider_store_for_mutation()
        existing = next((item for item in store.providers if item.id == provider_id), None)
        if existing is None and not store.providers and provider_id == "environment":
            existing = environment_provider_from_env()
        if existing is None:
            raise WorkbenchAPIError(
                status_code=404,
                code="LLM_PROVIDER_NOT_FOUND",
                message=f"LLM provider {provider_id!r} was not found.",
            )
        is_environment_bootstrap = existing.id == "environment" and not store.providers
        provider = _to_provider_record(request, provider_id=provider_id, existing=existing)
        updated_store = (
            ProviderStore(active_provider_id=provider.id, providers=[provider])
            if is_environment_bootstrap
            else _replace_provider(store, provider)
        )
        if (
            store.active_provider_id == provider_id
            and not _is_provider_configured(provider)
        ):
            updated_store = ProviderStore(
                active_provider_id=None,
                providers=updated_store.providers,
            )
        _save_provider_store_or_error(updated_store)
        return _public_provider_dict(provider)


@router.post("/llm/providers/{provider_id}/activate")
def activate_llm_provider(provider_id: ProviderID) -> dict[str, Any]:
    with _provider_store_mutation_lock():
        provider = _provider_or_error(provider_id)
        missing = _provider_configuration_gaps(provider)
        if missing:
            raise WorkbenchAPIError(
                status_code=422,
                code="LLM_PROVIDER_NOT_CONFIGURED",
                message="LLM provider is not fully configured.",
                details={"fields": missing},
        )
        store = _load_provider_store_for_mutation()
        _save_provider_store_or_error(
            ProviderStore(active_provider_id=provider.id, providers=store.providers)
        )
        return _public_provider_dict(provider)


@router.delete("/llm/providers/{provider_id}")
def delete_llm_provider(provider_id: ProviderID) -> dict[str, Any]:
    with _provider_store_mutation_lock():
        provider = _provider_or_error(provider_id)
        store = _load_provider_store_for_mutation()
        remaining_providers = [
            item for item in store.providers if item.id != provider_id
        ]
        active_provider_id = store.active_provider_id
        if active_provider_id == provider_id:
            active_provider_id = next(
                (
                    item.id
                    for item in remaining_providers
                    if _is_provider_configured(item)
                ),
                None,
            )
        _save_provider_store_or_error(
            ProviderStore(
                active_provider_id=active_provider_id,
                providers=remaining_providers,
            )
        )
        return _public_provider_dict(provider)


def _provider_config(provider: ProviderRecord):
    from ..llm.config import LLMConfig

    try:
        _validate_provider_url(provider.base_url, "base_url")
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_PROVIDER_INVALID",
            message="Provider base_url must be an absolute http or https URL.",
            details={"field": "base_url"},
        ) from exc

    return LLMConfig(
        base_url=provider.base_url,
        api_key=provider.api_key,
        model=provider.model,
        timeout_s=provider.timeout_s,
    )


@router.post("/llm/providers/{provider_id}/models/refresh")
def refresh_llm_provider_models(provider_id: ProviderID) -> dict[str, Any]:
    with _provider_store_mutation_lock():
        provider = _provider_or_error(provider_id)
    try:
        models = fetch_models(_provider_config(provider))
    except LLMNotConfiguredError as exc:
        raise WorkbenchAPIError(
            status_code=503, code="LLM_NOT_CONFIGURED", message=str(exc)
        ) from exc
    except LLMUpstreamError as exc:
        raise _upstream_error(exc) from exc

    with _provider_store_mutation_lock():
        current_store = _load_provider_store_for_mutation()
        current_provider = next(
            (item for item in current_store.providers if item.id == provider_id), None
        )
        if current_provider is None and not current_store.providers and provider_id == "environment":
            current_provider = environment_provider_from_env()
        if current_provider is None:
            raise WorkbenchAPIError(
                status_code=404,
                code="LLM_PROVIDER_NOT_FOUND",
                message=f"LLM provider {provider_id!r} was not found.",
            )
        if _provider_configuration_identity(current_provider) != (
            _provider_configuration_identity(provider)
        ):
            raise WorkbenchAPIError(
                status_code=409,
                code="LLM_PROVIDER_CHANGED_DURING_REFRESH",
                message=(
                    f"LLM provider {provider_id!r} changed while its models were "
                    "being refreshed."
                ),
                details={"provider_id": provider_id},
            )

        existing_models = {model.request_model: model for model in current_provider.models}
        refreshed_models = [
            ModelRecord(
                display_name=existing_models.get(
                    model["id"], ModelRecord(model["id"], model["id"])
                ).display_name,
                request_model=model["id"],
                context_window_tokens=(
                    existing_models[model["id"]].context_window_tokens
                    if model["id"] in existing_models
                    else None
                ),
                supports_1m=(
                    existing_models[model["id"]].supports_1m
                    if model["id"] in existing_models
                    else False
                ),
                supports_vision=(
                    existing_models[model["id"]].supports_vision
                    if model["id"] in existing_models
                    else False
                ),
            )
            for model in models
        ]
        refreshed = ProviderRecord(
            id=current_provider.id,
            name=current_provider.name,
            icon=current_provider.icon,
            notes=current_provider.notes,
            website_url=current_provider.website_url,
            base_url=current_provider.base_url,
            model=current_provider.model,
            api_key=current_provider.api_key,
            timeout_s=current_provider.timeout_s,
            models=refreshed_models,
        )
        updated_store = (
            ProviderStore(active_provider_id=refreshed.id, providers=[refreshed])
            if not current_store.providers and refreshed.id == "environment"
            else _replace_provider(current_store, refreshed)
        )
        _save_provider_store_or_error(updated_store)
        return _public_provider_dict(refreshed)


@router.post("/llm/providers/{provider_id}/probe")
def probe_llm_provider(provider_id: ProviderID) -> dict[str, Any]:
    with _provider_store_mutation_lock():
        provider = _provider_or_error(provider_id)
    try:
        fetch_models(_provider_config(provider))
    except LLMNotConfiguredError as exc:
        raise WorkbenchAPIError(
            status_code=503, code="LLM_NOT_CONFIGURED", message=str(exc)
        ) from exc
    except LLMUpstreamError as exc:
        raise _upstream_error(exc) from exc

    with _provider_store_mutation_lock():
        current_provider = next(
            (
                item
                for item in _load_provider_store_for_mutation().providers
                if item.id == provider_id
            ),
            None,
        )
        if current_provider is None and provider_id == "environment":
            current_provider = environment_provider_from_env()
        if current_provider is None:
            raise WorkbenchAPIError(
                status_code=404,
                code="LLM_PROVIDER_NOT_FOUND",
                message=f"LLM provider {provider_id!r} was not found.",
            )
        if current_provider != provider:
            raise WorkbenchAPIError(
                status_code=409,
                code="LLM_PROVIDER_CONFLICT",
                message=f"LLM provider {provider_id!r} changed while it was being probed.",
                details={"provider_id": provider_id},
            )
        return _public_provider_dict(current_provider)


def _provider_configuration_identity(
    provider: ProviderRecord,
) -> tuple[str, str, str, float]:
    return (provider.base_url, provider.api_key, provider.model, provider.timeout_s)


class AskAIChatRequest(BaseModel):
    mode: str
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    packet: dict[str, Any]
    response_guardrails: dict[str, Any] | None = None
    # v1.7 G2 step 2 — opt-in only. The client attaches the rendered chart as a
    # PNG data URL after the user explicitly agreed to send it to the provider.
    # Absent by default: the standing policy is binaries-excluded.
    image_data_url: str | None = Field(default=None, max_length=MAX_IMAGE_DATA_URL_CHARS)


@router.post("/llm/chat")
def llm_chat(request: AskAIChatRequest) -> dict[str, Any]:
    if request.mode not in (SUPPORTED_MODE, REPORT_MODE, FIGURE_MODE):
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_CHAT_UNSUPPORTED_MODE",
            message=f"Unsupported mode: {request.mode!r}",
            details={"supported_modes": [SUPPORTED_MODE, REPORT_MODE, FIGURE_MODE]},
        )
    if request.question.strip() == "":
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_CHAT_EMPTY_QUESTION",
            message="Question must not be blank",
        )

    config = load_llm_config()
    _validate_image_optin(request, config)
    messages = [
        {"role": "system", "content": _build_system_prompt(request)},
        {"role": "user", "content": _build_user_content(request)},
    ]
    try:
        result = chat_completion(messages, config)
    except LLMNotConfiguredError as exc:
        raise WorkbenchAPIError(
            status_code=503, code="LLM_NOT_CONFIGURED", message=str(exc)
        ) from exc
    except LLMUpstreamError as exc:
        raise WorkbenchAPIError(
            status_code=502,
            code="LLM_UPSTREAM_ERROR",
            message=str(exc),
            details={"upstream_status": exc.upstream_status},
        ) from exc

    return {
        "text": result["text"],
        "model": result["model"],
        "context_fingerprint": request.packet.get("context_fingerprint"),
    }


def _validate_image_optin(request: AskAIChatRequest, config) -> None:
    """Fail closed on the image opt-in: figure mode + vision model + PNG only."""

    if request.image_data_url is None:
        return
    if request.mode != FIGURE_MODE:
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_CHAT_IMAGE_NOT_ALLOWED",
            message="An image may only be sent in figure mode.",
            details={"mode": request.mode},
        )
    if not request.image_data_url.startswith(_IMAGE_DATA_URL_PREFIX):
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_CHAT_IMAGE_INVALID",
            message="The chart image must be a base64 PNG data URL.",
        )
    if not config.supports_vision:
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_CHAT_VISION_UNSUPPORTED",
            message=(
                "The active model is not marked as vision-capable; "
                "the chart image was not sent."
            ),
            details={"model": config.model or None},
        )


def _build_user_content(request: AskAIChatRequest) -> Any:
    """Text-only by default; OpenAI-compatible multimodal parts when opted in."""

    if request.image_data_url is None:
        return request.question
    return [
        {"type": "text", "text": request.question},
        {"type": "image_url", "image_url": {"url": request.image_data_url}},
    ]


def _build_system_prompt(request: AskAIChatRequest) -> str:
    if request.mode == REPORT_MODE:
        header = _REPORT_PROMPT_HEADER
    elif request.mode == FIGURE_MODE:
        header = (
            _FIGURE_VISION_PROMPT_HEADER
            if request.image_data_url is not None
            else _FIGURE_PROMPT_HEADER
        )
    else:
        header = _SYSTEM_PROMPT_HEADER
    sections = [header]
    guardrails = request.response_guardrails or request.packet.get("response_guardrails")
    if guardrails:
        sections.append(
            "Client-declared guardrails (all must hold):\n"
            + json.dumps(guardrails, ensure_ascii=False, sort_keys=True)
        )
    sections.append(
        "Context packet:\n" + json.dumps(request.packet, ensure_ascii=False)
    )
    return "\n\n".join(sections)
