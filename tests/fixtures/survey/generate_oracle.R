# Oracle generator for v1.8.7 complex survey design.
# Requires: survey, jsonlite  (declared in tests/fixtures/r-oracle-requirements.txt)
#
# Writes, next to this file:
#   design.csv        stratified two-PSU-per-stratum sample (80 rows)
#   lonely.csv        same shape but one stratum reduced to a single PSU
#   oracle.json       every reference value the Python engine must reproduce
#
# Run from the worktree root:
#   Rscript tests/fixtures/survey/generate_oracle.R
#
# Fixture design notes (these are load-bearing, not incidental):
#   * exactly 2 PSUs per stratum, because BRR requires a balanced design;
#   * degf = 16 PSUs - 8 strata = 8, so the t critical value (2.306) is far from
#     the normal one (1.96) -- a test that confuses them cannot pass by accident;
#   * `subpop` deliberately CUTS ACROSS strata and PSUs.  Subsetting on the
#     stratum variable itself removes whole strata cleanly and makes the correct
#     and incorrect approaches agree, which would make the subpopulation test
#     prove nothing.

source("tests/fixtures/_r_oracle_env.R")
versions <- require_oracle_packages("survey", "jsonlite")
suppressMessages({library(survey); library(jsonlite)})

set.seed(20260805)

n_strata <- 8
psu_per_stratum <- 2
obs_per_psu <- 5

rows <- do.call(rbind, lapply(seq_len(n_strata), function(h) {
  do.call(rbind, lapply(seq_len(psu_per_stratum), function(j) {
    psu <- sprintf("s%02d_p%d", h, j)
    x1 <- rnorm(obs_per_psu, mean = h, sd = 1)
    x2 <- runif(obs_per_psu, 0, 10)
    psu_effect <- rnorm(1, 0, 2)          # PSU-level clustering
    y <- 5 + 1.5 * x1 - 0.4 * x2 + psu_effect + rnorm(obs_per_psu, 0, 1)
    data.frame(
      stratum = sprintf("h%02d", h),
      psu = psu,
      y = y, x1 = x1, x2 = x2,
      weight = 10 + 2 * h,                # unequal weights across strata
      fpc = 500,
      # cuts across strata and PSUs on purpose (see header)
      subpop = ifelse(x2 > 5, 1L, 0L),
      stringsAsFactors = FALSE
    )
  }))
}))

write.csv(rows, "tests/fixtures/survey/design.csv", row.names = FALSE)

des <- svydesign(id = ~psu, strata = ~stratum, weights = ~weight, data = rows, nest = TRUE)

fit <- svyglm(y ~ x1 + x2, design = des)
co <- summary(fit)$coefficients
ci <- confint(fit)

# ---- replicate designs -------------------------------------------------------
rep_se <- function(type, ...) {
  rd <- as.svrepdesign(des, type = type, ...)
  s <- summary(svyglm(y ~ x1 + x2, design = rd))$coefficients
  list(estimate = as.list(s[, 1]), se = as.list(s[, 2]))
}
set.seed(101); brr  <- rep_se("BRR")
set.seed(102); jkn  <- rep_se("JKn")
set.seed(103); boot <- rep_se("bootstrap", replicates = 500)

# Provided replicate weights: emit BRR weights as plain columns so the engine can
# be tested on the NHANES/CPS shape, where the publisher ships the weights.
brr_design <- as.svrepdesign(des, type = "BRR")
rep_w <- as.data.frame(weights(brr_design, type = "analysis"))
names(rep_w) <- sprintf("repw%02d", seq_len(ncol(rep_w)))
write.csv(cbind(rows, rep_w), "tests/fixtures/survey/design_with_replicate_weights.csv",
          row.names = FALSE)
provided <- local({
  # `weights(type = "analysis")` already folds the sampling weight into each
  # replicate, so these are combined weights.  Declaring otherwise makes survey
  # warn and rescale, and the published NHANES/CPS shape is combined too.
  rd <- svrepdesign(data = rows, weights = ~weight, repweights = rep_w,
                    type = "BRR", combined.weights = TRUE)
  s <- summary(svyglm(y ~ x1 + x2, design = rd))$coefficients
  list(estimate = as.list(s[, 1]), se = as.list(s[, 2]))
})

# Self-check: consuming the published replicate weights must reproduce the BRR
# design exactly -- they are the same design expressed two ways.  If this drifts,
# the fixture is wrong and every downstream assertion built on it is worthless.
stopifnot(all.equal(provided$se, brr$se, tolerance = 1e-12))

