"""Server-written closing messages for Agent turns, in the user's language.

Two turn endings produced no usable reply: a proposal ended the turn on the
model's pre-tool narration (often English for a Chinese question), and an
exhausted step budget ended it with nothing at all. Both are written here from
structured facts -- the persisted proposal, the tools actually called -- so the
text cannot claim anything the server does not hold.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

_CJK = re.compile(r"[㐀-鿿]")


def detect_language(text: str | None) -> str:
    """'zh' when the text is written in Chinese, else 'en'."""

    if not text:
        return "en"
    return "zh" if len(_CJK.findall(text)) >= max(1, len(text.strip()) // 10) else "en"


def matches_language(text: str | None, language: str) -> bool:
    return bool(text and text.strip()) and detect_language(text) == language


def proposal_summary(proposal: Mapping[str, Any], language: str) -> str:
    """What the proposal will do, taken only from its persisted content."""

    from .proposal_text import proposal_lines

    operation = str(proposal.get("operation_id") or "operation")
    lines = proposal_lines(proposal)
    body = "\n".join(f"{index}. {line}" for index, line in enumerate(lines, start=1))
    if language == "zh":
        return (
            f"已生成待确认的提案（{operation}），尚未执行：\n{body}\n"
            "请在提案卡片中核对后确认执行，或告诉我需要修改的地方。"
        )
    return (
        f"A proposal ({operation}) is ready and has not run yet:\n{body}\n"
        "Review it in the proposal card and confirm to run it, or tell me what to change."
    )


def budget_exhausted_message(
    language: str,
    error: str,
    tools_used: Sequence[str],
    last_failure: str | None,
) -> str:
    """Why a turn stopped without an answer, and what the user can do next."""

    distinct = list(dict.fromkeys(tools_used))
    if language == "zh":
        reason = "步数预算已用完" if error == "max_steps_exceeded" else "检测到重复调用同一工具"
        parts = [f"这次请求没有完成：{reason}，我还没有给出结论或提交提案。"]
        if distinct:
            parts.append("已查看：" + "、".join(distinct[:8]) + "。")
        if last_failure:
            parts.append(f"最后一次失败的原因：{last_failure}")
        parts.append("你可以把请求说得更具体（例如写明变量名或要用的方法），或让我继续。")
        return "\n".join(parts)
    reason = "the step budget ran out" if error == "max_steps_exceeded" else "the same tool call repeated"
    parts = [f"This request did not finish: {reason} before I could answer or propose anything."]
    if distinct:
        parts.append("Checked: " + ", ".join(distinct[:8]) + ".")
    if last_failure:
        parts.append(f"Last failure: {last_failure}")
    parts.append("Try a more specific request (name the variables or the method), or ask me to continue.")
    return "\n".join(parts)


def provider_failure_message(language: str, error: str) -> str:
    """Why the answer is missing when the model provider failed mid-turn.

    Nothing the provider did can have changed data or a model: a change needs
    the user's confirmation, so the user can simply ask again. A read-only
    analysis the Agent ran earlier in the turn did run and stays recorded.
    """

    if error.endswith(("upstream_401", "upstream_403")):
        # Retrying cannot help a rejected key; say where to fix it.
        if language == "zh":
            return (
                f"AI 服务商拒绝了这次请求（{error}），通常是 API key 无效、过期或没有权限。"
                "我没有给出回答，也没有改动你的数据或模型。请在设置里检查这个服务商的 API key。"
            )
        return (
            f"The AI provider rejected the request ({error}), usually because the API key is invalid, expired or "
            "lacks access. There is no answer and nothing in your data or models was changed. "
            "Check this provider's API key in Settings."
        )
    if language == "zh":
        return (
            f"AI 服务商这次没有正常响应（{error}），我没有给出回答，也没有改动你的数据或模型。"
            "请稍后重试；如果反复出现，请在设置里检查 AI 服务商的配置和网络。"
        )
    return (
        f"The AI provider did not respond properly ({error}), so there is no answer and nothing in your data "
        "or models was changed. Please try again; if it keeps happening, check the AI provider settings and the network."
    )


def interrupted_reply_note(language: str) -> str:
    """Appended to a reply the provider cut off halfway: the numeric check
    runs only on a finished reply, so the partial text was never checked."""

    if language == "zh":
        return "（AI 服务商的连接中断，这条回答没有写完，其中的数字也没有经过核对。请让我重新回答。）"
    return (
        "(The AI provider's connection dropped, so this reply was cut off and its numbers were not checked. "
        "Ask me to answer again.)"
    )
