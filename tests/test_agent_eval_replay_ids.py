"""Replaying a recorded round maps the identifiers the new run mints to the recorded ones."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_eval.recorder import _MintedIdMap  # noqa: E402

OLD_RUN, NEW_RUN = "20261103_091447_706280_8ed5b0f2", "20261103_121458_523867_77dec55a"
OLD_RECORD, NEW_RECORD = "oprec_" + "a" * 24, "oprec_" + "b" * 24


def _request(*contents):
    return {"messages": [{"role": "tool", "content": content} for content in contents]}


def test_identifiers_are_paired_by_kind_and_order_and_rewritten_in_the_recorded_reply():
    ids = _MintedIdMap()
    ids.learn(_request(f"head {OLD_RUN}", f"record {OLD_RECORD} of {OLD_RUN}"),
              _request(f"head {NEW_RUN}", f"record {NEW_RECORD} of {NEW_RUN}"))
    reply = f'{{"active_head_run_id": "{OLD_RUN}", "operation_record_id": "{OLD_RECORD}"}}'
    assert ids.rewrite(reply) == f'{{"active_head_run_id": "{NEW_RUN}", "operation_record_id": "{NEW_RECORD}"}}'


def test_a_kind_whose_counts_differ_in_a_message_is_not_paired_there_but_other_kinds_are():
    ids = _MintedIdMap()
    ids.learn(_request(f"{OLD_RUN} {OLD_RECORD} and {'oprec_' + 'c' * 24}"),
              _request(f"{NEW_RUN} {NEW_RECORD}"))
    assert ids.old_to_new == {OLD_RUN: NEW_RUN}
