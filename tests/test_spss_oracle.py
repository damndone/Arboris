"""v1.8.9 — Workbench's SPSS reading and writing against R ``foreign``.

There is no SPSS on the development machine. ``foreign::read.spss`` is an
independent SPSS parser (Workbench and R ``haven`` share ReadStat), so it is
the reference: files SPSS itself wrote (shipped with ``foreign``) must read
the same in Workbench, and every ``.sav`` Workbench writes must read back in
``foreign`` with the same values, labels and user-missing codes.

Set ``WORKBENCH_SPSS_ORACLE_FILES`` to a ``:``-separated list of local
``.sav`` files (for example the public GSS release) to run the same
comparison on them; those files never enter the repository.
"""

from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from tests.spss_oracle import RSCRIPT, describe, requires_foreign
from workbench.tabular_io import prepare_export, read_statistical, read_statistical_labels, write_prepared
from workbench.user_missing import apply_user_missing, normalize_user_missing

pytestmark = requires_foreign


def _foreign_file(name: str) -> Path:
    completed = subprocess.run(
        [RSCRIPT or "Rscript", "-e", f"cat(system.file('files', '{name}', package='foreign'))"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(completed.stdout.strip())


def _as_number(key: object) -> object:
    try:
        return float(str(key))
    except ValueError:
        return str(key).strip()


def _long_string_segment(name: str, frame: pd.DataFrame) -> bool:
    """SPSS stores a string longer than 255 bytes as segments (COMMENT, COMME1,
    ...); foreign lists each segment as a variable, SPSS and Workbench join them."""

    stem = name[:-1].casefold()
    return name[-1:].isdigit() and any(
        str(column).casefold().startswith(stem) and not pd.api.types.is_numeric_dtype(frame[column]) for column in frame.columns
    )


def _disagreements(path: Path, workdir: Path) -> list[str]:
    """Every way Workbench's reading of ``path`` differs from foreign's."""

    reference = describe(path, workdir)
    frame = read_statistical(path, "sav")
    labels = read_statistical_labels(path, "sav")
    missing = normalize_user_missing(labels.get("user_missing_values", {}))
    frame, _record = apply_user_missing(frame, missing)
    problems: list[str] = []
    for name, expected in reference.items():
        if name not in frame.columns:
            if not _long_string_segment(name, frame):
                problems.append(f"{name}: absent")
            continue
        series = frame[name]
        if pd.api.types.is_numeric_dtype(series):
            values = series.dropna()
            if len(values) != expected["n"]:
                problems.append(f"{name}: n {len(values)} != {expected['n']}")
            for statistic, ours in (("mean", values.mean()), ("sd", values.std())):
                theirs = expected.get(statistic)
                if theirs is not None and not math.isclose(float(ours), theirs, rel_tol=1e-9, abs_tol=1e-9):
                    problems.append(f"{name}: {statistic} {ours} != {theirs}")
        ours_label = labels.get("variable_labels", {}).get(name, "").strip()
        if ours_label != (expected.get("label") or "").strip():
            problems.append(f"{name}: label {ours_label!r} != {expected.get('label')!r}")
        # foreign omits the labels of codes it has turned into missing values.
        ours_values = {_as_number(k): str(v).strip() for k, v in labels.get("value_labels", {}).get(name, {}).items()}
        for code, label in (expected.get("value_labels") or {}).items():
            if ours_values.get(_as_number(code)) != str(label).strip():
                problems.append(f"{name}: value label {code!r} {ours_values.get(_as_number(code))!r} != {label!r}")
    return problems


@pytest.mark.parametrize("name", ["electric.sav", "testdata.sav"])
def test_files_written_by_spss_read_as_foreign_reads_them(name: str, tmp_path: Path) -> None:
    assert _disagreements(_foreign_file(name), tmp_path) == []


def test_a_sav_workbench_writes_reads_back_in_foreign(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "income": [3200.5, 4100.25, 999.0, 2800.0, None, 5100.75],
            "satisfaction": [1, 2, 3, 9, 2, 1],
            "region": ["north", "south", "east", "west", "north", "south"],
            "comment": ["good", "很好", "", "a" * 300, "ok", "满意"],
        }
    )
    labels = {
        "variable_labels": {"income": "月收入（元）", "satisfaction": "Job satisfaction", "region": "Region"},
        "value_labels": {"satisfaction": {"1": "低", "2": "中", "3": "高", "9": "Refused"}},
        "user_missing_values": {"income": [999], "satisfaction": [9]},
        "measurement_level": {"satisfaction": "ordinal"},
    }
    path = tmp_path / "workbench_export.sav"
    write_prepared(prepare_export(frame, labels, "sav"), path)

    reference = describe(path, tmp_path)

    assert reference["income"]["n"] == 4  # 999 and the empty cell are missing
    assert reference["income"]["mean"] == pytest.approx((3200.5 + 4100.25 + 2800.0 + 5100.75) / 4, rel=1e-12)
    assert reference["income"]["label"] == "月收入（元）"
    assert reference["satisfaction"]["n"] == 5  # 9 declared missing
    assert reference["satisfaction"]["value_labels"] == {"1": "低", "2": "中", "3": "高"}
    assert reference["region"]["n"] == 6
    assert reference["comment"]["n"] == 5
    assert frame["comment"][3] == read_statistical(path, "sav")["comment"][3]  # 300 characters, whole
    # And Workbench reads its own file exactly as foreign does.
    assert _disagreements(path, tmp_path) == []


def _local_files() -> list[Path]:
    value = os.environ.get("WORKBENCH_SPSS_ORACLE_FILES", "")
    return [Path(item) for item in value.split(":") if item]


@pytest.mark.skipif(not _local_files(), reason="WORKBENCH_SPSS_ORACLE_FILES is not set")
@pytest.mark.parametrize("path", _local_files(), ids=lambda path: path.name)
def test_local_spss_files_read_as_foreign_reads_them(path: Path, tmp_path: Path) -> None:
    assert _disagreements(path, tmp_path) == []
