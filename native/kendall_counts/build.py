"""Build only the independent Kendall-counts CPython extension, without installs.

    .venv/bin/python native/kendall_counts/build.py
    NATIVE_KENDALL_REQUIRED=1 PYTHONPATH=local/native-kendall \\
      .venv/bin/python -m pytest tests/test_native_kendall_counts.py -q

Outputs stay in local/ or a temporary directory. Rebuild for another Python ABI.
This script neither connects a product path nor performs performance measurement.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess
import sysconfig
import tempfile


def main() -> None:
    source = Path(__file__).resolve().with_name('kendall_counts.cpp')
    root = source.parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=root / 'local/native-kendall')
    output_dir = parser.parse_args().output_dir.resolve()
    allowed = ((root / 'local').resolve(), Path(tempfile.gettempdir()).resolve(), Path('/tmp').resolve())
    if not any(output_dir == path or path in output_dir.parents for path in allowed):
        parser.error('build output must be under local/ or a temporary directory')
    linker = sysconfig.get_config_var('LDCXXSHARED')
    if not linker:
        parser.error('this interpreter does not supply LDCXXSHARED')
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / ('_kendall_counts' + sysconfig.get_config_var('EXT_SUFFIX'))
    command = shlex.split(linker) + [
        '-std=c++17', '-O3', '-Wall', '-Wextra', '-Werror', '-fPIC',
        '-I' + sysconfig.get_path('include'), str(source), '-o', str(output),
    ]
    print(shlex.join(command), flush=True)
    subprocess.run(command, check=True)
    print(output)


if __name__ == '__main__':
    main()
