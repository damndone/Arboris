"""JSON Lines must be split at newlines, never with ``str.splitlines()``.

``json.dumps(..., ensure_ascii=False)`` leaves U+2028, U+2029 and U+0085 raw
inside strings, and ``str.splitlines()`` splits there, so one such character in
a message made a whole session log unreadable (found 2026-11-03). The 21
backend readers the guard first listed now use ``jsonl_lines``; the lint rule
``jsonl-split-at-newline`` (scripts/lint_rules.py) keeps new ones out of
``backend/`` and ``scripts/``.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from workbench import analysis_ledger
from workbench.jsonl_store import jsonl_lines, read_jsonl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import lint_rules  # noqa: E402

SEPARATORS = "\u2028\u2029\u0085"


def _offences(source: str) -> int:
    return len(list(lint_rules.splitlines_jsonl_readers(ast.parse(source))))


def test_no_jsonl_reader_splits_at_unicode_line_separators():
    found = [str(violation) for violation in lint_rules.jsonl_is_split_at_newlines_only(ROOT)]
    assert not found, "\n".join(found)


def test_the_rule_sees_the_session_log_pattern():
    assert _offences("for line in data.decode('utf-8').splitlines():\n    index(json.loads(line))\n") == 1
    assert _offences("rows = [json.loads(x) for x in raw.splitlines() if x]\n") == 1
    assert _offences("lines = raw.splitlines()\nfor i, line in enumerate(lines):\n    json.loads(line)\n") == 1
    assert _offences("for line in data.split(b'\\n'):\n    json.loads(line)\n") == 0
    assert _offences("for line in jsonl_lines(data):\n    json.loads(line)\n") == 0


def test_jsonl_lines_keeps_a_record_with_unicode_separators_whole():
    record = {"content": f"first{SEPARATORS}second"}
    text = json.dumps(record, ensure_ascii=False) + "\n" + json.dumps({"n": 2}) + "\n"
    assert len(text.splitlines()) == 5
    assert [json.loads(line) for line in jsonl_lines(text)] == [record, {"n": 2}]
    assert [json.loads(line) for line in jsonl_lines(text.encode("utf-8"))] == [record, {"n": 2}]


def test_jsonl_lines_matches_splitlines_on_plain_newline_text():
    for text in ("", "\n", "a", "a\n", "a\nb", "a\nb\n", "a\n\nb\n"):
        assert jsonl_lines(text) == text.splitlines()
        assert jsonl_lines(text, keepends=True) == text.splitlines(keepends=True)


def test_stores_read_back_records_with_unicode_separators(tmp_path):
    record = {"event_id": "e1", "content": f"a{SEPARATORS}b"}
    line = json.dumps(record, ensure_ascii=False) + "\n"
    store = tmp_path / "store.jsonl"
    store.write_text(line, encoding="utf-8")
    assert read_jsonl(store) == [record]
    ledger = analysis_ledger.ledger_path(tmp_path)
    ledger.parent.mkdir(parents=True)
    ledger.write_text(line, encoding="utf-8")
    assert analysis_ledger.read(tmp_path) == [record]
