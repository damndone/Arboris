from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_lmm_result_adapter import (
    _complete_payload,
    _envelope,
    _write_indexed_packet,
)
from workbench.domain import ArtifactRecord
from workbench.services.lmm_result_adapter import (
    VersionedResultReadError,
    read_lmm_public_results,
)
from workbench.services.results_service import read_model_results


_LMM_RESULT_PATH = "artifacts/model_results/linear_mixed_effects_1.result.json"


def _write_legacy_result(run_root: Path, name: str, result: dict[str, object]) -> None:
    model_dir = run_root / "model_results"
    model_dir.mkdir(exist_ok=True)
    (model_dir / name).write_text(json.dumps(result), encoding="utf-8")


def _legacy_result(model_id: str) -> dict[str, object]:
    return {
        "model_id": model_id,
        "coefficients": {"x": {"estimate": 1.0}},
    }


def _write_index(run_root: Path, artifacts: list[dict[str, object]]) -> None:
    (run_root / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": artifacts}),
        encoding="utf-8",
    )


def test_read_model_results_keeps_ols_only_runs_unchanged_without_index(
    tmp_path: Path,
) -> None:
    z_result = _legacy_result("ols_z")
    a_result = _legacy_result("ols_a")
    _write_legacy_result(tmp_path, "z.json", z_result)
    _write_legacy_result(tmp_path, "a.json", a_result)
    _write_legacy_result(tmp_path, "ignored.json", {"not_coefficients": {}})

    assert read_model_results(tmp_path) == [a_result, z_result]


def test_read_model_results_appends_verified_lmm_projection_after_legacy_results(
    tmp_path: Path,
) -> None:
    legacy = _legacy_result("ols_1")
    _write_legacy_result(tmp_path, "ols_1.json", legacy)
    envelope = _envelope(_complete_payload())
    _write_indexed_packet(tmp_path, envelope)

    expected_lmm = read_lmm_public_results(tmp_path)

    assert read_model_results(tmp_path) == [legacy, *expected_lmm]


def test_read_model_results_raises_for_invalid_declared_packet_before_returning_legacy(
    tmp_path: Path,
) -> None:
    _write_legacy_result(tmp_path, "ols_1.json", _legacy_result("ols_1"))
    invalid_envelope = _envelope(_complete_payload())
    invalid_envelope["contract"] = "unknown.result"
    _write_indexed_packet(tmp_path, invalid_envelope)

    with pytest.raises(VersionedResultReadError) as raised:
        read_model_results(tmp_path)

    assert raised.value.code == "UNKNOWN_MODEL_RESULT_PACKET_CONTRACT"
    assert raised.value.artifact_path == _LMM_RESULT_PATH


def test_read_model_results_rejects_multiple_indexed_lmm_packets_atomically(
    tmp_path: Path,
) -> None:
    snapshot = _write_indexed_packet(tmp_path, _envelope(_complete_payload()))
    index = json.loads((tmp_path / "artifacts_index.json").read_text(encoding="utf-8"))
    index["artifacts"].append(
        ArtifactRecord(
            artifact_id="lmm-result-second",
            path=_LMM_RESULT_PATH,
            artifact_type="model_result_packet",
            step="linear_mixed_effects",
            sha256=hashlib.sha256(snapshot).hexdigest(),
            inputs=("clean-data",),
            config_hash="config-v1",
            code_version="1.7.3",
        ).to_dict()
    )
    _write_index(tmp_path, index["artifacts"])

    with pytest.raises(VersionedResultReadError) as raised:
        read_model_results(tmp_path)

    assert raised.value.code == "LMM_DUPLICATE_IDENTITY"
    assert raised.value.artifact_path == _LMM_RESULT_PATH


def test_read_model_results_ignores_non_model_index_records_and_unrelated_json(
    tmp_path: Path,
) -> None:
    legacy = _legacy_result("ols_1")
    _write_legacy_result(tmp_path, "ols_1.json", legacy)
    _write_legacy_result(tmp_path, "unrelated.json", {"metadata": "ignore me"})
    _write_index(
        tmp_path,
        [
            ArtifactRecord(
                artifact_id="metadata",
                path="metadata/run.json",
                artifact_type="run_metadata",
                step="metadata",
                sha256="a" * 64,
                inputs=(),
                config_hash="",
                code_version="1.7.3",
            ).to_dict()
        ],
    )

    assert read_model_results(tmp_path) == [legacy]


