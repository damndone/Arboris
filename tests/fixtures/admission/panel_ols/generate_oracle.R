# VERIFICATION LEVEL (v1.8.11): standard errors clustered by g as Stata xtreg, fe vce(cluster g) -- CR1 with G/(G-1)*(N-1)/(N-K), K excluding the unit effects nested in the clusters, t(G-1) -- via fixest ssc(K.fixef="nested", G.df="min", t.df="min"). The intercept's estimate is the sum-to-zero one from lm; its standard error is not compared (Stata's _cons is a different parameter).
# Deterministic data, seed 20261003; no downloaded inputs.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
here <- args[1]; phase <- args[2]
stopifnot(here == "tests/fixtures/admission/panel_ols")
cat("output directory:", here, "phase:", phase, "\n")
dir.create(here, recursive=TRUE, showWarnings=FALSE)
set.seed(20261003)
n <- 400
g <- rep(seq_len(50), each=8); time <- rep(seq_len(8), 50)
x1 <- rnorm(n); x2 <- rnorm(n)
y <- 1 + .7*x1 - .4*x2 + rnorm(50)[g] + .2*time + rnorm(n)
data <- data.frame(y, x1, x2, g, time)
write.csv(data, file.path(here, "data.csv"), row.names=FALSE)
if (phase == "data") quit(status=0)
data <- read.csv(file.path(here, "data.csv"))
suppressPackageStartupMessages({library(jsonlite); library(fixest)})
fit <- feols(y ~ x1 + x2 | g + time, data=data, cluster=~g,
             ssc=ssc(K.adj=TRUE, K.fixef="nested", G.adj=TRUE, G.df="min", t.df="min"))
b <- coef(fit); se <- se(fit)
G <- length(unique(data$g))
sum_to_zero <- lm(y ~ x1 + x2 + factor(g) + factor(time), data=data,
          contrasts=list("factor(g)"="contr.sum", "factor(time)"="contr.sum"))
intercept <- unname(coef(sum_to_zero)["(Intercept)"])
oracle <- list(meta=list(generator="tests/fixtures/admission/panel_ols/generate_oracle.R",
                           r_version=R.version.string, fixest=as.character(packageVersion("fixest")),
                           seed=20261003, n=nrow(data),
                           verification_level="clustered by g as Stata xtreg, fe vce(cluster g); intercept estimate only"),
               inference=list(covariance_estimator="cluster", df_method="clusters_minus_one",
                              reference_distribution="t", df_resid=G - 1, n_clusters=G),
               coefficients=c(list(Intercept=intercept), as.list(b)), std_error=as.list(se))
writeLines(jsonlite::toJSON(oracle, auto_unbox=TRUE, digits=NA, pretty=TRUE), file.path(here,"oracle.json"))
cat("wrote oracle.json\n")
