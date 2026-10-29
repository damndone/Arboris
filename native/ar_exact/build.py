"""Build the exact AR kernel using the current interpreter and existing C++17 toolchain.

    .venv/bin/python native/ar_exact/build.py

No dependency installation or network access. The ABI-specific output defaults
to local/native-ar; the product bridge checks ABI and the embedded source digest.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shlex
import subprocess
import sysconfig
import tempfile


def main():
    source = Path(__file__).resolve().with_name('ar_exact.cpp')
    root = source.parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=root / 'local/native-ar')
    parser.add_argument('--engine', choices=('row-exact', 'moments'), default='row-exact')
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    module, digest_macro = '_ar_exact', 'AR_EXACT_SOURCE_SHA256'
    if args.engine == 'moments':
        source = source.with_name('ar_moments.cpp')
        module, digest_macro = '_ar_moments_exact', 'AR_MOMENTS_SOURCE_SHA256'
    allowed = ((root / 'local').resolve(), Path(tempfile.gettempdir()).resolve(), Path('/tmp').resolve())
    if not any(output_dir == path or path in output_dir.parents for path in allowed):
        parser.error('build output must be under local/ or a temporary directory')
    linker = sysconfig.get_config_var('LDCXXSHARED')
    if not linker:
        parser.error('this interpreter does not supply LDCXXSHARED')
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / (module + sysconfig.get_config_var('EXT_SUFFIX'))
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    command = shlex.split(linker) + [
        '-std=c++17', '-O3', '-Wall', '-Wextra', '-Werror', '-fPIC',
        '-D' + digest_macro + '="' + source_digest + '"',
        '-I' + sysconfig.get_path('include'), str(source), '-o', str(output),
    ]
    print(shlex.join(command), flush=True)
    subprocess.run(command, check=True)
    print(output)


if __name__ == '__main__':
    main()
