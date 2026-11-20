"""A time-trend chart reaches a remote model as a summary of its series, its rows only where allowed.

2026-11-06 risk review, finding 1 (remainder): the chart's numeric source carried up to
400 row-level values, which the default remote policy never sends. The source now carries
an aggregate summary over every row (per-series statistics, a least-squares trend and
time-ordered bins) and the rows as a separately classified sample, so the checkpoint
withholds the rows unless the project allows rows for that provider. A preview over its
size bound stays parseable JSON, so the checkpoint can still see inside it.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from tests.test_egress import LOCAL, REMOTE, _send
from tests.test_figure_context import _run_with_figures
from workbench import egress
from workbench.artifacts import read_json, write_json
from workbench.egress import EgressPolicy, egress_project, read_audit, save_policy
from workbench.figure_context import (
    MAX_SOURCE_PREVIEW_CHARS,
    ROWS_PROTOCOL,
    SUMMARY_PROTOCOL,
    _bounded_preview,
    resolve_figure_ai_context,
    series_summary,
)


def _trend(tmp_path, frame: pd.DataFrame, time_column: str = "year"):
    project, run_id = _run_with_figures(tmp_path)
    run_root = project / "runs" / run_id
    (run_root / "figures" / "time_trend.png").write_bytes(b"\x89PNG trend")
    (run_root / "processed").mkdir(parents=True)
    frame.to_parquet(run_root / "processed" / "cleaned_dataset.parquet", index=False)
    write_json(run_root / "run_inputs.json", {"form": {"time_col": time_column}})
    index = read_json(run_root / "artifacts_index.json")
    index["artifacts"].extend([
        {"artifact_id": "time_trend", "path": "figures/time_trend.png", "artifact_type": "figure",
         "step": "visualization", "sha256": "g", "inputs": []},
        {"artifact_id": "cleaned_dataset", "path": "processed/cleaned_dataset.parquet", "artifact_type": "dataset",
         "step": "cleaning", "sha256": "h", "inputs": []},
    ])
    write_json(run_root / "artifacts_index.json", index)
    return project, resolve_figure_ai_context(project, run_id=run_id, artifact_id="time_trend")


def _panel(years: int = 12, units: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(20261109)
    year = np.repeat(np.arange(2000, 2000 + years), units)
    wage = 10.0 + 0.5 * (year - 2000) + rng.normal(0, 1, len(year))
    return pd.DataFrame({"year": year, "wage": np.round(wage, 6)})


def _figure_message(packet: dict) -> list[dict]:
    return [{"role": "system", "content": "Context packet:\n", egress.CONTEXT_PACKET_KEY: packet},
            {"role": "user", "content": "Explain this chart"}]


def test_the_summary_covers_every_row_by_time(tmp_path):
    frame = _panel()
    _, packet = _trend(tmp_path, frame)
    source = json.loads(packet["source"]["preview_json"])
    assert source["summary"]["protocol_version"] == SUMMARY_PROTOCOL
    wage = source["summary"]["observations"]["series"]["wage"]
    assert wage["n"] == len(frame) and wage["mean"] == pytest.approx(frame["wage"].mean())
    slope = np.polyfit(frame["year"], frame["wage"], 1)[0]
    assert wage["trend"]["slope"] == pytest.approx(slope) and wage["trend"]["per"] == "year"
    by_year = frame.groupby("year")["wage"].mean()
    bins = wage["bins"]
    assert [b["time_start"] for b in bins] == list(by_year.index)  # 12 time values: one bin each
    assert [b["mean"] for b in bins] == pytest.approx(list(by_year))
    assert [b["n"] for b in bins] == [3] * 12
    assert source["rows"]["protocol_version"] == ROWS_PROTOCOL


def test_many_time_values_fall_into_at_most_fifty_ordered_bins(tmp_path):
    frame = _panel(years=400, units=1)
    _, packet = _trend(tmp_path, frame)
    wage = json.loads(packet["source"]["preview_json"])["summary"]["observations"]["series"]["wage"]
    assert len(wage["bins"]) <= 50 and sum(b["n"] for b in wage["bins"]) == len(frame)
    starts = [b["time_start"] for b in wage["bins"]]
    assert starts == sorted(starts) and all(b["time_end"] < n["time_start"] for b, n in zip(wage["bins"], wage["bins"][1:]))


def test_a_remote_provider_gets_the_summary_and_never_the_rows(tmp_path, monkeypatch):
    frame = _panel()
    project, packet = _trend(tmp_path, frame)
    with egress_project(project):
        body = json.dumps(_send(monkeypatch, _figure_message(packet), REMOTE))
    inner = frame["wage"][(frame["wage"] > frame["wage"].min()) & (frame["wage"] < frame["wage"].max())]
    assert not [value for value in inner if repr(float(value)) in body]  # no single row's value leaves
    sent = json.loads(json.loads(body)["messages"][0]["content"].removeprefix("Context packet:\n"))
    summary = json.loads(sent["source"]["preview_json"])["summary"] if isinstance(sent["source"]["preview_json"], str) \
        else sent["source"]["preview_json"]["summary"]
    assert summary["protocol_version"] == SUMMARY_PROTOCOL
    assert summary["observations"]["series"]["wage"]["mean"] == pytest.approx(frame["wage"].mean())
    [record] = read_audit(project)
    assert ROWS_PROTOCOL in record["decisions"][0]["withheld_protocols"]


@pytest.mark.parametrize("allowed_by", ["project", "local"])
def test_rows_reach_a_provider_allowed_to_receive_rows(tmp_path, monkeypatch, allowed_by):
    frame = _panel()
    project, packet = _trend(tmp_path, frame)
    config = REMOTE
    if allowed_by == "project":
        save_policy(project, EgressPolicy(providers={"deepseek": frozenset(egress.REMOTE_DEFAULT_ALLOW | {"rows"})}))
    else:
        config = LOCAL
    with egress_project(project):
        body = json.dumps(_send(monkeypatch, _figure_message(packet), config))
    assert repr(float(frame.sort_values("year")["wage"].iloc[0])) in body


def test_a_wide_trend_keeps_its_summary_and_valid_json_inside_the_bound(tmp_path):
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({"year": np.arange(1000), **{f"s{i}": rng.normal(size=1000) for i in range(12)}})
    _, packet = _trend(tmp_path, frame)
    text = packet["source"]["preview_json"]
    assert len(text) <= MAX_SOURCE_PREVIEW_CHARS
    source = json.loads(text)
    assert set(source["summary"]["observations"]["series"]) == {f"s{i}" for i in range(12)}
    assert packet["source"]["preview_truncated"] is True


def test_an_oversized_preview_is_cut_as_structure_not_text():
    payload = {"columns": {f"column_{i}": {"mean": i + 0.123456, "std": 1.5} for i in range(2000)}}
    text, truncated = _bounded_preview(payload)
    assert truncated and len(text) <= MAX_SOURCE_PREVIEW_CHARS
    assert json.loads(text)["columns"]


def test_a_non_numeric_time_column_trends_per_position():
    frame = pd.DataFrame({"quarter": ["2020Q1", "2020Q2", "2020Q3"], "sales": [1.0, 2.0, 4.0]})
    summary = series_summary(frame, "quarter", ["sales"])
    assert summary["series"]["sales"]["trend"]["per"] == "time position"
    assert summary["series"]["sales"]["trend"]["slope"] == pytest.approx(1.5)
