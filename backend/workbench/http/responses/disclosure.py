"""Analysis-path disclosure for reports."""

from __future__ import annotations

from typing import Literal

from typing_extensions import TypedDict


class DisclosureSettings(TypedDict):
    include_in_exports: bool
    detail: Literal["full", "summary"]


class DisclosureCounts(TypedDict):
    inferential_tests: int
    descriptive_analyses: int
    models: int
    data_changes: int
    metadata_changes: int
    run_deletions: int
    failed_actions: int


class DisclosureLine(TypedDict):
    at: str | None
    who: str
    status: str | None
    what: str
    categories: list[str]
    run_id: str | None
    produced_run_id: str | None
    summary: str


class AnalysisDisclosure(TypedDict):
    run_id: str
    source_upload_sha256: str | None
    first_at: str | None
    last_at: str | None
    counts: DisclosureCounts
    inferential_tests_by: dict[str, int]
    changes: list[DisclosureLine]
    entries: list[DisclosureLine]
    entries_omitted: int
    settings: DisclosureSettings
    markdown: str
