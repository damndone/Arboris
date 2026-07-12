"""Secure local storage for Workbench LLM providers."""
from __future__ import annotations

import json
import math
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - fcntl is available on macOS/Linux.
    fcntl = None


DEFAULT_TIMEOUT_S = 60.0
MAX_TIMEOUT_S = 600.0
_CONFIG_PATH_ENV = "WORKBENCH_LLM_CONFIG_PATH"
_STORE_VERSION = 1
_DEFAULT_CONFIG_DIR = Path(".config") / "econometrics-workbench"
_DEFAULT_CONFIG_FILENAME = "llm-providers.json"


class ProviderStoreError(Exception):
    """Base error for strict provider-store loading."""


class ProviderStoreUnavailableError(ProviderStoreError):
    """The provider store could not be read due to an I/O failure."""


class ProviderStoreInvalidError(ProviderStoreError):
    """The provider store exists but contains invalid JSON or schema."""


@dataclass(frozen=True)
class ModelRecord:
    display_name: str
    request_model: str
    context_window_tokens: int | None = None
    supports_1m: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "request_model": self.request_model,
            "context_window_tokens": self.context_window_tokens,
            "supports_1m": self.supports_1m,
        }


@dataclass(frozen=True)
class ProviderRecord:
    id: str
    name: str
    base_url: str
    model: str
    api_key: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    models: list[ModelRecord] = field(default_factory=list)
    website_url: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "models", list(self.models))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "website_url": self.website_url,
            "base_url": self.base_url,
            "model": self.model,
            "api_key": self.api_key,
            "timeout_s": self.timeout_s,
            "models": [model.to_dict() for model in self.models],
        }


@dataclass(frozen=True)
class ProviderStore:
    active_provider_id: str | None = None
    providers: list[ProviderRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "providers", list(self.providers))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": _STORE_VERSION,
            "active_provider_id": self.active_provider_id,
            "providers": [provider.to_dict() for provider in self.providers],
        }


def config_path() -> Path:
    """Return the configured provider-store path."""
    configured = os.environ.get(_CONFIG_PATH_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / _DEFAULT_CONFIG_DIR / _DEFAULT_CONFIG_FILENAME


@contextmanager
def provider_store_lock(path: Path | None = None):
    """Lock the provider store across processes when flock is available."""
    target = Path(path) if path is not None else config_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = target.with_name(f"{target.name}.lock")
    lock_file = lock_path.open("a+b")
    acquired = False
    try:
        os.chmod(lock_path, 0o600)
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            acquired = True
        yield
    finally:
        if fcntl is not None and acquired:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def load_provider_store(path: Path | None = None) -> ProviderStore:
    """Load the local provider store, degrading invalid or missing files to empty."""
    target = Path(path) if path is not None else config_path()
    try:
        with target.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        return _store_from_dict(raw)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, OverflowError):
        return ProviderStore()


