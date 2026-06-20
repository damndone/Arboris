#!/usr/bin/env Rscript
# =============================================================================
# Workbench v1.5.8 — Sun-Abraham (fixest::sunab) JSON oracle generator
# Task 1 of the SA estimator-slot validation plan.
#
# RUN FROM WORKTREE ROOT:
#   Rscript tests/fixtures/sa_did/generate_oracle.R
#
# Requires: fixest (tested 0.14.1), jsonlite. The Python test suite NEVER calls
# R — it reads the committed JSON + CSV produced here.
#
# LOCKED 口径: ssc(adj = FALSE, cluster.adj = FALSE); cluster = ~ id.
# NOTE: fixest::sunab is NOT exported via `::`; it only works UNQUOTED inside a
# feols formula, e.g. feols(y ~ sunab(cohort, year) | id + year, d).
#
# -----------------------------------------------------------------------------
# AUTHORITATIVE PER-(g,e) ORACLE = fixest::sunab's OWN raw output:
#   coef(m, agg = FALSE)  and  vcov(m, agg = FALSE)
# We do NOT hand-build a separate saturated i() fit. A naive
# `i(cohort, rel_period, ref = -1)` does NOT reproduce sunab's per-(g,e) CATTs
# (different kept-cell set AND different values, verified empirically) because
# sunab uses a specific construction (documented below) and then relies on
# fixest's automatic collinearity removal. sunab raw IS the validation target
# (spec §5.1 CATT vs sunab ~1e-8; §5.2 IF reconstructs sunab bare-cluster vcov
# ~1e-6). The Python engine in Tasks 3/4 is built to mirror this construction.
#
# -----------------------------------------------------------------------------
# EXACT fixest::sunab CONSTRUCTION RULE (decoded from fixest:::sunab source,
# fixest 0.14.1). This determines WHICH (g,e) cells survive and is the spec
# Task 3 must mirror to reproduce the kept-cell set + 1e-6 vcov match:
#
#   (a) Relative period: rel_period = period - cohort, computed per row for
#       treated units. A "cohort" value that never appears as a "period" value
#       (here: never-treated, encoded NA in the CSV) is detected as a reference
#       cohort (cpp_find_never_always_treated -> info$ref); always-treated units
#       get NA interaction rows.
#   (b) Never-treated detection: cohort values not present in the period set are
#       the never-treated reference group. They contribute to the id/year FEs
#       (serve as the clean comparison) but get NO interaction columns.
#   (c) qui_drop = which( cohort %in% never-treated-ref  OR  rel_period %in% ref.p ).
#       Default ref.p = -1. So the e = -1 relative period AND the never-treated
#       cohort columns are dropped (their interaction entries set to 0).
#   (d) Factor order: res_raw = i(factor_var = period(=rel_period), f2 = cohort).
#       RELATIVE PERIOD is the PRIMARY factor, COHORT the SECONDARY. Coefficient
#       names are therefore  "year::<e>:cohort::<g>".
#   (e) Collinearity removal: after sunab builds the full rel_period × cohort
#       interaction design, feols() runs its OWN automatic collinearity check
#       against the two-way (id + year) fixed effects and drops collinear
#       columns ($collin.var). With a never-treated group plus multiple treated
#       cohorts, MANY cohort×rel-period interactions are collinear with the
#       cohort-implied id FE structure and the year FE, so the surviving
#       per-(g,e) cell set is SPARSE and is NOT simply "all treated (g,e) with
#       e != -1". The kept set is whatever feols retains after this drop. The
#       Python engine must reproduce the same construction (a)-(d) and the same
#       collinearity-drop outcome (e) to match cell-for-cell.
#
# Parser for the raw names:  "year::(-?\\d+):cohort::(-?\\d+)"  ->  e = \1, g = \2.
#
# -----------------------------------------------------------------------------
# NEVER-TREATED CSV ENCODING: cohort = NA (empty cell). pandas reads it as NaN,
# which normalize_did_input treats as non-finite = never-treated. We DO NOT use
# a 10000 sentinel.
# =============================================================================

suppressMessages({
  library(fixest)
  library(jsonlite)
})

LOCKED_SSC <- ssc(adj = FALSE, cluster.adj = FALSE)

