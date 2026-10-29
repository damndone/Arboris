"""Journal/archive/verify only the 15 original Agent A/B product trees.

Never edits original timing JSONL, report or source manifest, and never touches
frozen inputs/source snapshots. This correction cannot retrospectively supply
host-idle evidence or make the original retention protocol compliant.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import perf_evidence as evidence


def migrate(out: Path):
    out = out.resolve()
    ledger = out / "retention-migration.jsonl"
    correction = out / "protocol-correction.json"
    if ledger.exists() or correction.exists():
        raise FileExistsError("migration evidence already exists; inspect before resuming")
    raw_path, report_path, manifest_path = (out / name for name in ("runs.jsonl", "report.json", "source-manifest.json"))
    original_sha256 = {path.name:evidence.digest(path) for path in (raw_path, report_path, manifest_path)}
    rows = [json.loads(line) for line in raw_path.read_text().splitlines() if line.strip()]
    report = json.loads(report_path.read_text())
    source_manifest = json.loads(manifest_path.read_text())
    if len(rows) != 15 or report["manifest_sha256"] != original_sha256["source-manifest.json"]:
        raise ValueError("expected exactly the original 15 measured observations")
    roots = []
    for ordinal, row in enumerate(rows):
        role = row["engine_role"]
        if role not in {"baseline", "candidate"}:
            raise ValueError("unknown benchmark source role")
        root = Path(row["work_dir"])
        if (root.is_symlink() or root.resolve().parent != out or
                root.name != f"{ordinal:02d}-{role}" or not re.fullmatch(r"\d\d-(baseline|candidate)", root.name)):
            raise ValueError("refusing a directory outside the exact original benchmark products")
        if not root.is_dir() or row["manifest_sha256"] != source_manifest["fixture_manifest_sha256"]:
            raise ValueError("original benchmark product or manifest identity changed")
        roots.append(root)
    records, archives = [], {}
    for row, root in zip(rows, roots):
        record = evidence.snapshot(root, record_id=root.name,
            metadata={"original_measurement":row, "source_raw_sha256":original_sha256["runs.jsonl"],
                      "protocol_correction":"retention inventory recorded after original measurement"},
            kind="offline_pipeline_run")
        evidence.append_record(ledger, record)
        saved = [r for r in evidence.read_records(ledger) if r["record_id"] == root.name]
        evidence.verify_tree_records(root, saved)
        role = row["engine_role"]
        if role not in archives:
            archive = out / "representatives" / (role + "-agent-local-pipeline.tar.gz")
            archives[role] = evidence.archive_verified(root, archive, record["files"]) | {"record_id":root.name}
        records.append(record)
    result = {"schema_version":1, "observed_at":datetime.now(timezone.utc).isoformat(),
        "original_evidence_sha256":original_sha256, "observations":15,
        "original_numeric_thresholds_passed":report["accepted_local_replay"],
        "original_full_protocol_accepted":False,
        "original_protocol_deviations":["kept all 15 product directories concurrently", "no host ps snapshots before/after observations",
            "raw row manifest_sha256 names the fixture hash after worker merge; original source manifest pin remains in report and source-manifest.json"],
        "measurement_exclusion_or_recalculation":False, "measurements_repeated":False,
        "migration_ledger":"retention-migration.jsonl", "representatives":archives,
        "migration_state":"verified_ready_for_product_removal", "removed_product_directories":[]}
    correction.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    # Verify the durable journal, original measurements and representatives
    # again before any removal. All roots were allowlisted from original rows.
    saved = evidence.read_records(ledger)
    if len(saved) != 15:
        raise ValueError("retention journal does not cover all original observations")
    for name, checksum in original_sha256.items():
        if evidence.digest(out / name) != checksum:
            raise ValueError("original measurement changed during migration")
    for archive in archives.values():
        if evidence.digest(archive["path"]) != archive["sha256"]:
            raise ValueError("verified representative changed")
    for root in roots:
        evidence.verify_tree_records(root,[r for r in saved if r["record_id"] == root.name])
    for root in roots:
        evidence.verify_tree_records(root,[r for r in saved if r["record_id"] == root.name])
        shutil.rmtree(root)
        result["removed_product_directories"].append(root.name)
    result["migration_state"] = "completed"
    result["original_evidence_unchanged"] = all(evidence.digest(out / name)==checksum for name,checksum in original_sha256.items())
    result["retained_product_directories"] = sum(root.exists() for root in roots)
    correction.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(migrate(args.out),sort_keys=True))


if __name__ == "__main__":
    main()
