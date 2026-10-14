"""Manual report snapshots keep user prose separate from computed evidence."""
from typing import Literal
from typing_extensions import TypedDict


class ManualFactSource(TypedDict):
    run_id: str
    node_key: str
    result_ref: str
    artifact_ids: list[str]


class ManualReportFact(TypedDict):
    id: str
    field: str
    label: str
    value: str | int | float | bool | None
    source: ManualFactSource


class ManualReportFigure(TypedDict):
    artifact_id: str
    chart_type: str
    sha256: str


class ManualReportDraft(TypedDict):
    schema_version: Literal["workbench-manual-report-draft/v1"]
    run_id: str
    source_fingerprint: str
    draft_origin: Literal["deterministic"]
    title: str
    text: str
    facts: list[ManualReportFact]
    figures: list[ManualReportFigure]
    limitations: list[str]


class ManualReportRecord(TypedDict):
    id: str
    run_id: str
    author: Literal["user"]
    draft_origin: Literal["deterministic"]
    created_at: str
    document_id: str
    revision_number: int
    parent_report_id: str | None
    title: str
    text: str
    source_fingerprint: str
    facts: list[ManualReportFact]
    figures: list[ManualReportFigure]
    limitations: list[str]


class ManualReportSaved(TypedDict):
    schema_version: Literal["workbench-manual-report/v1"]
    record: ManualReportRecord


class ManualReportHistory(TypedDict):
    reports: list[ManualReportRecord]
