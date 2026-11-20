"""CSV and Excel uploads are previewed by the reader the run imports them with.

2026-11-06 risk review, finding 4: the browser parsed spreadsheets with xlsx 0.18.5
(CVE-2023-30533 prototype pollution, CVE-2024-22363 ReDoS) on its main thread, typed and
transposed them differently from the import, and read whole workbooks. The server now
previews them with ingestion.read_frame_bounded in a child process it can stop, after
checking the archive, and transposes exactly as the import does.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.app import app
from workbench.config import WorkbenchConfig
from workbench.ingestion import _read_frame, read_frame_bounded
from workbench.projects import create_project

client = TestClient(app)


def _preview(root, name: str, payload: bytes, **fields):
    return client.post("/uploads/preview", data={"project_root": str(root), **fields},
                       files={"file": (name, io.BytesIO(payload), "application/octet-stream")})


def _records(frame: pd.DataFrame) -> list[dict]:
    return [{str(k): (None if pd.isna(v) else v.isoformat() if isinstance(v, pd.Timestamp) else
                      v.item() if hasattr(v, "item") else v) for k, v in row.items()}
            for row in frame.astype(object).to_dict(orient="records")]


def test_a_csv_preview_is_the_imported_frame_with_the_whole_file_s_row_count(tmp_path):
    project = create_project(tmp_path, "csv")
    path = tmp_path / "wages.csv"
    pd.DataFrame({"wage": [float(i) / 3 for i in range(6000)], "region": ["east", "west", None] * 2000}).to_csv(
        path, index=False)
    response = _preview(project.root, "wages.csv", path.read_bytes())
    assert response.status_code == 200, response.text
    body = response.json()
    imported, _ = read_frame_bounded(path, max_rows=5000)
    assert body["columns"] == ["wage", "region"] and body["total_rows"] == 6000
    assert body["rows"] == _records(imported)
    assert body["sheet_names"] == []


def _workbook(path, sheets: dict[str, pd.DataFrame]) -> bytes:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return path.read_bytes()


def test_an_excel_preview_names_its_sheets_and_reads_the_chosen_one_as_the_import_does(tmp_path):
    project = create_project(tmp_path, "xlsx")
    path = tmp_path / "book.xlsx"
    payload = _workbook(path, {
        "first": pd.DataFrame({"a": [1, 2]}),
        "second": pd.DataFrame({"year": [2001, 2002], "when": pd.to_datetime(["2020-01-01", "2020-02-01"])}),
    })
    response = _preview(project.root, "book.xlsx", payload, sheet_name="second")
    assert response.status_code == 200, response.text
    body = response.json()
    imported, _ = read_frame_bounded(path, max_rows=5000, sheet_name="second")
    assert body["sheet_names"] == ["first", "second"] and body["selected_sheet"] == "second"
    assert body["rows"] == _records(imported) and body["total_rows"] == 2


def test_a_transposed_preview_matches_the_transposed_import(tmp_path):
    project = create_project(tmp_path, "transpose")
    path = tmp_path / "wide.csv"
    path.write_text("variable,obs1,obs2,obs3\nwage,10,12,9\neduc,12,16,11\n")
    response = _preview(project.root, "wide.csv", path.read_bytes(), transpose="true")
    assert response.status_code == 200, response.text
    imported = _read_frame(path, WorkbenchConfig(), transpose=True)
    body = response.json()
    assert body["columns"] == [str(column) for column in imported.columns]
    assert body["rows"] == _records(imported) and body["total_rows"] == len(imported)


def _bomb(path) -> bytes:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/worksheets/sheet1.xml", b"<" + b" " * (64 * 1024 * 1024) + b"/>")
    return path.read_bytes()


def test_a_decompression_bomb_is_refused_before_parsing_by_preview_and_import(tmp_path):
    project = create_project(tmp_path, "bomb")
    path = tmp_path / "bomb.xlsx"
    response = _preview(project.root, "bomb.xlsx", _bomb(path))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UPLOAD_PREVIEW_UNREADABLE"
    assert "compression" in response.json()["error"]["message"]
    with pytest.raises(ValueError, match="compression"):
        read_frame_bounded(path, max_rows=10)


def test_a_preview_that_outlives_its_time_is_stopped(tmp_path, monkeypatch):
    from workbench import upload_preview

    monkeypatch.setattr(upload_preview, "PREVIEW_TIMEOUT_S", 0.001)
    project = create_project(tmp_path, "slow")
    response = _preview(project.root, "d.csv", b"a,b\n1,2\n")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UPLOAD_PREVIEW_TIMEOUT"


def test_an_unsupported_file_is_still_refused(tmp_path):
    project = create_project(tmp_path, "unsupported")
    response = _preview(project.root, "d.txt", b"a b\n")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UPLOAD_PREVIEW_UNSUPPORTED"
