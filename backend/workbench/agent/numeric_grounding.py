"""Every number the Agent shows must come from a result.

A language model rounds and subtracts in its head, and sometimes gets it
wrong (0.09849 written as 0.099, 5.123 - 4.022 written as 1.100). Prompting
alone cannot rule that out, so the rule is enforced here:

- ``calculate`` does arithmetic on result values in code: differences,
  ratios, percentages, exp/log. The model quotes its value.
- ``check`` runs before a reply is shown. Every decimal number in the reply
  must equal some number the model was given -- a tool result, a server
  record, the user's own words, or a ``calculate`` value whose operands are
  themselves supported -- rounded correctly to the digits written. A reply
  that fails goes back to the model once with the offending numbers and the
  closest real values (``correction_message``); if the rewrite still fails,
  the reply is shown with a visible warning naming the unverified numbers
  (``unverified_note``). Nothing is silently rewritten.

Whole numbers below 1,000 and years are not checked: counts of tests,
levels and codes are too often legitimate prose.
"""

from __future__ import annotations

import ast
import bisect
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CHECK_MESSAGE_NAME = "numeric_check"
CALCULATE_TOOL_ID = "calculate"
MAX_REPAIRS = 1

# ASCII-only boundaries: in Python's Unicode regex a Chinese character is a
# word character, so "系数为0.099" would otherwise hide the number.
_REPLY_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.,])"
    r"(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+(?:[eE][-+]?\d+)?)?)"
    r"(?![A-Za-z0-9_]|[.,]\d)"
)
# Whole numbers are checked from here up: smaller ones are too often prose
# ("3 tests", "the 5% level", "1 = male"). Years are prose too.
_MIN_CHECKED_INTEGER = 1000
_YEARS = range(1900, 2101)
# Letters on either side mean an identifier or a hash ("run-3e45ab"), not a number.
_EVIDENCE_NUMBER = re.compile(r"(?<![0-9A-Za-z_.])\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z_])")

