"""Observe real default background OLS cancellation without a provider or patches."""
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "scripts")]
from perf_evidence import digest, finalize_active, require_space
from workbench.jsonl_store import jsonl_lines
from workbench.events import get_event_manager
from workbench.projects import create_project
from workbench.services.run_service import _submit_run


def main():
    require_space(ROOT)
    area = ROOT / "local/perf-evidence/ols-cancel"
    area.mkdir(parents=True, exist_ok=True)
    active = area / "active"
    active.mkdir(exist_ok=False)
    source_info = json.loads((ROOT / "local/perf-inputs/ols/source.json").read_text())
    source = Path(source_info["source"])
    assert digest(source) == source_info["sha256"]
    project = create_project(active, "benchmark")
    events = get_event_manager()
    assert events.try_acquire_slot()
    started = time.perf_counter()
    result = _submit_run(project.root, form={"mode": "auto", "model_type": "ols", "y": "wage",
        "x": "education,experience,female,hours"}, upload_bytes=source.read_bytes(),
        upload_filename=source.name, started_at="offline-cancel-observation")
    run_id = result["run_id"]
    run = project.root / "runs" / run_id
    requested = None
    deadline = started + 180
    while time.perf_counter() < deadline:
        history = [json.loads(line) for line in jsonl_lines((run / "workflow_log.jsonl").read_text())]
        if requested is None and any(e.get("step") == "estimation" and e.get("event") == "step_start" for e in history):
            requested = time.perf_counter()
            assert events.request_cancel(run_id)
        manifest = json.loads((run / "run_manifest.json").read_text())
        if manifest["status"] not in {"running", "pending"} and not events.is_active(run_id):
            break
        time.sleep(.005)
    else:
        raise TimeoutError("cancellation observation did not settle; retain active evidence")
    settled = time.perf_counter()
    metadata = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "status": manifest["status"], "run_root": str(run), "elapsed_s": settled - started,
        "cancel_requested": requested is not None,
        "cancel_to_terminal_s": settled - requested if requested is not None else None,
        "cancel_budget_s": 2, "ru_maxrss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "input_source": str(source), "input_sha256": source_info["sha256"]}
    (area / "results.json").write_text(json.dumps({"metadata": metadata, "history": history}, indent=2))
    retained = finalize_active(active, ledger=area / "runs.jsonl", record_id="ols-default-cancel",
        metadata=metadata, archive_dir=ROOT / "local/perf-evidence/representatives", version="v1.9.1", case="ols")
    print(json.dumps({"metadata": metadata, "retention": retained}, indent=2))


if __name__ == "__main__":
    main()