def test_read_model_results_keeps_v1_unversioned_non_model_index_compatible(
    tmp_path: Path,
) -> None:
    legacy = _legacy_result("ols_1")
    _write_legacy_result(tmp_path, "ols_1.json", legacy)
    _write_index(
        tmp_path,
        [
            {
                "artifact_id": "report_html",
                "path": "reports/report.html",
                "artifact_type": "report",
                "step": "reporting",
                "sha256": "deadbeef",
            }
        ],
    )
    index_path = tmp_path / "artifacts_index.json"
    index_path.write_text(
        json.dumps({"artifacts": json.loads(index_path.read_text(encoding="utf-8"))["artifacts"]}),
        encoding="utf-8",
    )

    assert read_model_results(tmp_path) == [legacy]


def test_read_model_results_rejects_unversioned_declared_model_packet_atomically(
    tmp_path: Path,
) -> None:
    _write_legacy_result(tmp_path, "ols_1.json", _legacy_result("ols_1"))
    _write_index(
        tmp_path,
        [
            {
                "artifact_id": "lmm-result",
                "artifact_type": "model_result_packet",
            }
        ],
    )
    index_path = tmp_path / "artifacts_index.json"
    index_path.write_text(
        json.dumps({"artifacts": json.loads(index_path.read_text(encoding="utf-8"))["artifacts"]}),
        encoding="utf-8",
    )

    with pytest.raises(VersionedResultReadError) as raised:
        read_model_results(tmp_path)

    assert raised.value.code == "ARTIFACT_INDEX_INVALID"
    assert raised.value.artifact_path is None


def test_cold_import_of_api_has_no_results_reader_cycle() -> None:
    workspace = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(workspace / "backend"), str(workspace), environment.get("PYTHONPATH", "")]
    )

    completed = subprocess.run(
        [sys.executable, "-c", "import workbench.api; print('cold-import-ok')"],
        cwd=workspace,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "cold-import-ok"


def _write_run_manifest(run_root: Path) -> None:
    run_root.mkdir(parents=True)
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_root.name,
                "mode": "auto",
                "status": "completed",
                "lineage": [],
            }
        ),
        encoding="utf-8",
    )


def test_run_detail_returns_valid_generic_response_without_versioned_packet(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient
    from workbench.api import app

    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "valid-run"
    _write_run_manifest(run_root)
    _write_index(run_root, [])

    response = TestClient(app, raise_server_exceptions=False).get(
        "/runs/valid-run", params={"project_root": str(project_root)}
    )

    assert response.status_code == 200
    assert response.json()["run_id"] == "valid-run"
    assert response.json()["model_results"] == []


def test_run_detail_maps_invalid_declared_packet_to_controlled_422(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient
    from workbench.api import app

    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "invalid-packet-run"
    _write_run_manifest(run_root)
    envelope = _envelope(_complete_payload())
    envelope["contract"] = "untrusted.packet"
    _write_indexed_packet(run_root, envelope)

    response = TestClient(app, raise_server_exceptions=False).get(
        "/runs/invalid-packet-run", params={"project_root": str(project_root)}
    )

    assert response.status_code == 422
    body = response.json()
    assert body == {
        "error": {
            "code": "UNKNOWN_MODEL_RESULT_PACKET_CONTRACT",
            "message": "The versioned model result cannot be read.",
            "details": {"artifact_path": _LMM_RESULT_PATH},
        }
    }
    assert "Traceback" not in response.text
    assert "untrusted.packet" not in response.text


def test_run_detail_rejects_a_dangling_artifact_index_symlink(
    tmp_path: Path,
) -> None:
    """A lexical index entry is never silently treated as legacy absence."""
    from fastapi.testclient import TestClient
    from workbench.api import app

    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "dangling-index-run"
    _write_run_manifest(run_root)
    (run_root / "artifacts_index.json").symlink_to("missing-index.json")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/runs/dangling-index-run", params={"project_root": str(project_root)}
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "ARTIFACT_INDEX_INVALID",
            "message": "The versioned model result cannot be read.",
            "details": {},
        }
    }
