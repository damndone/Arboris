"""Local owner rubric and a separate, minimal outbound evidence contract.

The historical owner packet can contain restricted data. Outbound evidence
contains only fixed categories and coarse workflow facts and supports no
rubric scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

RUBRIC = {
    "method": "Is the estimation method appropriate for the question and the data-generating structure (identification, outcome type, dependence)? 5 = the method a careful expert would choose; 1 = a method that answers a different question or is biased here.",
    "diagnostics": "Were the checks that this design needs actually run (assumptions, specification, influence, weak instruments, unit roots, missingness, as relevant)? 5 = all key checks run and read correctly; 1 = none.",
    "robustness": "Were defensible alternative specifications or estimators run and compared? 5 = a well-chosen set with a clear reading; 1 = none.",
    "conclusion": "Is the conclusion correct and bounded: right size and sign relative to the truth, uncertainty stated, no causal or precision claims the design cannot support, known traps avoided? 5 = what an expert would write; 1 = wrong or overclaimed.",
    "traceability": "Can every reported number be traced to an analysis in the project, and is the write-up clear enough to hand to a reviewer? 5 = fully traceable and clear; 1 = untraceable or missing.",
}

SYSTEM = (
    "You are a senior applied statistician grading an analysis done by an assistant. "
    "Be strict and specific. Judge only from the material given. Reply with one JSON object and nothing else."
)


def build_prompt(task: dict[str, Any], scenario: dict[str, Any], facts: dict[str, Any], final_answer: str) -> str:
    """Build the historical, private owner packet for local review only."""
    rubric = "\n".join(f"- {key}: {text}" for key, text in RUBRIC.items())
    return (
        f"Research question given to the assistant:\n{task['prompt']}\n\n"
        f"Ground truth (hidden from the assistant):\n{json.dumps(scenario, ensure_ascii=False, indent=1)}\n\n"
        f"Analyses present in the project (read from disk):\n{json.dumps(facts, ensure_ascii=False, indent=1)[:70000]}\n\n"
        f"The assistant's final answer to the person:\n{final_answer[:12000]}\n\n"
        f"Score each dimension 1-5:\n{rubric}\n\n"
        'Reply as {"method": {"score": n, "reason": "..."}, "diagnostics": {...}, "robustness": {...}, '
        '"conclusion": {...}, "traceability": {...}}'
    )


OUTBOUND_PROTOCOL = "judge-structural-evidence/v1"
OUTBOUND_SYSTEM = (
    "This packet has only workflow status. The full rubric requires additional evidence. "
    'Reply with {"status":"insufficient_evidence"}. Do not grade or use tools or files.'
)
_KINDS = {"dev": "synthetic_dev", "blade": "blade_external"}
_COUNTS = {"none", "one", "multiple"}


class OutboundJudgeBlocked(ValueError):
    """No live reviewer is authorized for this projection."""


def require_outbound_approval() -> None:
    """Live review requires a separate scoped approval and transport review."""
    raise OutboundJudgeBlocked("live judge disabled pending explicit scoped approval and containment review")


@dataclass(frozen=True)
class OutboundPacket:
    kind: str
    completed_marker: bool
    turns: str
    confirmations: str


def _count_bucket(values: Any) -> str:
    if type(values) is not list:
        raise ValueError("invalid outbound workflow evidence")
    return "none" if not values else "one" if len(values) == 1 else "multiple"


def outbound_packet(record: Any) -> OutboundPacket:
    """Project a few fixed workflow facts without opening project or task sources."""
    if type(record) is not dict or record.get("status") != "ran":
        raise ValueError("unsupported outbound task state")
    suite = record.get("suite")
    if suite == "dev":
        kind = _KINDS["dev"]
    elif suite == "external" and record.get("source") == "blade":
        kind = _KINDS["blade"]
    else:
        raise ValueError("unsupported outbound task source")
    conversation = record.get("conversation")
    if type(conversation) is not dict or type(conversation.get("completed_marker")) is not bool:
        raise ValueError("invalid outbound completion evidence")
    return OutboundPacket(kind, conversation["completed_marker"], _count_bucket(conversation.get("turns")),
                          _count_bucket(conversation.get("confirmations")))


def outbound_prompt(packet: OutboundPacket) -> str:
    """Serialize a fixed schema at the boundary. A raw owner prompt fails here."""
    if (type(packet) is not OutboundPacket or type(packet.kind) is not str
            or packet.kind not in _KINDS.values() or type(packet.completed_marker) is not bool
            or any(type(value) is not str or value not in _COUNTS
                   for value in (packet.turns, packet.confirmations))):
        raise ValueError("invalid outbound judge packet")
    return json.dumps({"protocol": OUTBOUND_PROTOCOL, "rubric_status": "insufficient_evidence",
                       "kind": packet.kind, "completed_marker": packet.completed_marker,
                       "turns": packet.turns, "confirmations": packet.confirmations}, indent=2)


def outbound_result(text: str) -> dict[str, Any]:
    if json.loads(text) != {"status": "insufficient_evidence"}:
        raise ValueError("unexpected outbound judge response")
    return {"protocol": OUTBOUND_PROTOCOL, "status": "unscored", "reason": "insufficient_evidence"}


def parse(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("judge returned no JSON object")
    payload = json.loads(match.group(0))
    scores = {}
    for key in RUBRIC:
        item = payload.get(key) or {}
        score = item.get("score")
        if not isinstance(score, (int, float)) or not 1 <= score <= 5:
            raise ValueError(f"judge score for {key} missing or out of range")
        scores[key] = {"score": int(round(score)), "reason": str(item.get("reason") or "")}
    return scores
