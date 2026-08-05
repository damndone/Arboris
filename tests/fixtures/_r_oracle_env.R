# Shared preflight for the committed R oracle generators.
#
# Source this at the top of any generate_oracle.R:
#   source("tests/fixtures/_r_oracle_env.R"); require_oracle_packages("survey", "jsonlite")
#
# Deliberately fails loudly.  A generator that quietly skipped when a package was
# absent would look identical to one that ran and matched, which is the exact
# failure mode this release exists to remove.

require_oracle_packages <- function(...) {
  pkgs <- c(...)
  missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing)) {
    stop(sprintf(
      paste0(
        "Missing R oracle package(s): %s\n",
        "R packages are machine-level, not per-worktree, so install once:\n",
        "  Rscript tests/fixtures/install-r-oracle-requirements.R\n",
        "Declared set: tests/fixtures/r-oracle-requirements.txt\n",
        "Refusing to continue: a skipped oracle proves nothing but reads as a pass."
      ),
      paste(missing, collapse = ", ")
    ), call. = FALSE)
  }
  invisible(
    vapply(pkgs, function(p) as.character(utils::packageVersion(p)), character(1))
  )
}

# Record the exact library and versions used, so a fixture can be traced back to
# the environment that produced it rather than to "whatever was installed then".
oracle_environment <- function(pkgs) {
  list(
    r_version = paste(R.version$major, R.version$minor, sep = "."),
    platform = R.version$platform,
    lib_paths = .libPaths(),
    packages = as.list(vapply(
      pkgs, function(p) as.character(utils::packageVersion(p)), character(1)
    ))
  )
}
