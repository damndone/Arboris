#!/usr/bin/env Rscript
# v1.8.7 A3 — external oracles for the four families v1.8.6 shipped without one.
#
# Those families were validated against themselves: statsmodels is the execution
# engine, so checking it with statsmodels is internal consistency, not an oracle.
# This produces reference values from the R implementations practitioners
# actually cite, so a solver change in either project becomes visible.
#
# One dataset carries all four outcomes. They are generated from the *same*
# latent index, so a mistake in the shared design matrix would move every family
# at once and could not hide in one of them.
#
#   ordinal_logit      -> MASS::polr        (proportional odds)
#   multinomial_logit  -> nnet::multinom
#   quantile_regression-> quantreg::rq      (tau = 0.25, 0.5, 0.75)
#   survival_cox       -> survival::coxph   (Efron ties, the statsmodels default)
#
# Run from the worktree root:
#   Rscript tests/fixtures/v186_families/generate_oracle.R

source("tests/fixtures/_r_oracle_env.R")
require_oracle_packages(c("MASS", "nnet", "quantreg", "survival", "jsonlite"))

set.seed(20260807)
n <- 240

x1 <- round(rnorm(n, mean = 0, sd = 1), 6)
x2 <- round(runif(n, min = -1.5, max = 1.5), 6)
# A binary regressor as well: a design of continuous columns only would not
# exercise the categorical handling any of the four engines applies.
grp <- rbinom(n, 1, 0.45)

latent <- 0.9 * x1 - 0.6 * x2 + 0.8 * grp + rlogis(n)

# --- ordered outcome (3 levels, deliberately unbalanced) --------------------
rating <- cut(latent, breaks = c(-Inf, -0.4, 1.1, Inf), labels = c("low", "mid", "high"))
rating <- factor(rating, levels = c("low", "mid", "high"), ordered = TRUE)

# --- unordered outcome (3 categories) --------------------------------------
# Not a re-coding of `rating`: an unordered outcome that is secretly ordered
# would let a model that ignores the distinction still match.
u <- cbind(0, 0.7 * x1 + 0.5 * grp, -0.8 * x2 + 0.4 * x1)
probs <- exp(u) / rowSums(exp(u))
choice <- factor(
  apply(probs, 1, function(p) sample(c("a", "b", "c"), 1, prob = p)),
  levels = c("a", "b", "c")
)

# --- continuous outcome, heteroskedastic so the quantiles genuinely differ --
# With homoskedastic noise every tau estimates the same slope and the fixture
# could not tell a correct quantile fit from one that ignored tau.
y <- 2.0 + 1.3 * x1 - 0.9 * x2 + 0.5 * grp + (1 + 0.8 * abs(x1)) * rnorm(n)
y <- round(y, 6)

# --- survival outcome -------------------------------------------------------
baseline <- 0.08
lp <- 0.7 * x1 - 0.5 * x2 + 0.6 * grp
event_time <- rexp(n, rate = baseline * exp(lp))
censor_time <- rexp(n, rate = 0.05)
duration <- round(pmin(event_time, censor_time), 6)
event <- as.integer(event_time <= censor_time)

frame <- data.frame(
  x1 = x1, x2 = x2, grp = grp,
  rating = as.character(rating), choice = as.character(choice),
  y = y, duration = duration, event = event,
  stringsAsFactors = FALSE
)

fixture_dir <- "tests/fixtures/v186_families"
write.csv(frame, file.path(fixture_dir, "families.csv"), row.names = FALSE)

# Guard the fixture itself: assertions below are worthless on degenerate data.
stopifnot(all(table(frame$rating) >= 40))
stopifnot(all(table(frame$choice) >= 40))
stopifnot(sum(frame$event) >= 80, sum(frame$event) <= n - 40)

# ---------------------------------------------------------------------------
# ordinal logit -- MASS::polr
# ---------------------------------------------------------------------------
ord_frame <- frame
ord_frame$rating <- factor(ord_frame$rating, levels = c("low", "mid", "high"), ordered = TRUE)
polr_fit <- MASS::polr(rating ~ x1 + x2 + grp, data = ord_frame, method = "logistic", Hess = TRUE)
polr_summary <- summary(polr_fit)

ordinal <- list(
  coefficients = as.list(coef(polr_fit)),
  # polr reports cutpoints as `low|mid`, `mid|high`; statsmodels calls them
  # thresholds and parameterises the second as an increment. The comparison is
  # made on the cumulative values, which is what both agree on.
  thresholds = as.list(polr_fit$zeta),
  std_errors = as.list(sqrt(diag(vcov(polr_fit)))[names(coef(polr_fit))]),
  log_likelihood = as.numeric(logLik(polr_fit)),
  n_obs = as.integer(nobs(polr_fit))
)

# ---------------------------------------------------------------------------
# multinomial logit -- nnet::multinom
# ---------------------------------------------------------------------------
mn_frame <- frame
mn_frame$choice <- factor(mn_frame$choice, levels = c("a", "b", "c"))
mn_fit <- nnet::multinom(choice ~ x1 + x2 + grp, data = mn_frame, trace = FALSE, maxit = 2000)
mn_coef <- coef(mn_fit)

multinomial <- list(
  baseline = "a",
  coefficients = lapply(
    setNames(rownames(mn_coef), rownames(mn_coef)),
    function(lvl) as.list(mn_coef[lvl, ])
  ),
  log_likelihood = as.numeric(logLik(mn_fit)),
  n_obs = as.integer(nrow(mn_frame))
)

# ---------------------------------------------------------------------------
# quantile regression -- quantreg::rq
# ---------------------------------------------------------------------------
taus <- c(0.25, 0.5, 0.75)
quantile_fits <- lapply(taus, function(tau) {
  fit <- quantreg::rq(y ~ x1 + x2 + grp, tau = tau, data = frame, method = "br")
  list(tau = tau, coefficients = as.list(coef(fit)))
})
names(quantile_fits) <- sprintf("tau_%s", taus)

# The slopes must actually differ across tau, or the fixture cannot detect a
# model that fit the mean and reported it three times.
slopes <- vapply(quantile_fits, function(f) f$coefficients$x1, numeric(1))
stopifnot(max(slopes) - min(slopes) > 0.05)

# ---------------------------------------------------------------------------
# Cox proportional hazards -- survival::coxph
# ---------------------------------------------------------------------------
cox_fit <- survival::coxph(
  survival::Surv(duration, event) ~ x1 + x2 + grp,
  data = frame, ties = "efron"
)
cox_summary <- summary(cox_fit)

cox <- list(
  ties = "efron",
  coefficients = as.list(coef(cox_fit)),
  std_errors = as.list(sqrt(diag(vcov(cox_fit)))),
  hazard_ratios = as.list(exp(coef(cox_fit))),
  log_likelihood = as.numeric(logLik(cox_fit)),
  n_obs = as.integer(cox_fit$n),
  n_events = as.integer(cox_fit$nevent)
)

oracle <- list(
  environment = oracle_environment(c("MASS", "nnet", "quantreg", "survival", "jsonlite")),
  design = list(
    n_obs = n,
    seed = 20260807,
    rating_counts = as.list(table(frame$rating)),
    choice_counts = as.list(table(frame$choice)),
    n_events = sum(frame$event)
  ),
  ordinal_logit = ordinal,
  multinomial_logit = multinomial,
  quantile_regression = quantile_fits,
  survival_cox = cox
)

jsonlite::write_json(
  oracle,
  file.path(fixture_dir, "oracle.json"),
  auto_unbox = TRUE, digits = 16, pretty = TRUE, na = "null"
)

cat("wrote families.csv and oracle.json\n")