# Significance levels and coverage people state without citing a result;
# exempt only where the wording shows they are thresholds ("p < 0.05",
# "the 0.05 level", "α = 0.05").
_CONVENTIONAL = frozenset(Decimal(value) for value in ("0.001", "0.01", "0.05", "0.1", "0.10", "0.9", "0.90", "0.95", "0.99"))
_THRESHOLD_BEFORE = re.compile(
    r"(?:[<>≤≥＜＞]|α|alpha|显著性水平|低于|高于|小于|大于|超过|不到|不足|below|above|under|over|exceeds?|than)\s*=?\s*$",
    re.IGNORECASE,
)
_THRESHOLD_AFTER = re.compile(r"^\s*(?:的)?\s*(?:水平|显著性水平|level|significance)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    """A reply number no result supports, with the closest real values."""

    text: str
    closest: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "closest": list(self.closest)}


class Evidence:
    """The numbers a reply may use, sorted for window lookups."""

    def __init__(self, values: Iterable[Decimal]) -> None:
        unique = sorted({abs(value) for value in values if value.is_finite()})
        self._values = unique
        self._floats = [float(value) for value in unique]

    def __len__(self) -> int:
        return len(self._values)

    def supports(self, value: Decimal) -> bool:
        quantum = Decimal(1).scaleb(value.as_tuple().exponent)
        if value == value.to_integral_value() and value.as_tuple().exponent >= 0 and value != 0:
            # 34,000 is written to the thousand: trailing zeros set the precision.
            digits = str(int(value))
            quantum = Decimal(1).scaleb(len(digits) - len(digits.rstrip("0")))
        for candidate in self._window(value, quantum):
            if _rounds_to(candidate, quantum, value):
                return True
            if _rounds_to(candidate * 100, quantum, value):  # 0.0985 → 9.85%
                return True
        return False

    def closest(self, value: Decimal, limit: int = 2) -> tuple[str, ...]:
        if not self._values:
            return ()
        target = float(value)
        index = bisect.bisect_left(self._floats, target)
        nearby = self._values[max(index - limit, 0): index + limit]
        ranked = sorted(nearby, key=lambda candidate: abs(float(candidate) - target))
        return tuple(_plain(candidate) for candidate in ranked[:limit])

    def _window(self, value: Decimal, quantum: Decimal) -> list[Decimal]:
        found: list[Decimal] = []
        for scale in (Decimal(1), Decimal(100)):
            low = float((value - quantum) / scale)
            high = float((value + quantum) / scale)
            start = bisect.bisect_left(self._floats, low)
            stop = bisect.bisect_right(self._floats, high)
            found.extend(self._values[start:stop])
        return found


def _rounds_to(candidate: Decimal, quantum: Decimal, value: Decimal) -> bool:
    try:
        return (
            candidate.quantize(quantum, rounding=ROUND_HALF_UP) == value
            or candidate.quantize(quantum, rounding=ROUND_HALF_EVEN) == value
        )
    except InvalidOperation:
        return False


def _plain(value: Decimal) -> str:
    text = format(value.normalize(), "f") if abs(value.adjusted()) < 12 else str(value)
    return text


def _decimal(text: str) -> Decimal | None:
    try:
        value = Decimal(text.replace(",", ""))
    except (InvalidOperation, ArithmeticError):
        return None
    if not value.is_finite() or not -400 < value.adjusted() < 400:
        return None
    return value


def _numbers_in(text: str) -> list[Decimal]:
    values = []
    for token in _EVIDENCE_NUMBER.findall(text):
        value = _decimal(token)
        if value is not None:
            values.append(value)
    return values


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def evidence_from_messages(messages: Sequence[Mapping[str, Any]]) -> Evidence:
    """Every number the model was given, except its own words.

    The Agent's replies are not evidence (a wrong number must not certify
    itself on the next turn), nor is a numeric-check correction, which quotes
    the wrong numbers it rejects. A ``calculate`` value counts only when every
    decimal operand it used is itself supported.
    """

    values: list[Decimal] = []
    calculations: list[Mapping[str, Any]] = []
    for message in messages:
        if message.get("role") == "assistant" or message.get("name") == CHECK_MESSAGE_NAME:
            continue
        text = _content_text(message.get("content"))
        if message.get("role") == "tool" and message.get("name") == CALCULATE_TOOL_ID:
            calculations.extend(_calculation_records(text))
            continue
        values.extend(_numbers_in(text))
    evidence = Evidence(values)
    for record in calculations:
        operands = [_decimal(str(operand)) for operand in record.get("operands") or ()]
        if all(operand is not None and (operand == operand.to_integral_value() or evidence.supports(abs(operand))) for operand in operands):
            value = _decimal(str(record.get("value")))
            if value is not None:
                values.append(value)
                evidence = Evidence(values)
    return evidence


def _calculation_records(text: str) -> list[Mapping[str, Any]]:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return []
    output = payload.get("output") if isinstance(payload, Mapping) else None
    results = output.get("results") if isinstance(output, Mapping) else None
    return [item for item in results or () if isinstance(item, Mapping)]


def _is_threshold(text: str, start: int, end: int, value: Decimal) -> bool:
    if value not in _CONVENTIONAL:
        return False
    return bool(_THRESHOLD_BEFORE.search(text[max(start - 12, 0):start]) or _THRESHOLD_AFTER.match(text[end:end + 12]))


def check(reply: str, messages: Sequence[Mapping[str, Any]]) -> tuple[Finding, ...]:
    """The decimal numbers in ``reply`` that no given number supports."""

    tokens = list(_REPLY_NUMBER.finditer(reply or ""))
    if not tokens:
        return ()
    evidence = evidence_from_messages(messages)
    findings: list[Finding] = []
    seen: set[str] = set()
    for match in tokens:
        text = match.group("number")
        value = _decimal(text)
        if value is None or text in seen:
            continue
        value = abs(value)
        if "." not in text and (value < _MIN_CHECKED_INTEGER or int(value) in _YEARS):
            continue
        if _is_threshold(reply, match.start(), match.end(), value) or evidence.supports(value):
            continue
        seen.add(text)
        findings.append(Finding(text, evidence.closest(value)))
    return tuple(findings)


def _finding_line(finding: Finding, language: str) -> str:
    if not finding.closest:
        return finding.text
    closest = ", ".join(finding.closest)
    if language == "zh":
        return f"{finding.text}（最接近的结果值：{closest}）"
    return f"{finding.text} (closest result values: {closest})"


def correction_message(findings: Sequence[Finding]) -> str:
    """What the model is told when its draft fails the check."""

    lines = "\n".join(f"- {_finding_line(finding, 'en')}" for finding in findings)
    return (
        "[Workbench numeric check -- an automatic message, not from the user] These numbers in your "
        "last answer do not match any result you were given, at the digits you wrote them:\n"
        f"{lines}\n"
        "That answer has been withdrawn. Answer the user's question again, in full and in the user's "
        "language. Round numbers for reading (about four significant digits), always from the full "
        "value in the results: 0.098491 is 0.098 or 0.0985, never 0.099; do not paste full precision. "
        "For a number derived from results -- a difference, ratio, percentage, sum or odds ratio -- "
        "call the calculate tool and quote its value. Leave out any number you cannot source. Do not "
        "mention this check."
    )


def unverified_note(findings: Sequence[Finding], language: str) -> str:
    """The warning shown with a reply whose rewrite still failed the check."""

    items = "; ".join(_finding_line(finding, language) for finding in findings)
    if language == "zh":
        return f"⚠️ Workbench 数字核对：以下数字与任何计算结果都对不上，请勿引用：{items}。"
    return f"⚠️ Workbench numeric check: these numbers do not match any computed result; do not rely on them: {items}."


def unchecked_note(language: str) -> str:
    if language == "zh":
        return "⚠️ Workbench 未能自动核对本条回复中的数字，请对照结果查看。"
    return "⚠️ Workbench could not check the numbers in this reply; compare them with the results."


# --- calculate -------------------------------------------------------------

_FUNCTIONS = {
    "exp": math.exp,
    "log": math.log,
    "ln": math.log,
    "log10": math.log10,
    "sqrt": math.sqrt,
    "abs": abs,
}
_BINARY = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
    ast.Pow: lambda left, right: left ** right,
}
MAX_EXPRESSION_CHARS = 400


class CalculationError(ValueError):
    pass


def evaluate(expression: str) -> tuple[float, tuple[str, ...]]:
    """Evaluate arithmetic on literal numbers; return the value and operands.

    Only numbers, + - * / **, parentheses and exp/log/ln/log10/sqrt/abs are
    accepted. The operands are returned as written so the numeric check can
    confirm each one came from a result.
    """

    if len(expression) > MAX_EXPRESSION_CHARS:
        raise CalculationError(f"expression longer than {MAX_EXPRESSION_CHARS} characters")
    try:
        tree = ast.parse(expression.replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise CalculationError(f"not an arithmetic expression: {exc.msg}") from exc
    operands: list[str] = []

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            operands.append(ast.get_source_segment(source, node) or repr(node.value))
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise CalculationError("exponent larger than 100")
            try:
                return float(_BINARY[type(node.op)](left, right))
            except ZeroDivisionError as exc:
                raise CalculationError("division by zero") from exc
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS
            and len(node.args) == 1
            and not node.keywords
        ):
            try:
                return float(_FUNCTIONS[node.func.id](walk(node.args[0])))
            except (ValueError, OverflowError) as exc:
                raise CalculationError(f"{node.func.id} is undefined here") from exc
        raise CalculationError(
            "only numbers, + - * / ^, parentheses and exp, log, ln, log10, sqrt, abs are allowed"
        )

    source = expression.replace("^", "**")
    value = walk(tree)
    if not math.isfinite(value):
        raise CalculationError("the result is not a finite number")
    return value, tuple(operands)


def calculate(calculations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    results = []
    for item in calculations:
        label = str(item.get("label") or "")
        expression = str(item.get("expression") or "")
        try:
            value, operands = evaluate(expression)
        except CalculationError as exc:
            results.append({"label": label, "expression": expression, "error": str(exc)})
            continue
        results.append({
            "label": label,
            "expression": expression,
            "value": repr(value),
            "operands": list(operands),
        })
    return {
        "results": results,
        "note": "Quote these values; round only from the full value shown.",
    }