# Output directory = this script's own directory.
out_dir <- tryCatch({
  a <- commandArgs(trailingOnly = FALSE)
  f <- sub("^--file=", "", a[grep("^--file=", a)])
  if (length(f)) dirname(normalizePath(f)) else "tests/fixtures/sa_did"
}, error = function(e) "tests/fixtures/sa_did")
cat("Output dir:", out_dir, "\n")

# -------- fit + extract one fixture --------
fit_sunab <- function(d) {
  feols(y ~ sunab(cohort, year) | id + year,
        data = d, ssc = LOCKED_SSC, cluster = ~ id)
}

parse_ge <- function(nm) {
  e <- as.numeric(sub("year::(-?\\d+):cohort::(-?\\d+)", "\\1", nm))
  g <- as.numeric(sub("year::(-?\\d+):cohort::(-?\\d+)", "\\2", nm))
  list(g = g, e = e)
}

build_oracle <- function(d, name) {
  m <- fit_sunab(d)

  # --- per-(g,e) CATT coefficients (authoritative SA raw output) ---
  cf  <- coef(m, agg = FALSE)
  nm  <- names(cf)
  ge  <- parse_ge(nm)
  stopifnot(all(is.finite(cf)), !any(is.na(ge$g)), !any(is.na(ge$e)))

  # --- bare cluster vcov (clustered by id, locked ssc) ---
  # vcov(m, agg = FALSE) default already equals the explicit bare cluster-by-id
  # under the model's ssc (verified: max diff 0). We pass it explicitly anyway.
  V <- vcov(m, agg = FALSE, cluster = ~ id, ssc = LOCKED_SSC)
  v_names <- rownames(V)
  V <- matrix(as.numeric(V), nrow = nrow(V), ncol = ncol(V))  # strip fixest_vcov class
  stopifnot(all(is.finite(V)), identical(v_names, nm))
  ge_v <- parse_ge(v_names)   # parallel keys aligned to vcov rows/cols

  # --- aggregated dynamic event study (period-aggregated): names year::<e> ---
  agg  <- coef(m)
  agg_e <- as.numeric(sub("year::(-?\\d+)", "\\1", names(agg)))
  stopifnot(all(is.finite(agg)), !any(is.na(agg_e)))

  # --- single overall ATT (harmless, cheap) ---
  att_overall <- tryCatch(
    as.numeric(coef(summary(m, agg = "att"))["ATT"]),
    error = function(e) NA_real_
  )

  obj <- list(
    fixture       = name,
    ssc           = "adj=FALSE,cluster.adj=FALSE",
    cluster       = "id",
    # per-(g,e) CATT
    coef          = as.numeric(cf),
    coef_g        = ge$g,
    coef_e        = ge$e,
    coef_name     = nm,
    # bare cluster vcov + parallel (g,e) keys (same order as matrix rows/cols)
    vcov          = V,
    vcov_g        = ge_v$g,
    vcov_e        = ge_v$e,
    vcov_name     = v_names,
    # aggregated dynamic target
    agg_estimate  = as.numeric(agg),
    agg_e         = agg_e,
    agg_name      = names(agg),
    att_overall   = att_overall
  )
  obj
}

write_fixture <- function(d, name) {
  obj <- build_oracle(d, name)
  jpath <- file.path(out_dir, paste0("sunab_", name, ".json"))
  write_json(obj, jpath, digits = 16, matrix = "rowmajor", auto_unbox = TRUE,
             pretty = TRUE)
  # CSV the Python engine reads: never-treated cohort = NA (empty).
  cpath <- file.path(out_dir, paste0("panel_", name, ".csv"))
  out <- d[, c("id", "year", "cohort", "y")]
  write.csv(out, cpath, row.names = FALSE, na = "")  # NA -> empty cell
  cat(sprintf("[%s] %d per-(g,e) cells, %d agg periods -> %s , %s\n",
              name, length(obj$coef), length(obj$agg_estimate),
              basename(jpath), basename(cpath)))
  invisible(obj)
}

