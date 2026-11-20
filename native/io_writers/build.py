"""Build or verify the native CSV, Stata and JSON writers offline with the shared build registry."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from workbench.native_build import main

if __name__ == "__main__":
    raise SystemExit(main(__file__))
