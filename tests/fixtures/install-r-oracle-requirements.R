# Install every R package declared in r-oracle-requirements.txt.
#
# Run once per machine (packages are machine-level, shared by all worktrees):
#   Rscript tests/fixtures/install-r-oracle-requirements.R
#
# Already-present packages are left alone, so this is safe to re-run.

manifest <- "tests/fixtures/r-oracle-requirements.txt"
if (!file.exists(manifest)) {
  stop("Run from the repository root: ", manifest, " not found", call. = FALSE)
}

lines <- readLines(manifest, warn = FALSE)
lines <- sub("#.*$", "", lines)          # strip trailing comments
lines <- trimws(lines)
pkgs <- unique(lines[nzchar(lines)])

present <- vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)
cat(sprintf("Declared: %d   present: %d   missing: %d\n",
            length(pkgs), sum(present), sum(!present)))

if (all(present)) {
  cat("Nothing to install.\n")
} else {
  missing <- pkgs[!present]
  cat("Installing:", paste(missing, collapse = ", "), "\n")
  install.packages(missing, repos = "https://cloud.r-project.org")
}

still <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
if (length(still)) {
  # Not every declared package is on CRAN (DIDmultiplegtDYN and friends have
  # their own sources), so report precisely instead of implying a clean install.
  cat("\nSTILL MISSING (install manually, see each generator's header):\n  ",
      paste(still, collapse = ", "), "\n")
  quit(status = 1)
}
cat("All declared oracle packages are available.\n")
