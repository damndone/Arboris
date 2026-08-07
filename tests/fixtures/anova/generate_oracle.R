# Oracle generator for factorial ANOVA and ANCOVA.
# Requires: car, jsonlite  (declared in tests/fixtures/r-oracle-requirements.txt)
#
# Writes, next to this file:
#   anova.csv    UNBALANCED two-factor design with a covariate
#   oracle.json  Type I, II and III sums of squares, effect sizes, post-hoc
#
# Run from the worktree root:
#   Rscript tests/fixtures/anova/generate_oracle.R
#
# The design is deliberately unbalanced, and that is the whole point. In a
# balanced design Type I, II and III sums of squares coincide, so a balanced
# fixture cannot tell which type an implementation actually computed -- the test
# would pass whichever it picked.
#
# It also pins down a real portability trap: SPSS's GLM defaults to Type III,
# R's `aov` gives Type I. A user moving between them gets different F statistics
# and different p values from the same data with nothing on screen to say why.
# Whatever this repository computes has to be declared, not defaulted silently.

source("tests/fixtures/_r_oracle_env.R")
require_oracle_packages("car", "jsonlite")
suppressMessages({library(car); library(jsonlite)})

set.seed(20260806)

# Unbalanced on purpose: cell sizes 12/7/9/15/6/11.
cells <- list(
  list(a = "a1", b = "b1", n = 12, mu = 10),
  list(a = "a1", b = "b2", n = 7,  mu = 13),
  list(a = "a1", b = "b3", n = 9,  mu = 11),
  list(a = "a2", b = "b1", n = 15, mu = 14),
  list(a = "a2", b = "b2", n = 6,  mu = 12),
  list(a = "a2", b = "b3", n = 11, mu = 17)
)

rows <- do.call(rbind, lapply(cells, function(cell) {
  cov <- rnorm(cell$n, mean = 5, sd = 2)
  data.frame(
    factor_a = cell$a,
    factor_b = cell$b,
    covariate = cov,
    score = cell$mu + 0.8 * cov + rnorm(cell$n, 0, 2),
    stringsAsFactors = FALSE
  )
}))
rows$factor_a <- factor(rows$factor_a)
rows$factor_b <- factor(rows$factor_b)
write.csv(rows, "tests/fixtures/anova/anova.csv", row.names = FALSE)

# Type III requires sum-to-zero contrasts to be meaningful; with treatment
# contrasts the "main effects" it reports are effects at the reference level,
# which is a different quantity wearing the same name.
options(contrasts = c("contr.sum", "contr.poly"))

as_table <- function(tbl) {
  df <- as.data.frame(tbl)
  terms <- rownames(df)
  out <- list()
  for (i in seq_along(terms)) {
    row <- df[i, ]
    # NA has to reach JSON as null. Left alone jsonlite writes the string "NA";
    # replaced with R's NULL it writes an empty object. `na = "null"` on the
    # writer is the only form that produces the value a consumer expects.
    out[[terms[i]]] <- list(
      sum_sq = as.numeric(row[["Sum Sq"]]),
      df = as.numeric(row[["Df"]]),
      f = if ("F value" %in% names(row)) as.numeric(row[["F value"]]) else NA,
      p_value = if ("Pr(>F)" %in% names(row)) as.numeric(row[["Pr(>F)"]]) else NA
    )
  }
  out
}

fit_anova <- lm(score ~ factor_a * factor_b, data = rows)
fit_ancova <- lm(score ~ covariate + factor_a * factor_b, data = rows)

# Partial eta squared = SS_effect / (SS_effect + SS_residual).
partial_eta_sq <- function(tbl) {
  df <- as.data.frame(tbl)
  ss_res <- df["Residuals", "Sum Sq"]
  terms <- setdiff(rownames(df), "Residuals")
  out <- list()
  for (t in terms) out[[t]] <- df[t, "Sum Sq"] / (df[t, "Sum Sq"] + ss_res)
  out
}

anova_t2 <- Anova(fit_anova, type = 2)
anova_t3 <- Anova(fit_anova, type = 3)
ancova_t3 <- Anova(fit_ancova, type = 3)

out <- list(
  environment = oracle_environment(c("car", "jsonlite")),
  design = list(
    n_obs = nrow(rows),
    balanced = FALSE,
    cell_sizes = vapply(cells, function(c) c$n, numeric(1)),
    contrasts = "contr.sum",
    note = paste(
      "Unbalanced by construction so Type I, II and III differ;",
      "a balanced fixture cannot discriminate between them."
    )
  ),
  anova = list(
    type_1 = as_table(anova(fit_anova)),
    type_2 = as_table(anova_t2),
    type_3 = as_table(anova_t3),
    partial_eta_squared_type_3 = partial_eta_sq(anova_t3),
    coefficients = as.list(coef(fit_anova))
  ),
  ancova = list(
    type_3 = as_table(ancova_t3),
    partial_eta_squared_type_3 = partial_eta_sq(ancova_t3),
    coefficients = as.list(coef(fit_ancova))
  )
)

write_json(out, "tests/fixtures/anova/oracle.json", digits = 14, auto_unbox = TRUE, na = "null")

# The fixture must actually discriminate; if the types ever coincide it has
# stopped testing anything and should fail here rather than downstream.
t1 <- as.data.frame(anova(fit_anova))["factor_a", "Sum Sq"]
t3 <- as.data.frame(anova_t3)["factor_a", "Sum Sq"]
stopifnot(abs(t1 - t3) > 1e-6)
cat("anova oracle written; n =", nrow(rows),
    " SS(factor_a) type1 =", round(t1, 6), " type3 =", round(t3, 6), "\n")
