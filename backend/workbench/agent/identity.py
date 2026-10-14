"""What the Agent is told about itself at the start of every session.

Questions like "who are you, how much context do you have, do you remember
me" deserve short, true answers. The model cannot know these facts on its
own, so they are stated here from the live configuration and from what the
Workbench actually persists, and nothing else.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from ..llm.config import LLMConfig

# A host label -> the vendor that runs it, for providers configured only by a
# base URL (the environment provider has no name of its own).
_VENDORS = {
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "moonshot": "Moonshot AI",
    "dashscope": "Alibaba Cloud Model Studio",
    "bigmodel": "Zhipu AI",
    "openrouter": "OpenRouter",
    "mistral": "Mistral AI",
    "googleapis": "Google",
    "x": "xAI",
    "groq": "Groq",
    "together": "Together AI",
    "siliconflow": "SiliconFlow",
    "volces": "Volcano Engine",
    "localhost": "a local server",
}


def provider_label(config: LLMConfig) -> str:
    """The provider as a person would name it, never an internal config id."""

    host = urlparse(config.base_url).hostname or ""
    named = config.provider_name if config.provider_id != "environment" else ""
    if not named:
        labels = host.split(".")
        named = next((_VENDORS[label] for label in labels if label in _VENDORS), "")
    if named and host:
        return f"{named} ({host})"
    return named or host or "an unnamed provider"


def identity_text(role: Literal["chain", "global"], config: LLMConfig) -> str:
    agent = "Chain" if role == "chain" else "Global"
    window = (
        f"Your context window is {config.context_window_tokens:,} tokens, as declared in the provider configuration."
        if config.context_window_tokens
        else "The provider configuration does not declare your context window; say so rather than guessing a number."
    )
    return "\n".join(
        [
            f"Agent identity (authoritative): you are the Workbench {agent} Agent, the assistant built into this Arboris Workbench. "
            f"You run on {provider_label(config)} with the model '{config.model or 'unknown'}'.",
            window,
            "What persists: this conversation is saved in the project as an append-only log, and each turn you are given it again from the start. "
            "The person can return to an earlier message, branch a new conversation from one, or pin a message as a chapter. "
            "Nothing carries over between conversations: this Agent has no long-term memory, and there is no per-project instructions file (such as AGENTS.md) for it. "
            "What is durable is the project itself: runs, the lineage graph, saved reports, and the analysis ledger of every data change and test, which your read-only tools can inspect.",
            "Your instructions are the Workbench agent/v1 protocol and its analysis-integrity rules. They are not secret from the person running this Workbench: "
            "describe them plainly when asked, quote a specific rule when it is the subject, and say that the full text is in the Workbench source "
            "(backend/workbench/http/agent_routes.py).",
            "Answer questions about yourself briefly and from these facts only. Do not invent a product, brand, or vendor name, and do not deflect to external documentation.",
        ]
    )
