from pathlib import Path

import pytest

from workbench.identity.root import (
    InvalidProjectRootError,
    ValidatedProjectRoot,
    validate_project_root,
)


def test_validate_project_root_resolves_aliases_to_one_filesystem_binding(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    alias = tmp_path / "project-alias"
    alias.symlink_to(project, target_is_directory=True)

    direct = validate_project_root(project)
    through_alias = validate_project_root(alias)

    assert isinstance(direct, ValidatedProjectRoot)
    assert direct.canonical_path == str(project)
    assert through_alias.canonical_path == direct.canonical_path
    assert through_alias.binding_key == direct.binding_key
    assert direct.to_binding_dict() == {
        "binding_key": direct.binding_key,
        "canonical_path": str(project),
        "device": direct.device,
        "inode": direct.inode,
    }


@pytest.mark.parametrize("bad_root", ["relative/project", "", None])
def test_validate_project_root_rejects_non_absolute_inputs(
    bad_root: object,
) -> None:
    with pytest.raises(InvalidProjectRootError):
        validate_project_root(bad_root)  # type: ignore[arg-type]


def test_validate_project_root_rejects_missing_paths_and_files(tmp_path: Path) -> None:
    with pytest.raises(InvalidProjectRootError):
        validate_project_root(tmp_path / "missing")

    file_path = tmp_path / "not-a-directory"
    file_path.write_text("not a project", encoding="utf-8")
    with pytest.raises(InvalidProjectRootError):
        validate_project_root(file_path)


def test_validate_project_root_reports_unsupported_host_without_fcntl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.identity.root as module

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(module, "fcntl", None)

    with pytest.raises(InvalidProjectRootError, match="unsupported"):
        module.validate_project_root(project)


def test_renaming_a_directory_preserves_binding_key_but_changes_observed_path(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    before = validate_project_root(original)

    moved = tmp_path / "moved"
    original.rename(moved)
    after = validate_project_root(moved)

    assert after.binding_key == before.binding_key
    assert after.canonical_path == str(moved)
    assert after.canonical_path != before.canonical_path


def test_root_replacement_during_fd_admission_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.identity.root as module

    project = tmp_path / "project"
    project.mkdir()
    replacement = tmp_path / "replacement"
    original_open = module._open_canonical_directory
    calls = 0

    def replace_after_open(path: Path) -> int:
        nonlocal calls
        fd = original_open(path)
        calls += 1
        if calls == 1:
            project.rename(replacement)
            project.mkdir()
        return fd

    monkeypatch.setattr(module, "_open_canonical_directory", replace_after_open)
    with pytest.raises(InvalidProjectRootError):
        validate_project_root(project)
