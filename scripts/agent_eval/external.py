"""External benchmark tasks: QRData subset, BLADE analyses, the red-card data.

Sources (downloaded to ``local/external/``, not in Git):

* QRData (Liu et al., Findings of ACL 2024), github.com/xxxiaol/QRData at
  de450af4; data CC BY-NC 4.0 (evaluation use only). Scored with the paper's
  own rule (3 % relative tolerance for numbers, prefix match for choices).
* BLADE (Gu et al., Findings of EMNLP 2024), github.com/behavioral-data/BLADE
  at 6118fa8d; datasets ODC-By. Full analyses graded by the rubric judge, with
  the expert annotations' model specifications as the reference.
* The red-card question (Silberzahn et al. 2018, 29 teams) is BLADE's
  ``soccer`` dataset; the teams' odds ratios ranged from 0.89 to 2.93 with
  median 1.31, which the grader uses as the many-analysts reference.

The subset is chosen once, deterministically, and frozen in
``local/agent-eval/external_subset.json`` before the baseline.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = ROOT / "local" / "external"
QRDATA = EXTERNAL / "QRData" / "benchmark"
BLADE = EXTERNAL / "BLADE" / "blade_bench" / "datasets"
BLADE_DATASETS = ("affairs", "amtl", "boxes", "caschools", "crofoot", "fish", "hurricane", "mortgage",
                  "panda_nuts", "reading", "soccer", "teachingratings")
SOCCER_REFERENCE = {"teams": 29, "odds_ratio_min": 0.89, "odds_ratio_max": 2.93, "odds_ratio_median": 1.31}

ANSWER_ZH = ("\n\n请完成分析后，在回答最后单独一行写出最终答案，格式为：FINAL ANSWER: <答案>。"
             "选择题只写选项本身；数值题写数值（可带 %）。")
ANSWER_EN = ("\n\nAfter the analysis, end your reply with a separate line in the form FINAL ANSWER: <answer>. "
             "For multiple choice write only the option; for a number write the number (a % sign is allowed).")


@dataclass(frozen=True)
class ExternalTask:
    id: str
    source: str
    language: str
    prompt: str
    data_path: Path
    answer: str | None = None
    question_type: str | None = None
    reference: dict[str, Any] | None = None


def _numeric_columns(path: Path, limit: int = 200) -> list[str]:
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        rows = [row for _, row in zip(range(limit), reader)]
        names = reader.fieldnames or []
    numeric = []
    for name in names:
        values = [row.get(name) for row in rows if row.get(name) not in (None, "", "NA")]
        try:
            [float(v) for v in values]
        except ValueError:
            continue
        if values:
            numeric.append(name)
    return numeric


def seed_model_for(path: Path) -> dict[str, str]:
    import re

    # Row labels are not variables: a person would not regress on them.
    numeric = [c for c in _numeric_columns(path)
               if not re.fullmatch(r"(rownames|unnamed.*|index|.*_id|id)", c.strip().lower())]
    if len(numeric) < 2:
        raise ValueError(f"{path.name}: needs two numeric columns for the import model")
    return {"mode": "auto", "model_type": "ols", "covariance": "unadjusted", "y": numeric[0], "x": numeric[1]}


def qrdata_subset(per_cell: int = 10, per_source: int = 4, seed: int = 20261017) -> list[ExternalTask]:
    items = json.loads((QRDATA / "QRData.json").read_text(encoding="utf-8"))
    rng = random.Random(seed)
    cells: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for index, item in enumerate(items):
        files = item["data_files"]
        path = QRDATA / "data" / files[0]
        if len(files) != 1 or not path.exists() or path.stat().st_size > 5_000_000:
            continue
        try:
            seed_model_for(path)
        except (ValueError, OSError):
            continue
        category = "causal" if "Causality" in item["meta_data"]["keywords"] else "statistical"
        cells.setdefault((category, item["meta_data"]["question_type"]), []).append((index, item))
    chosen = []
    for key in sorted(cells):
        pool = cells[key][:]
        rng.shuffle(pool)
        sources: dict[str, int] = {}
        picked = 0
        for index, item in pool:
            source = item["meta_data"]["reference"]
            if sources.get(source, 0) >= per_source:
                continue
            sources[source] = sources.get(source, 0) + 1
            chosen.append(ExternalTask(
                id=f"qrdata.{index:03d}", source="qrdata", language="en",
                prompt=f"{item['data_description']}\n\n{item['question']}{ANSWER_EN}",
                data_path=QRDATA / "data" / item["data_files"][0], answer=item["answer"],
                question_type=item["meta_data"]["question_type"],
                reference={"category": key[0], "source": source}))
            picked += 1
            if picked >= per_cell:
                break
    return chosen


def blade_tasks() -> list[ExternalTask]:
    tasks = []
    for name in BLADE_DATASETS:
        info = json.loads((BLADE / name / "info.json").read_text(encoding="utf-8"))
        description = info["data_desc"]["dataset_description"]
        question = info["research_questions"][0]
        specs = []
        annotations = BLADE / name / "annotations.csv"
        if annotations.exists():
            csv.field_size_limit(10_000_000)
            with annotations.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    if row.get("model_spec_json"):
                        specs.append(row["model_spec_json"][:600])
        reference = {"expert_model_specs": specs[:12]}
        if name == "soccer":
            reference["many_analysts"] = SOCCER_REFERENCE
        tasks.append(ExternalTask(
            id=f"blade.{name}", source="blade", language="en",
            prompt=(f"{description}\n\nResearch question: {question}\n\nPlease carry out a complete analysis that would "
                    "hold up in peer review and write it up. End with a separate line FINAL ANSWER: <your conclusion in one sentence, with the key estimate>."),
            data_path=BLADE / name / "data.csv", reference=reference))
    return tasks


def qrdata_correct(answer: str, reply: str, question_type: str) -> bool | None:
    """QRData's own scoring rule, applied to the FINAL ANSWER line."""
    import re

    lines = [line for line in reply.splitlines() if "FINAL ANSWER" in line.upper()]
    if not lines:
        return None
    pred = lines[-1].split(":", 1)[-1].strip().strip("*` ").lower()
    gold = answer.strip().lower()
    if question_type == "numerical":
        def as_float(text):
            match = re.search(r"-?\d+\.?\d*%?", text)
            if not match:
                return None
            value = match.group()
            return float(value[:-1]) / 100 if value.endswith("%") else float(value)
        g, p = as_float(gold), as_float(pred)
        if g is None or p is None:
            return False
        return min(g * 0.97, g * 1.03) < p < max(g * 0.97, g * 1.03)
    return pred[: len(gold)] == gold
