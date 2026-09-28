"""R ``foreign`` as an independent reader of SPSS files.

Workbench reads and writes ``.sav`` through ReadStat (pyreadstat); so does R's
``haven``, so agreeing with haven proves little. ``foreign::read.spss`` is a
separate parser with its own C code, so it is the reference here: for any
``.sav`` it reports, per variable, the non-missing count, mean and standard
deviation after SPSS user-missing values are applied, plus the variable label
and the value labels.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RSCRIPT = shutil.which("Rscript")


def _foreign_available() -> bool:
    if RSCRIPT is None:
        return False
    probe = subprocess.run(
        [RSCRIPT, "-e", "cat(requireNamespace('foreign', quietly=TRUE))"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() == "TRUE"


requires_foreign = pytest.mark.skipif(not _foreign_available(), reason="R package foreign is not installed")

_SCRIPT = r"""
suppressWarnings(suppressMessages(library(foreign)))
args <- commandArgs(trailingOnly = TRUE)
d <- suppressWarnings(read.spss(args[1], to.data.frame = FALSE, use.value.labels = FALSE,
                                use.missings = TRUE, reencode = "UTF-8"))
labels <- attr(d, "variable.labels")
out <- list()
for (name in names(d)) {
  x <- d[[name]]
  entry <- list(label = if (!is.null(labels[[name]])) unname(labels[[name]]) else "")
  if (is.numeric(x)) {
    v <- x[!is.na(x)]
    entry$n <- length(v)
    entry$mean <- if (length(v)) mean(v) else NULL
    entry$sd <- if (length(v) > 1) sd(v) else NULL
  } else {
    entry$n <- sum(!is.na(x) & trimws(x) != "")
  }
  vl <- attr(x, "value.labels")
  if (!is.null(vl)) entry$value_labels <- setNames(as.list(names(vl)), trimws(as.character(unname(vl))))
  out[[name]] <- entry
}
cat(jsonlite::toJSON(out, auto_unbox = TRUE, digits = NA, null = "null"))
"""


def describe(path: Path, workdir: Path) -> dict:
    """foreign's per-variable description of ``path``."""

    script = workdir / "describe_sav.R"
    script.write_text(_SCRIPT, encoding="utf-8")
    completed = subprocess.run(
        [RSCRIPT or "Rscript", str(script), str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"R foreign failed on {path.name}: {completed.stderr[-2000:]}")
    return json.loads(completed.stdout)
