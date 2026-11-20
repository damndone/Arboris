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
    title: str | None
    categories: list[str]
    run_id: str | None
    produced_run_id: str | None
    summary: str


class ResearchSpecificationLine(TypedDict):
    record_id: str | None
    run_id: str | None
    step_id: str
    operation_id: str
    question_id: str | None
    specification_status: Literal["pre_specified", "exploratory"]
    verification: str
    reason: str
    status: str | None
    at: str | None
    specification_event_id: str | None


class ResearchSpecificationSections(TypedDict):
    pre_specified: list[ResearchSpecificationLine]
    exploratory: list[ResearchSpecificationLine]


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
    research_specifications: ResearchSpecificationSections