# ---- subpopulation: design-internal vs pre-filtered --------------------------
# Needs its OWN fixture with 3 PSUs per stratum.
#
# A first attempt reused the main design and defined the subpopulation as
# `x2 > 5`.  It cut across strata and PSUs, but left every PSU non-empty, so the
# design structure was unchanged and the correct and incorrect approaches
# produced byte-identical standard errors -- a fixture that proves nothing.
#
# The difference only appears when the subpopulation EMPTIES whole PSUs:
# design-internal subsetting keeps them for variance purposes, while filtering
# the data first makes them vanish, changing the PSU counts and degf.  Three PSUs
# per stratum means dropping one still leaves two, so the incorrect path yields a
# different variance rather than collapsing into a lonely-PSU error.
sub_rows <- do.call(rbind, lapply(seq_len(6), function(h) {
  do.call(rbind, lapply(seq_len(3), function(j) {
    psu <- sprintf("t%02d_p%d", h, j)
    x1 <- rnorm(obs_per_psu, mean = h, sd = 1)
    x2 <- runif(obs_per_psu, 0, 10)
    y <- 4 + 1.2 * x1 - 0.3 * x2 + rnorm(1, 0, 2) + rnorm(obs_per_psu, 0, 1)
    data.frame(
      stratum = sprintf("t%02d", h), psu = psu, y = y, x1 = x1, x2 = x2,
      weight = 8 + 3 * h,
      # whole PSUs excluded, plus scattered within-PSU exclusions
      subpop = if (psu %in% c("t02_p3", "t05_p1")) 0L else ifelse(x2 > 1, 1L, 0L),
      stringsAsFactors = FALSE
    )
  }))
}))
write.csv(sub_rows, "tests/fixtures/survey/subpop.csv", row.names = FALSE)

sub_des <- svydesign(id = ~psu, strata = ~stratum, weights = ~weight,
                     data = sub_rows, nest = TRUE)
sub_correct <- svyglm(y ~ x1 + x2, design = subset(sub_des, subpop == 1))
pre <- subset(sub_rows, subpop == 1)
sub_wrong <- svyglm(
  y ~ x1 + x2,
  design = svydesign(id = ~psu, strata = ~stratum, weights = ~weight,
                     data = pre, nest = TRUE)
)

# The whole point of the fixture is that these two disagree.  If they ever match,
# the fixture stopped discriminating and every subpopulation assertion built on
# it silently becomes vacuous.
stopifnot(!isTRUE(all.equal(unname(SE(sub_correct)), unname(SE(sub_wrong)),
                            tolerance = 1e-10)))

# ---- lonely PSU: five策略 ----------------------------------------------------
lonely_rows <- rows[!(rows$stratum == "h01" & rows$psu == "s01_p2"), ]
write.csv(lonely_rows, "tests/fixtures/survey/lonely.csv", row.names = FALSE)

lonely_se <- list()
for (opt in c("fail", "remove", "adjust", "average", "certainty")) {
  options(survey.lonely.psu = opt)
  lonely_se[[opt]] <- tryCatch({
    ld <- svydesign(id = ~psu, strata = ~stratum, weights = ~weight,
                    data = lonely_rows, nest = TRUE)
    s <- summary(svyglm(y ~ x1 + x2, design = ld))$coefficients
    list(status = "ok", se = as.list(s[, 2]))
  }, error = function(e) list(status = "error", message = conditionMessage(e)))
}
options(survey.lonely.psu = "fail")

# ---- design effect, effective sample size, adjusted Wald ---------------------
deff_mean <- svymean(~y, des, deff = TRUE)
w <- rows$weight
wald <- regTermTest(fit, ~ x1 + x2, method = "Wald")

out <- list(
  environment = oracle_environment(c("survey", "jsonlite")),
  design = list(
    n_obs = nrow(rows),
    n_strata = length(unique(rows$stratum)),
    n_psu = nrow(unique(rows[, c("stratum", "psu")])),
    degf = degf(des)
  ),
  linearization = list(
    estimate = as.list(co[, 1]), se = as.list(co[, 2]),
    t_value = as.list(co[, 3]), p_value = as.list(co[, 4]),
    ci_lower = as.list(ci[, 1]), ci_upper = as.list(ci[, 2])
  ),
  replicate = list(brr = brr, jackknife = jkn, bootstrap = boot, provided = provided),
  subpopulation = list(
    fixture = "tests/fixtures/survey/subpop.csv",
    design_internal = list(
      estimate = as.list(coef(sub_correct)), se = as.list(SE(sub_correct)),
      degf = degf(subset(sub_des, subpop == 1))
    ),
    pre_filtered_incorrect = list(
      estimate = as.list(coef(sub_wrong)), se = as.list(SE(sub_wrong)),
      degf = degf(svydesign(id = ~psu, strata = ~stratum, weights = ~weight,
                            data = pre, nest = TRUE))
    )
  ),
  lonely_psu = lonely_se,
  design_effect = list(
    deff_y = as.numeric(deff(deff_mean)),
    mean_y = as.numeric(coef(deff_mean)),
    se_y = as.numeric(SE(deff_mean)),
    kish_n_eff = sum(w)^2 / sum(w^2),
    n_obs = length(w)
  ),
  adjusted_wald = list(
    statistic = as.numeric(wald$Ftest),
    df = as.numeric(wald$df),
    ddf = as.numeric(wald$ddf),
    p_value = as.numeric(wald$p)
  )
)

write_json(out, "tests/fixtures/survey/oracle.json", digits = 14, auto_unbox = TRUE)
cat("survey oracle written; degf =", degf(des),
    " deff =", as.numeric(deff(deff_mean)), "\n")
