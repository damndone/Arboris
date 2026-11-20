import json

import pytest

from workbench.llm.provider_store import (
    DEFAULT_TIMEOUT_S,
    ModelRecord,
    ProviderRecord,
    ProviderStore,
    environment_provider_from_env,
    load_provider_store,
    provider_public_dict,
    provider_store_lock,
    save_provider_store,
)
from workbench.llm import provider_store


def _provider_dict(**overrides):
    provider = {
        "id": "deepseek",
        "name": "DeepSeek",
        "website_url": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "secret-key",
        "timeout_s": 60,
        "models": [],
    }
    provider.update(overrides)
    return provider


@pytest.mark.parametrize("location", ["local", "remote"])
def test_data_location_round_trip_and_config(tmp_path, monkeypatch, location):
    from workbench.llm.config import load_llm_config
    target = tmp_path / "providers.json"
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(target))
    target.write_text(json.dumps({"active_provider_id": "deepseek", "providers": [
        _provider_dict(base_url="http://127.0.0.1:3425/v1", data_location=location)]}))
    store = provider_store.load_provider_store_strict(target)
    assert store.providers[0].data_location == location
    save_provider_store(store, target)
    assert load_llm_config().data_location == location
    assert provider_public_dict(store.providers[0])["data_location"] == location
    assert "secret-key" not in json.dumps(provider_public_dict(store.providers[0]))


def test_legacy_loopback_config_defaults_to_remote(tmp_path):
    target = tmp_path / "providers.json"
    target.write_text(json.dumps({"providers": [_provider_dict(base_url="http://localhost:3425/v1")]}))
    assert provider_store.load_provider_store_strict(target).providers[0].data_location == "remote"


def test_invalid_default_location_cannot_fall_back_to_environment(tmp_path, monkeypatch):
    from workbench.llm.config import load_llm_config
    monkeypatch.delenv("WORKBENCH_LLM_CONFIG_PATH", raising=False)
    target = tmp_path / "providers.json"
    target.write_text(json.dumps({"providers": [_provider_dict(data_location="auto")]}))
    monkeypatch.setattr(provider_store, "config_path", lambda: target)
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://paid.example/v1")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "paid-key")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "paid-model")
    config = load_llm_config()
    assert not config.is_configured()
    assert "invalid" in config.configuration_error_message().lower()


def test_explicit_local_environment_config(monkeypatch):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "unused")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "local")
    monkeypatch.setenv("WORKBENCH_LLM_DATA_LOCATION", "local")
    assert environment_provider_from_env().data_location == "local"
    monkeypatch.setenv("WORKBENCH_LLM_DATA_LOCATION", "auto")
    with pytest.raises(ValueError, match="data_location"):
        environment_provider_from_env()


@pytest.mark.parametrize("value", [None, "auto", "LOCAL", True, 0, []])
def test_invalid_data_location_rejected_by_strict_store(tmp_path, value):
    target = tmp_path / "providers.json"
    target.write_text(json.dumps({"providers": [_provider_dict(data_location=value)]}))
    with pytest.raises(provider_store.ProviderStoreInvalidError):
        provider_store.load_provider_store_strict(target)


def test_store_round_trips_active_provider_and_keeps_key_internal(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(tmp_path / "llm-providers.json"))
    provider = ProviderRecord(
        id="deepseek",
        name="DeepSeek",
        icon="deepseek-mark",
        notes="Primary research provider",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        api_key="secret-key",
        timeout_s=60.0,
        models=[ModelRecord("deepseek-chat", "deepseek-chat", None, False)],
    )
    save_provider_store(ProviderStore(active_provider_id="deepseek", providers=[provider]))

    loaded = load_provider_store()

    assert loaded.active_provider_id == "deepseek"
    assert loaded.providers[0].api_key == "secret-key"
    assert loaded.providers[0].icon == "deepseek-mark"
    assert loaded.providers[0].notes == "Primary research provider"
    public = provider_public_dict(loaded.providers[0])
    assert public["icon"] == "deepseek-mark"
    assert public["notes"] == "Primary research provider"
    assert public["key_present"] is True
    assert "api_key" not in public


def test_store_writes_private_file_and_handles_corrupt_file(tmp_path, monkeypatch):
    target = tmp_path / "llm-providers.json"
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(target))

    save_provider_store(ProviderStore(active_provider_id=None, providers=[]))

    assert target.exists()
    assert target.stat().st_mode & 0o077 == 0
    target.write_text("{not json", encoding="utf-8")
    assert load_provider_store().providers == []


