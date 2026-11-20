"""Archive a saved OLS result with one copy of its analysis row IDs.

The archive is a separate file. The original result and artifact index are
left in place. Restore reproduces the original result bytes and checks its SHA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

FORMAT = "workbench.ols_result_archive.v1"


def _analysis_sample(result: dict) -> dict:
    if not isinstance(result, dict) or (
        result.get("model") != "ols" or result.get("contract_version") != "ols_result_contract_v1"
    ):
        raise ValueError("expected an OLS result contract v1")
    sample = result.get("analysis_sample")
    if not isinstance(sample, dict):
        raise ValueError("missing analysis sample")
    order = sample.get("row_order")
    if not isinstance(order, list) or any(type(row) is not str for row in order):
        raise ValueError("expected a list of string row_order IDs")
    return sample


def _legacy_bytes(result: dict) -> bytes:
    # Match the result writer, including key order, UTF-8 and indentation.
    return json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8")


def pack(source: bytes) -> bytes:
    result = json.loads(source)
    sample = _analysis_sample(result)
    if "row_set" not in sample:
        raise ValueError("this result already stores one copy of its row IDs (written by a v1.9.1 development build); "
                         "there is nothing to archive")
    if sample.get("row_set") != sorted(sample["row_order"]):
        raise ValueError("row_set must equal the sorted row_order, including duplicates")
    if _legacy_bytes(result) != source:
        raise ValueError("source bytes are not in the legacy result writer format")
    position = list(sample).index("row_set")
    del sample["row_set"]
    archive = {
        "format": FORMAT,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "source_bytes": len(source),
        "row_set_position": position,
        "result": result,
    }
    return json.dumps(archive, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def restore(source: bytes) -> bytes:
    archive = json.loads(source)
    if not isinstance(archive, dict) or archive.get("format") != FORMAT:
        raise ValueError("unsupported OLS archive format")
    result = archive.get("result")
    sample = _analysis_sample(result)
    position = archive.get("row_set_position")
    if "row_set" in sample or type(position) is not int or not 0 <= position <= len(sample):
        raise ValueError("invalid archived row_set position")
    fields = list(sample.items())
    fields.insert(position, ("row_set", sorted(sample["row_order"])))
    result["analysis_sample"] = dict(fields)
    raw = _legacy_bytes(result)
    if len(raw) != archive.get("source_bytes") or hashlib.sha256(raw).hexdigest() != archive.get("source_sha256"):
        raise ValueError("restored result does not match the original size and SHA-256")
    return raw


def _publish_new_file(path: Path, contents: bytes) -> None:
    # Link only after the file is complete and fsynced. An existing destination
    # fails atomically, even if two commands try to publish the same path.
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.") as staged:
        staged.write(contents)
        staged.flush()
        os.fsync(staged.fileno())
        os.link(staged.name, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("pack", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError(f"output already exists: {args.output}")
        source = args.source.read_bytes()
        result = pack(source) if args.operation == "pack" else restore(source)
        _publish_new_file(args.output, result)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({
        "operation": args.operation, "input_bytes": len(source),
        "output_bytes": len(result), "output_sha256": hashlib.sha256(result).hexdigest(),
    }))


if __name__ == "__main__":
    main()
