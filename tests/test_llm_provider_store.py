from workbench.llm.provider_store import (
    ModelRecord,
    ProviderRecord,
    ProviderStore,
    environment_provider_from_env,
    load_provider_store,
    provider_public_dict,
    save_provider_store,
)


def test_store_round_trips_active_provider_and_keeps_key_internal(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(tmp_path / "llm-providers.json"))
    provider = ProviderRecord(
        id="deepseek",
        name="DeepSeek",
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
    assert provider_public_dict(loaded.providers[0])["key_present"] is True
    assert "api_key" not in provider_public_dict(loaded.providers[0])


def test_store_writes_private_file_and_handles_corrupt_file(tmp_path, monkeypatch):
    target = tmp_path / "llm-providers.json"
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(target))

    save_provider_store(ProviderStore(active_provider_id=None, providers=[]))

    assert target.exists()
    assert target.stat().st_mode & 0o077 == 0
    target.write_text("{not json", encoding="utf-8")
    assert load_provider_store().providers == []


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