def test_strict_store_loader_keeps_missing_empty_but_rejects_corrupt_store(tmp_path):
    missing = tmp_path / "missing.json"
    assert provider_store.load_provider_store_strict(missing) == ProviderStore()

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        provider_store.load_provider_store_strict(corrupt)
    assert type(exc_info.value).__name__ == "ProviderStoreInvalidError"

    invalid_schema = tmp_path / "invalid-schema.json"
    invalid_schema.write_text(json.dumps({"providers": "not-a-list"}), encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        provider_store.load_provider_store_strict(invalid_schema)
    assert type(exc_info.value).__name__ == "ProviderStoreInvalidError"

    unavailable = tmp_path / "unavailable.json"
    unavailable.mkdir()

    with pytest.raises(Exception) as exc_info:
        provider_store.load_provider_store_strict(unavailable)
    assert type(exc_info.value).__name__ == "ProviderStoreUnavailableError"


@pytest.mark.parametrize("field", ["id", "name"])
@pytest.mark.parametrize("value", ["", " \t"])
def test_strict_store_rejects_blank_provider_identity(tmp_path, field, value):
    target = tmp_path / "invalid-provider.json"
    target.write_text(
        json.dumps(
            {
                "version": 1,
                "active_provider_id": None,
                "providers": [_provider_dict(**{field: value})],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(provider_store.ProviderStoreInvalidError):
        provider_store.load_provider_store_strict(target)


def test_environment_provider_from_env_preserves_legacy_variables(monkeypatch):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://llm.example.com/")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "secret-key")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("WORKBENCH_LLM_TIMEOUT_S", "not-a-number")

    provider = environment_provider_from_env()

    assert provider is not None
    assert provider.base_url == "https://llm.example.com"
    assert provider.api_key == "secret-key"
    assert provider.model == "deepseek-chat"
    assert provider.timeout_s == 60.0
    assert provider.models == [ModelRecord("deepseek-chat", "deepseek-chat", None, False)]


def test_environment_provider_does_not_invent_deepseek_model_choices(monkeypatch):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "secret-key")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-v4-flash")

    provider = environment_provider_from_env()

    assert provider is not None
    assert provider.models == [
        ModelRecord("deepseek-v4-flash", "deepseek-v4-flash", None, False)
    ]


@pytest.mark.parametrize("raw_timeout", ["nan", "inf", "0", "-1", "601"])
def test_environment_provider_invalid_timeout_falls_back_to_default(
    monkeypatch, raw_timeout
):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://llm.example.com/")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "secret-key")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("WORKBENCH_LLM_TIMEOUT_S", raw_timeout)

    provider = environment_provider_from_env()

    assert provider is not None
    assert provider.timeout_s == DEFAULT_TIMEOUT_S


@pytest.mark.parametrize("raw_timeout", ["30", "60"])
def test_environment_provider_valid_timeout_is_preserved(monkeypatch, raw_timeout):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://llm.example.com/")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "secret-key")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("WORKBENCH_LLM_TIMEOUT_S", raw_timeout)

    provider = environment_provider_from_env()

    assert provider is not None
    assert provider.timeout_s == float(raw_timeout)


@pytest.mark.parametrize("raw_timeout", ["nan", "inf", 0, -1, 601])
def test_legacy_store_invalid_timeout_falls_back_to_default(tmp_path, raw_timeout):
    target = tmp_path / "llm-providers.json"
    target.write_text(
        json.dumps(
            {
                "version": 1,
                "active_provider_id": "deepseek",
                "providers": [_provider_dict(timeout_s=raw_timeout)],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_provider_store(target)

    assert loaded.active_provider_id == "deepseek"
    assert loaded.providers[0].timeout_s == DEFAULT_TIMEOUT_S


def test_legacy_store_huge_integer_timeout_falls_back_to_default(tmp_path):
    target = tmp_path / "llm-providers.json"
    target.write_text(
        json.dumps(
            {
                "version": 1,
                "active_provider_id": "deepseek",
                "providers": [_provider_dict(timeout_s=10**400)],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_provider_store(target)

    assert loaded.active_provider_id == "deepseek"
    assert loaded.providers[0].timeout_s == DEFAULT_TIMEOUT_S


def test_provider_store_lock_creates_and_releases_sibling_lockfile(tmp_path):
    target = tmp_path / "llm-providers.json"
    lock_path = target.with_name(f"{target.name}.lock")

    with provider_store_lock(target):
        assert lock_path.exists()

    with provider_store_lock(target):
        pass


def test_store_with_duplicate_provider_ids_is_rejected(tmp_path):
    target = tmp_path / "llm-providers.json"
    target.write_text(
        json.dumps(
            {
                "version": 1,
                "active_provider_id": None,
                "providers": [_provider_dict(), _provider_dict()],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_provider_store(target)

    assert loaded == ProviderStore()


def test_store_with_missing_active_provider_id_is_rejected(tmp_path):
    target = tmp_path / "llm-providers.json"
    target.write_text(
        json.dumps(
            {
                "version": 1,
                "active_provider_id": "missing",
                "providers": [_provider_dict()],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_provider_store(target)

    assert loaded == ProviderStore()


@pytest.mark.parametrize(
    "models",
    [
        [{"display_name": "   ", "request_model": "model"}],
        [{"display_name": "Model", "request_model": "\t"}],
        [{"display_name": "Model", "request_model": "model", "context_window_tokens": 0}],
        [{"display_name": "Model", "request_model": "model", "context_window_tokens": -1}],
        [
            {"display_name": "First", "request_model": "model"},
            {"display_name": "Second", "request_model": "model"},
        ],
    ],
)
def test_store_with_invalid_model_invariants_falls_back_to_empty(tmp_path, models):
    target = tmp_path / "llm-providers.json"
    target.write_text(
        json.dumps(
            {
                "version": 1,
                "active_provider_id": "deepseek",
                "providers": [_provider_dict(models=models)],
            }
        ),
        encoding="utf-8",
    )

    assert load_provider_store(target) == ProviderStore()
