"""Gate 4 — persistence is append-only and crash-recoverable (spec §8, §3.6).

The point of these tests is the negative: no byte previously written is ever
changed. A revision counter that increments over overwritten content (§3.8) is
indistinguishable from this one at the API level and useless at the disk level,
so the assertions look at the file.
"""
from __future__ import annotations

import json
from pathlib import Path

from workbench.agent.notebook import NotebookService, OptionDraft, TypedProposal
from workbench.agent.notebook.vocabulary import DECLARED_ARTIFACT_TYPES
from workbench.contracts.agent.notebook_option import ExpectedArtifact

from tests.test_notebook_support import make_project, model_rerun_proposal

_REQUIRED = (
    ExpectedArtifact(
        artifact_id="ts.parameters", artifact_type="time_series_json", required=True, count=1
    ),
)


def _draft(proposal_id: str, covariance: str, option_id: str | None = None) -> OptionDraft:
    return OptionDraft(
        rank=1,
        rationale=covariance,
        proposal=TypedProposal.from_dict(
            model_rerun_proposal(proposal_id, covariance=covariance)
        ),
        expected_artifacts=_REQUIRED,
        option_id=option_id,
    )


def _option_log(project: Path, notebook_id: str, option_id: str) -> Path:
    return project / "notebooks" / notebook_id / "options" / f"{option_id}.jsonl"


def test_the_option_log_only_ever_grows(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    (option,) = service.propose_batch(
        notebook.notebook_id,
        context=service.compile_context(notebook.notebook_id),
        drafts=[_draft("p1", "robust")],
    )
    path = _option_log(project, notebook.notebook_id, option.option_id)
    prefix = path.read_bytes()

    service.record_decision(
        notebook.notebook_id, option.option_id, decision="deferred", actor="u"
    )
    service.set_focus(notebook.notebook_id, user_focus={"selected_text_hash": "sha256:zzz"})
    service.revalidate_option(
        notebook.notebook_id,
        option.option_id,
        context=service.compile_context(notebook.notebook_id),
        draft=_draft("p2", "clustered", option_id=option.option_id),
    )

    after = path.read_bytes()
    assert after.startswith(prefix)
    assert len(after) > len(prefix)

    records = [json.loads(line) for line in after.decode("utf-8").splitlines() if line.strip()]
    assert [r["record_type"] for r in records] == [
        "option",
        "revision",
        "lifecycle",
        "lifecycle",
        "revision",
    ]
    revisions = [r for r in records if r["record_type"] == "revision"]
    assert [r["option_revision"] for r in revisions] == [1, 2]
    # Revision 1 still names its own proposal, not revision 2's.
    assert revisions[0]["typed_proposal"]["proposal_id"] == "p1"
    assert revisions[0]["typed_proposal"]["changes"]["model_options"]["covariance"] == "robust"
    assert revisions[1]["typed_proposal"]["changes"]["model_options"]["covariance"] == (
        "clustered"
    )
    assert revisions[1]["revision"]["supersedes_option_revision"] == 1
    # Lifecycle survived the new revision: deferred + stale + valid is legal (§3.4).
    assert service.option_view(
        notebook.notebook_id, option.option_id
    ).lifecycle_status == "deferred"


def test_a_notebook_and_its_options_survive_a_process_restart(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    first = NotebookService(project)
    notebook = first.create_notebook(title="Restart", created_by="u")
    (option,) = first.propose_batch(
        notebook.notebook_id,
        context=first.compile_context(notebook.notebook_id),
        drafts=[_draft("p1", "robust")],
    )

    reopened = NotebookService(project)
    view = reopened.option_view(notebook.notebook_id, option.option_id)

    assert reopened.get_notebook(notebook.notebook_id).title == "Restart"
    assert view.current_revision.to_dict() == option.to_dict()
    assert view.current_stored_revision.proposal.proposal_id == "p1"
    assert view.lifecycle_status == "proposed"
    assert [n.notebook_id for n in reopened.list_notebooks()] == [notebook.notebook_id]


def test_the_published_vocabulary_matches_the_packs_required_artifacts() -> None:
    """§5.4 — the vocabulary is a promise about what the system really produces.

    Imports the pack's own list rather than restating it: if a pack adds or
    renames a logical artifact, this fails instead of letting the notebook layer
    quietly promise something that no longer exists.
    """
    from workbench.engine.packs.arma_garch.runner import _REQUIRED_LOGICAL_ARTIFACTS

    assert set(DECLARED_ARTIFACT_TYPES) == set(_REQUIRED_LOGICAL_ARTIFACTS)
    assert DECLARED_ARTIFACT_TYPES["ts.artifact_manifest"] == "time_series_manifest"
    assert DECLARED_ARTIFACT_TYPES["ts.parameters"] == "time_series_json"
