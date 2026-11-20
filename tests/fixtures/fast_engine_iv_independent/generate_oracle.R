# Independent R oracle: fixest estimation and covariance, base-R QR auxiliary regressions,
# sandwich HC0, and R's upper-tail distribution functions. Does not import product outputs.
# Reproduce: LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 Rscript tests/fixtures/fast_engine_iv_independent/generate_oracle.R
source("tests/fixtures/_r_oracle_env.R")
packages <- require_oracle_packages("fixest", "sandwich", "jsonlite")
suppressPackageStartupMessages({library(fixest); library(sandwich); library(jsonlite)})
here <- "tests/fixtures/fast_engine_iv_independent"
input <- file.path(here, "data.csv")
base <- read.csv(input)
clean_names <- function(x) sub("^fit_", "", sub("^\\(Intercept\\)$", "Intercept", x))
named <- function(x) {names(x) <- clean_names(names(x)); as.list(x)}
covariance <- function(fit, kind) {
  if (kind == "robust") sandwich::vcovHC(fit, type = "HC0") else vcov(fit) * df.residual(fit) / nobs(fit)
}
joint <- function(fit, terms, kind) {
  beta <- coef(fit)[terms]; v <- covariance(fit, kind)[terms, terms, drop = FALSE]
  as.numeric(crossprod(beta, solve(v, beta)))
}
stat <- function(value, df, denominator = NULL) {
  list(stat = value, df = df, df_denom = denominator,
       pval = if (is.null(denominator)) pchisq(value, df, lower.tail = FALSE) else pf(value, df, denominator, lower.tail = FALSE))
}
cases <- list()
for (shape in c("plain", "weak", "small", "missing", "shifted", "tail", "just")) {
  d <- base
  if (shape == "weak") d$d1 <- d$d1 - .595*d$z1 - .395*d$z2
  if (shape == "small") d <- d[1:8, ]
  if (shape == "missing") {
    for (i in 1:4) d[i, c("y", "w", "d1", "z1")[i]] <- NA_real_
  }
  if (shape == "shifted") { d$z1 <- d$z1 + 7 + 4*d$w; d$z2 <- d$z2 - 3 + 2*d$w }
  if (shape == "tail") d$y <- d$y + 6*d$d1
  endog <- if (shape == "just") "d1" else c("d1", "d2")
  instruments <- if (shape == "just") "z1" else c("z1", "z2", "z3")
  d <- na.omit(d[, c("y", "w", endog, instruments)])
  n <- nrow(d); k <- 2 + length(endog); m <- length(endog); l <- length(instruments)
  f <- as.formula(paste("y ~ w |", paste(endog, collapse = " + "), "~", paste(instruments, collapse = " + ")))
  first <- lapply(endog, function(x) lm(reformulate(c("w", instruments), response = x), data = d))
  names(first) <- endog
  for (name in endog) d[[paste0("res_", name)]] <- residuals(first[[name]])
  ordinary <- lm(reformulate(c("w", endog), response = "y"), data = d)
  auxiliary <- lm(reformulate(c("w", endog, paste0("res_", endog)), response = "y"), data = d)
  out <- list(nobs = n, df_model = k, df_resid = n-k, endog = endog, instruments = instruments)
  for (kind in c("robust", "unadjusted")) {
    fit <- feols(f, data = d, vcov = if (kind == "robust") "hetero" else "iid", ssc = ssc(K.adj = FALSE, G.adj = FALSE))
    beta <- coef(fit); names(beta) <- clean_names(names(beta))
    v <- vcov(fit); dimnames(v) <- lapply(dimnames(v), clean_names)
    # fixest iid with no K adjustment is sigma^2 = SSR/(n-1); the product uses SSR/n.
    if (kind == "unadjusted") v <- v*(n-1)/n
    se <- sqrt(diag(v)); t <- beta/se
    values <- list(params = as.list(beta), std_errors = as.list(se), tstats = as.list(t),
                   pvalues = as.list(2*pnorm(-abs(t))), cov = lapply(seq_len(nrow(v)), function(i) as.list(v[i, ])))
    names(values$cov) <- rownames(v)
    values$first_stage <- lapply(first, function(fs) {
      w <- joint(fs, instruments, kind)
      if (kind == "robust") stat(w, l) else stat(w/l, l, n-2-l)
    })
    values$wooldridge_regression <- stat(joint(auxiliary, paste0("res_", endog), kind), m)
    e <- residuals(fit)
    z <- model.matrix(reformulate(c("w", instruments)), data = d)
    if (l > m) {
      fitted_endog <- sapply(first, fitted)
      basis <- cbind(model.matrix(~w, d), fitted_endog)
      omitted_scores <- sapply(instruments[seq_len(l-m)], function(name) qr.resid(qr(basis), d[[name]]) * e)
      score_fit <- lm.fit(as.matrix(omitted_scores), rep(1, n))
      values$wooldridge_overid <- stat(sum(score_fit$fitted.values^2), l-m)
    }
    if (kind == "unadjusted") {
      if (l > m) values$sargan <- stat(n*sum(qr.fitted(qr(z), e)^2)/sum(e^2), l-m)
      delta <- sum(qr.fitted(qr(cbind(z, as.matrix(d[, endog, drop = FALSE]))), residuals(ordinary))^2) -
               sum(qr.fitted(qr(as.matrix(d[, instruments, drop = FALSE])), e)^2)
      values$wu_hausman_excluded_projection <- stat((delta/m)/((sum(residuals(ordinary)^2)-delta)/(n-k-m)), m, n-k-m)
      control_f <- ((sum(residuals(ordinary)^2)-sum(residuals(auxiliary)^2))/m)/(sum(residuals(auxiliary)^2)/(n-k-m))
      values$wu_hausman_control_function <- stat(control_f, m, n-k-m)
      values$wu_hausman_fixest <- fitstat(fit, "wh")$wh
    }
    out[[kind]] <- values
  }
  cases[[shape]] <- out
}
oracle <- list(meta = list(generator = "tests/fixtures/fast_engine_iv_independent/generate_oracle.R",
                          data_sha256 = system2("shasum", c("-a", "256", input), stdout = TRUE),
                          environment = oracle_environment(names(packages)), stata_runtime = "not tested; executable unavailable",
                          definition_sources = c(
                            "https://lrberge.github.io/fixest/reference/ssc.html",
                            "https://lrberge.github.io/fixest/reference/fitstat.html",
                            "https://bashtage.github.io/linearmodels/iv/iv/linearmodels.iv.results.IVResults.wu_hausman.html",
                            "https://www.stata.com/manuals/rivregresspostestimation.pdf"),
                          normal_critical_values = as.list(setNames(qnorm(c(.95, .975, .995)), c("0.9", "0.95", "0.99"))),
                          definitions = list(
                            covariance = "iid SSR/n or HC0, no K adjustment; normal coefficient tails",
                            first_stage = "iid Wald/l with F(l,n-kz), HC0 Wald with chi2(l)",
                            wu_hausman = "excluded-projection and nested-control F retained separately; fixest wh retained unmodified")),
               cases = cases)
write_json(oracle, file.path(here, "oracle.json"), auto_unbox = TRUE, digits = 17, pretty = TRUE, null = "null")
