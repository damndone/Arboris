"""Bounded requests leave room for DeepSeek V4.1 Flash's reasoning (paid fix4 round)."""

from workbench.agent.research_review import REVIEW_MAX_TOKENS
from workbench.llm.client import deepseek_v4_request_config
from workbench.llm.config import LLMConfig


def _config(model):
    return LLMConfig(base_url="https://api.deepseek.com", api_key="k", model=model,
                     context_window_tokens=1_000_000, provider_id="deepseek", provider_name="DeepSeek", source="local")


def test_the_configured_flash_alias_gets_the_v4_controls():
    for model in ("deepseek-flash", "deepseek-v4-flash", "deepseek-v4.1-flash"):
        assert deepseek_v4_request_config(_config(model)) == {"thinking": {"type": "disabled"}, "max_tokens": 8192}
    assert deepseek_v4_request_config(_config("deepseek-chat")) == {}


def test_the_reviewer_has_room_for_reasoning_and_its_answer():
    # With 2048 every review ended with finish_reason=length and no answer.
    assert REVIEW_MAX_TOKENS >= 16_384
