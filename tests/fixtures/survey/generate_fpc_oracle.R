# Linearization reference WITH the fixture's finite population correction.
# generate_oracle.R builds its design without fpc = ~fpc although design.csv
# carries fpc = 500; before v1.8.11 Workbench ignored a supplied FPC, so the
# two agreed. This file is the reference for runs that declare the FPC column.
suppressPackageStartupMessages({ library(survey); library(jsonlite) })
rows <- read.csv("tests/fixtures/survey/design.csv", stringsAsFactors = FALSE)
des <- svydesign(id = ~psu, strata = ~stratum, weights = ~weight, fpc = ~fpc, data = rows, nest = TRUE)
fit <- svyglm(y ~ x1 + x2, design = des)
co <- summary(fit)$coefficients
out <- list(
  environment = list(R = R.version.string, survey = as.character(packageVersion("survey"))),
  design = "svydesign(id=~psu, strata=~stratum, weights=~weight, fpc=~fpc, nest=TRUE)",
  linearization_fpc = list(
    estimate = as.list(co[, 1]), se = as.list(co[, 2]),
    t_value = as.list(co[, 3]), p_value = as.list(co[, 4]), degf = degf(des)
  )
)
writeLines(toJSON(out, auto_unbox = TRUE, digits = NA, pretty = TRUE), "tests/fixtures/survey/oracle_fpc.json")