# =============================================================================
# PANEL 1 — BALANCED: 3 treated cohorts {3,4,5} + never-treated; T = 1..7.
# Full common support: every treated cohort observed at every in-range relative
# period (no gaps). Dynamic effect grows with event time (0.8 + 0.5*rel) + noise.
# This is required so the aggregation-weighting equivalence test can isolate the
# n_g vs N_{g,e} weighting claim without a support gap masquerading as a
# weighting difference.
# =============================================================================
make_balanced <- function() {
  set.seed(202)
  N <- 120; Tn <- 7; ids <- 1:N
  cohort_map <- c(3, 4, 5, NA)[((ids - 1) %% 4) + 1]   # 30 ids per group
  d <- expand.grid(id = ids, year = 1:Tn)
  d$cohort <- cohort_map[d$id]
  d$rel    <- ifelse(is.na(d$cohort), Inf, d$year - d$cohort)
  d$treat  <- ifelse(!is.na(d$cohort) & d$year >= d$cohort, 1, 0)
  fe_id <- rnorm(N)[d$id]; fe_yr <- (1:Tn)[d$year] * 0.1
  d$y <- fe_id + fe_yr + ifelse(d$treat == 1, 0.8 + 0.5 * d$rel, 0) +
         rnorm(nrow(d), sd = 0.3)
  d
}

# =============================================================================
# PANEL 2 — UNBALANCED: same DGP as balanced (seed 202), then DROP rows so that
# observed counts N_{g,e} differ across cohorts at the same event time, while
# cohort sizes n_g stay equal (30 each). Half of cohort-4 ids lose year>=6;
# every 3rd cohort-3 id loses year 7. Result: at e=2 cohort-3 has N=30 but
# cohort-4 has N=15, so sunab's observed-count weighting diverges from n_g
# weighting by >> 1e-6.
# =============================================================================
make_unbalanced <- function() {
  d <- make_balanced()   # identical DGP/seed, then drop rows
  c4 <- unique(d$id[!is.na(d$cohort) & d$cohort == 4])
  c3 <- unique(d$id[!is.na(d$cohort) & d$cohort == 3])
  drop4 <- c4[seq(1, length(c4), 2)]    # half of cohort 4
  drop3 <- c3[seq(1, length(c3), 3)]    # every 3rd of cohort 3
  keep <- !((d$id %in% drop4 & d$year >= 6) | (d$id %in% drop3 & d$year == 7))
  d[keep, ]
}

# =============================================================================
# PANEL 3 — COLLINEAR / ZERO-SUPPORT: drop ALL cohort-4 observations at year 4
# (their relative period e=0), so the cohort×period cell (g=4, e=0) has ZERO
# observations. That cell is genuinely ABSENT from sunab's per-(g,e) coef set,
# yet the fit completes (other cohort-4 cells survive). The downstream test
# asserts (g=4,e=0) is absent from the engine's estimates and the run succeeds.
# =============================================================================
make_collinear <- function() {
  set.seed(303)
  N <- 120; Tn <- 7; ids <- 1:N
  cohort_map <- c(3, 4, 5, NA)[((ids - 1) %% 4) + 1]
  d <- expand.grid(id = ids, year = 1:Tn)
  d$cohort <- cohort_map[d$id]
  d$rel    <- ifelse(is.na(d$cohort), Inf, d$year - d$cohort)
  d$treat  <- ifelse(!is.na(d$cohort) & d$year >= d$cohort, 1, 0)
  fe_id <- rnorm(N)[d$id]; fe_yr <- (1:Tn)[d$year] * 0.1
  d$y <- fe_id + fe_yr + ifelse(d$treat == 1, 0.8 + 0.5 * d$rel, 0) +
         rnorm(nrow(d), sd = 0.3)
  keep <- !(!is.na(d$cohort) & d$cohort == 4 & d$year == 4)  # zero-support cell
  d[keep, ]
}

# -------- generate all three --------
ob <- write_fixture(make_balanced(),   "balanced")
ou <- write_fixture(make_unbalanced(), "unbalanced")
oc <- write_fixture(make_collinear(),  "collinear")

# -------- sanity: collinear must miss (g=4, e=0) --------
collinear_missing_40 <- !any(oc$coef_g == 4 & oc$coef_e == 0)
cat("\nSANITY collinear (g=4,e=0) absent from coef:", collinear_missing_40, "\n")
stopifnot(collinear_missing_40)
# present cohort-4 cells in collinear (confirms the run completed, only the cell dropped)
c4_cells <- which(oc$coef_g == 4)
cat("collinear surviving cohort-4 cells (e):", oc$coef_e[c4_cells], "\n")

cat("\nDONE. All fixtures written.\n")
