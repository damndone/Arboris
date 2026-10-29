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
    from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    notes = []
    changes = proposal.get("changes") or {}
    for step in changes.get("steps", []):
        contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(step.get("operation_id"))
        note = contract.proposal_notes.get(language) if contract is not None else None
        if note and note not in notes:
            notes.append(note)
    if notes:
        body += "\n" + "\n".join(notes)
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

    if error == "analysis_recovery_limit":
        if language == "zh":
            return ("部分完成：同一步已失败 2 次，已暂停自动尝试。\n"
                + "已记录原因：" + (last_failure or "工具未能完成该步骤。")[:300]
                + "\n修正选项：根据该错误核对数据、变量和方法条件，修订方案后明确继续；或保留缺项并结束。"
                + "已完成的操作与证据保留，不自动切换方法或降低标准。")
        return ("Partial completion: this step failed 2 times; automatic attempts have stopped.\n"
            + "Recorded failure: " + (last_failure or "The tool could not complete this step.")[:300]
            + "\nCorrection options: check the data, variables and method conditions, then explicitly continue with a revised plan; or finish with the gap recorded."
            + " Completed operations and evidence are retained; no automatic method substitution or relaxed criteria.")
    distinct = list(dict.fromkeys(tools_used))
    if language == "zh":
        reason = "步数预算已用完" if error == "max_steps_exceeded" else "检测到重复调用同一工具"
        parts = [f"这次请求没有完整交付：{reason}。已执行的操作与证据仍保留，执行状态以确认回执为准。"]
        if distinct:
            parts.append("已调用工具（调用不代表执行成功）：" + "、".join(distinct[:8]) + "。")
        if last_failure:
            parts.append(f"最后一次失败的原因：{last_failure}")
        parts.append("下一步先核对已有结果和最后失败，明确剩余工作；需要补充变量含义、数据或权限时再说明，避免重复计算。")
        return "\n".join(parts)
    reason = "the step budget ran out" if error == "max_steps_exceeded" else "the same tool call repeated"
    parts = [f"This request did not finish: {reason}. Existing operations and evidence are retained; "
             "execution status comes from confirmed receipts."]
    if distinct:
        parts.append("Tools called (a call does not imply success): " + ", ".join(distinct[:8]) + ".")
    if last_failure:
        parts.append(f"Last failure: {last_failure}")
    parts.append("Next, inspect existing results and the last failure, then identify the remaining work. "
                 "State any missing variable meaning, data or permission before continuing; avoid duplicate computation.")
    return "\n".join(parts)


def provider_failure_message(language: str, error: str) -> str:
    """Why the answer is missing when the model provider failed mid-turn.

    Earlier approved operations may already have run. A later provider failure
    does not undo them, and must not tell the person that nothing changed.
    """

    if error == "provider_output_limit":
        if language == "zh":
            return ("本次回复达到模型输出上限（provider_output_limit），没有写完，不能作为完整回答；"
                    "其中的数字尚未核验。未完成的工具请求不会执行，已执行的操作与证据仍保留。"
                    "没有自动重试；建议将剩余报告拆成较小步骤，核对已有结果后再明确继续。")
        return ("The reply reached the model output limit (provider_output_limit) and is incomplete; "
                "its numbers are unverified. Unfinished tool requests are not executed; earlier operations "
                "and evidence are retained. No automatic retry was made. Split the remaining report into "
                "smaller steps, inspect existing results, then explicitly continue.")
    if error == "agent_timeout":
        if language == "zh":
            return "这次请求超时（agent_timeout），没有生成完整回答。已经执行的操作与证据仍保留；你可以重试或让我继续。"
        return "This request timed out (agent_timeout) before a complete answer was produced. Executed operations and evidence are retained; retry or ask me to continue."
    if error.endswith(("upstream_401", "upstream_403")):
        # Retrying cannot help a rejected key; say where to fix it.
        if language == "zh":
            return (
                f"AI 服务商拒绝了这次请求（{error}），通常是 API key 无效、过期或没有权限。"
                "本次回答未完成；此前已执行的操作与证据仍保留。请在设置里检查这个服务商的 API key，"
                "恢复后先核对已有结果再继续。"
            )
        return (
            f"The AI provider rejected the request ({error}), usually because the API key is invalid, expired or "
            "lacks access. The answer is incomplete; earlier operations and evidence are retained. "
            "Check this provider's API key in Settings, then inspect existing results before continuing."
        )
    if language == "zh":
        return (
            f"AI 服务商这次没有正常响应（{error}），本次回答未完成；此前已执行的操作与证据仍保留。"
            "请核对已有结果后再继续；如果反复出现，请在设置里检查 AI 服务商的配置和网络。"
        )
    return (
        f"The AI provider did not respond properly ({error}), so the answer is incomplete; earlier operations "
        "and evidence are retained. Inspect existing results before continuing; if it keeps happening, "
        "check the AI provider settings and the network."
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
