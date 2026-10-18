"""Rubric grading of one finished task by a model judge.

The judge sees what a senior reviewer would: the research question, the
scenario's ground truth and known traps (which the Agent never saw), the
analyses the project actually contains (read from disk, not from the Agent's
prose), and the Agent's final answer. It scores five dimensions from 1 to 5
with a one-sentence reason each, as JSON. The same rubric is used for human
calibration (``agent_eval_grade.py --calibration``), so agreement between
judge and human can be measured.
"""

from __future__ import annotations

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
    rubric = "\n".join(f"- {key}: {text}" for key, text in RUBRIC.items())
    return (
        f"Research question given to the assistant:\n{task['prompt']}\n\n"
        f"Ground truth (hidden from the assistant):\n{json.dumps(scenario, ensure_ascii=False, indent=1)}\n\n"
        f"Analyses present in the project (read from disk):\n{json.dumps(facts, ensure_ascii=False, indent=1)[:24000]}\n\n"
        f"The assistant's final answer to the person:\n{final_answer[:12000]}\n\n"
        f"Score each dimension 1-5:\n{rubric}\n\n"
        'Reply as {"method": {"score": n, "reason": "..."}, "diagnostics": {...}, "robustness": {...}, '
        '"conclusion": {...}, "traceability": {...}}'
    )


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
