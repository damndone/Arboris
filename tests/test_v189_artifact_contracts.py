from __future__ import annotations

from workbench.artifacts import sha256_file
from workbench.repository.run_repository import _validate_artifact_record


def _record(run_root, artifact_type: str) -> dict[str, object]:
    path = run_root / "measurement" / "design_precheck.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"contract":"workbench.design_precheck.v1"}\n', encoding="utf-8")
    return {
        "artifact_id": "design_precheck",
        "path": "measurement/design_precheck.json",
        "artifact_type": artifact_type,
        "step": "estimation",
        "sha256": sha256_file(path),
        "inputs": ["cleaned_dataset"],
        "config_hash": "",
        "code_version": "0.1.0",
    }


def test_design_precheck_is_accepted_by_the_canonical_artifact_reader(tmp_path):
    record = _record(tmp_path, "design_precheck")

    validated = _validate_artifact_record(tmp_path, record)

    assert validated["artifact_type"] == "design_precheck"


def test_unknown_artifact_types_remain_rejected(tmp_path):
    record = _record(tmp_path, "unknown_future_artifact")

    try:
        _validate_artifact_record(tmp_path, record)
    except ValueError as exc:
        assert "canonical vocabulary" in str(exc)
    else:
        raise AssertionError("unknown artifact type was admitted")
