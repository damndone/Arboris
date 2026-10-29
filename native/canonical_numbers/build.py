"""Build the canonical-v1 CPython C++ kernel with the existing interpreter/toolchain.

    .venv/bin/python native/canonical_numbers/build.py
    NATIVE_CANONICAL_REQUIRED=1 PYTHONPATH=backend:local/native-canonical \\
      .venv/bin/python -m pytest tests/test_native_canonical.py -q

No package installation, download, or measurement. Product auto-detection uses
the default local/native-canonical output directory.
Output is restricted to local/ or the system temporary directory. The extension
is specific to this interpreter ABI/platform; rebuild after changing Python.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess
import sysconfig
import tempfile


def main() -> None:
    source = Path(__file__).resolve().with_name("canonical_numbers.cpp")
    root = source.parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=root / "local/native-canonical")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    allowed = ((root / "local").resolve(), Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve())
    if not any(output_dir == path or path in output_dir.parents for path in allowed):
        parser.error("build output must be under local/ or a temporary directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / ("_canonical_numbers" + sysconfig.get_config_var("EXT_SUFFIX"))
    linker = sysconfig.get_config_var("LDCXXSHARED")
    if not linker:
        parser.error("this interpreter does not supply LDCXXSHARED")
    command = shlex.split(linker) + [
        "-std=c++17", "-O3", "-Wall", "-Wextra", "-Werror", "-fPIC",
        "-I" + sysconfig.get_path("include"), str(source), "-o", str(output),
    ]
    print(shlex.join(command), flush=True)
    subprocess.run(command, check=True)
    print(output)


if __name__ == "__main__":
    main()
