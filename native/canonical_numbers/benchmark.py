"""One component A/B worker, called in fresh processes by the evidence runner.

Inputs are prepared and hashed before workers start. Both branches include
input I/O/hash/JSON parsing, full output allocation, UTF-8 conversion and SHA256.
This is component evidence; use frozen default product trees for Agent/OLS E2E.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
import threading
from time import perf_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--engine", required=True, choices=("reference", "native"))
    args = parser.parse_args()
    started = perf_counter()
    # Import/binary loading belongs to worker overhead, outside the encoding
    # phase but inside this total. The parent records process wall time too.
    from workbench import canonical, native_canonical
    imported = perf_counter()
    source = args.input.read_bytes()
    input_sha256 = hashlib.sha256(source).hexdigest()
    if input_sha256 != args.sha256:
        raise ValueError("fixed input SHA256 mismatch")
    values = json.loads(source)
    if type(values) not in (list, tuple) or not canonical._numeric_list(values):
        raise ValueError("component fixture must contain one exact numeric sequence")
    loaded = perf_counter()
    if args.engine == "native":
        engine = native_canonical.backend_info()
        if engine["engine"] != "native":
            raise RuntimeError("native component requires a built kernel")
        text = native_canonical.encode_numbers(values)
    else:
        # Component reference: the original flat-sequence encoder including
        # numeric validation, bracket/join and its O(n) temporary list.
        import math
        if not all(map(math.isfinite, values)):
            raise canonical.CanonicalJSONError("canonical JSON does not allow NaN or Infinity")
        text = "[" + ",".join(canonical._encode_numbers(values)) + "]"
        engine = {"engine": "reference", "reason": "explicit_component_reference"}
    encoded = perf_counter()
    output = text.encode("utf-8")
    output_sha256 = hashlib.sha256(output).hexdigest()
    finished = perf_counter()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({
        "scope": "canonical_numeric_component_including_io_copy_ffi_and_hash",
        "default_product_path": False, "engine": engine,
        "input_sha256": input_sha256, "input_bytes": len(source), "items": len(values),
        "output_sha256": output_sha256, "output_bytes": len(output),
        "seconds": finished - started, "import_seconds": imported - started,
        "input_seconds": loaded - imported, "encoding_seconds": encoded - loaded,
        "utf8_hash_seconds": finished - encoded,
        "rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "python_threads": threading.active_count(),
        "kernel_threads": 1, "gil": "held; no signal polling inside numeric loop",
        "memory_contract": "O(distinct) dict/text cache + final Unicode + UTF8 bytes; reference also O(n) text-list",
    }, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
