"""Explicitly build the finite native64 average-rank extension; no installation.

    .venv/bin/python native/spearman_ranks/build.py

The fixed product loader reads local/native-spearman-ranks. Build outputs may
also be placed under local/ or temporary directories for isolated tests.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import sysconfig
import tempfile


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    source=Path(__file__).resolve().with_name('spearman_rank.cpp')
    root=source.parents[2]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=root/'local/native-spearman-ranks')
    out=parser.parse_args().output_dir.resolve()
    allowed=((root/'local').resolve(),Path(tempfile.gettempdir()).resolve(),Path('/tmp').resolve())
    if not any(out==path or path in out.parents for path in allowed):
        parser.error('build output must be under local/ or a temporary directory')
    linker=sysconfig.get_config_var('LDCXXSHARED')
    if not linker:parser.error('current interpreter does not supply LDCXXSHARED')
    out.mkdir(parents=True,exist_ok=True)
    output=out/('_spearman_rank'+sysconfig.get_config_var('EXT_SUFFIX'))
    command=shlex.split(linker)+['-std=c++17','-O3','-Wall','-Wextra','-Werror','-fPIC',
        '-I'+sysconfig.get_path('include'),str(source),'-o',str(output)]
    source_sha=digest(source)
    print(shlex.join(command),flush=True)
    subprocess.run(command,check=True)
    if digest(source)!=source_sha:raise RuntimeError('Spearman source changed during build')
    result={'schema_version':1,'source':str(source),'source_sha256':source_sha,
        'binary':str(output),'binary_sha256':digest(output),'abi_version':1,
        'command':command,'executable':sys.executable,'python':sys.version,'fast_math':False}
    (out/'build-manifest.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