def load_provider_store_strict(path: Path | None = None) -> ProviderStore:
    """Load the provider store without degrading an existing file to empty."""
    target = Path(path) if path is not None else config_path()
    try:
        with target.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return ProviderStore()
    except OSError as exc:
        raise ProviderStoreUnavailableError(
            "LLM provider store could not be read."
        ) from exc
    except (UnicodeError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ProviderStoreInvalidError(
            "LLM provider store contains invalid JSON."
        ) from exc

    try:
        return _store_from_dict(raw)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ProviderStoreInvalidError(
            "LLM provider store has an invalid schema."
        ) from exc


def save_provider_store(store: ProviderStore, path: Path | None = None) -> None:
    """Persist a provider store using a private sibling file and atomic replacement."""
    target = Path(path) if path is not None else config_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    temporary_path: Path | None = None
    file_descriptor = -1
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        temporary_path = Path(temporary_name)
        os.chmod(temporary_path, 0o600)
        temporary_file = os.fdopen(file_descriptor, "w", encoding="utf-8")
        file_descriptor = -1
        with temporary_file:
            json.dump(store.to_dict(), temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, target)
    finally:
        if file_descriptor != -1:
            os.close(file_descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def environment_provider_from_env() -> ProviderRecord | None:
    """Build a provider from the legacy WORKBENCH_LLM_* environment variables."""
    base_url = os.environ.get("WORKBENCH_LLM_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("WORKBENCH_LLM_API_KEY", "")
    model = os.environ.get("WORKBENCH_LLM_MODEL", "")
    if not (base_url and api_key and model):
        return None

    raw_timeout = os.environ.get("WORKBENCH_LLM_TIMEOUT_S", "")
    timeout_s = _timeout_value(raw_timeout or DEFAULT_TIMEOUT_S)

    return ProviderRecord(
        id="environment",
        name="Environment",
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_s=timeout_s,
        models=[ModelRecord(model, model, None, False)],
    )


def provider_public_dict(provider: ProviderRecord) -> dict[str, Any]:
    """Return provider metadata safe for API responses; never include its key."""
    return {
        "id": provider.id,
        "name": provider.name,
        "website_url": provider.website_url,
        "base_url": provider.base_url,
        "model": provider.model,
        "timeout_s": provider.timeout_s,
        "models": [model.to_dict() for model in provider.models],
        "key_present": bool(provider.api_key and provider.api_key.strip()),
    }


def _store_from_dict(raw: Any) -> ProviderStore:
    if not isinstance(raw, Mapping):
        raise ValueError("provider store must be an object")
    if raw.get("version", _STORE_VERSION) != _STORE_VERSION:
        raise ValueError("unsupported provider store version")

    active_provider_id = raw.get("active_provider_id")
    if active_provider_id is not None and not isinstance(active_provider_id, str):
        raise ValueError("active_provider_id must be a string or null")

    providers_raw = raw.get("providers", [])
    if not isinstance(providers_raw, list):
        raise ValueError("providers must be a list")
    providers = [_provider_from_dict(item) for item in providers_raw]
    provider_ids = [provider.id for provider in providers]
    if len(provider_ids) != len(set(provider_ids)):
        raise ValueError("provider ids must be unique")
    if active_provider_id is not None and active_provider_id not in provider_ids:
        raise ValueError("active_provider_id must reference a provider")
    return ProviderStore(
        active_provider_id=active_provider_id,
        providers=providers,
    )


def _provider_from_dict(raw: Any) -> ProviderRecord:
    if not isinstance(raw, Mapping):
        raise ValueError("provider must be an object")
    models_raw = raw.get("models", [])
    if not isinstance(models_raw, list):
        raise ValueError("models must be a list")
    models = [_model_from_dict(item) for item in models_raw]
    request_models = [model.request_model for model in models]
    if len(request_models) != len(set(request_models)):
        raise ValueError("model request_model values must be unique")
    return ProviderRecord(
        id=_required_nonblank_string(raw, "id"),
        name=_required_nonblank_string(raw, "name"),
        website_url=_optional_string(raw, "website_url"),
        base_url=_required_string(raw, "base_url"),
        model=_required_string(raw, "model"),
        api_key=_optional_string(raw, "api_key"),
        timeout_s=_timeout_value(raw.get("timeout_s", DEFAULT_TIMEOUT_S)),
        models=models,
    )


def _model_from_dict(raw: Any) -> ModelRecord:
    if not isinstance(raw, Mapping):
        raise ValueError("model must be an object")
    context_window_tokens = raw.get("context_window_tokens")
    if context_window_tokens is not None and (
        isinstance(context_window_tokens, bool)
        or not isinstance(context_window_tokens, int)
        or context_window_tokens <= 0
    ):
        raise ValueError("context_window_tokens must be an integer or null")
    supports_1m = raw.get("supports_1m", False)
    if not isinstance(supports_1m, bool):
        raise ValueError("supports_1m must be a boolean")
    return ModelRecord(
        display_name=_required_nonblank_string(raw, "display_name"),
        request_model=_required_nonblank_string(raw, "request_model"),
        context_window_tokens=context_window_tokens,
        supports_1m=supports_1m,
    )


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _required_nonblank_string(raw: Mapping[str, Any], key: str) -> str:
    value = _required_string(raw, key)
    if not value.strip():
        raise ValueError(f"{key} must not be blank")
    return value


def _optional_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _timeout_value(value: Any) -> float:
    if isinstance(value, bool):
        return DEFAULT_TIMEOUT_S
    try:
        timeout_s = float(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_TIMEOUT_S
    if not math.isfinite(timeout_s) or timeout_s <= 0 or timeout_s > MAX_TIMEOUT_S:
        return DEFAULT_TIMEOUT_S
    return timeout_s
