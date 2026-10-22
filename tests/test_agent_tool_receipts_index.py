"""Receipt reads use the shared log index yet keep the whole-log strict check."""
import json

import pytest

from workbench.agent import tool_receipts
from workbench.agent.session import JsonlSessionRepository


def _case(tmp_path, invocation="invocation-index"):
    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("session", chain_id="chain", role="chain")
    arguments = {"session_id": "session", "command_id": "command", "provider_step": 1, "tool_call_id": "call",
                 "invocation_id": invocation, "tool_call": {"tool_call_id": "call", "tool_id": "inspect", "arguments": {}}}
    return repository, arguments, {"ok": True, "output": {"value": 3}, "error": None}


def test_a_corrupt_line_appended_after_a_good_read_is_still_refused(tmp_path):
    repository, arguments, payload = _case(tmp_path)
    entry = tool_receipts.persist(repository, payload=payload, **arguments)
    assert tool_receipts.read(repository, **arguments) == entry
    repository.append("session", "message", {"role": "user", "content": "later"})
    path = repository._session_path("session")
    lines = path.read_text().splitlines()
    lines[-1] = lines[-1].replace('"content": "later"', '"content": "later", "content": "again"')
    assert lines[-1].count('"content"') == 2
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(tool_receipts.ToolReceiptError, match="invalid tool receipt session log"):
        tool_receipts.read(repository, **arguments)


def test_reads_parse_only_new_lines_and_the_matching_receipt(tmp_path, monkeypatch):
    repository, arguments, payload = _case(tmp_path)
    for i in range(30):
        repository.append("session", "message", {"role": "user", "content": f"turn {i}"})
    tool_receipts.persist(repository, payload=payload, **arguments)
    strict = []
    original = tool_receipts._strict_row
    monkeypatch.setattr(tool_receipts, "_strict_row", lambda line: strict.append(line) or original(line))
    for _ in range(3):
        assert tool_receipts.read(repository, **arguments) is not None
    # Nothing was appended, so each read strictly parses only the one receipt line.
    assert len(strict) == 3 and all('"tool_receipt"' in line for line in strict)


def test_an_unknown_invocation_reads_as_missing(tmp_path):
    repository, arguments, payload = _case(tmp_path)
    tool_receipts.persist(repository, payload=payload, **arguments)
    other = {**arguments, "invocation_id": "never-written"}
    assert tool_receipts.read(repository, **other) is None
    assert json.loads(repository._session_path("session").read_text().splitlines()[-1])["entry_type"] == "tool_receipt"
