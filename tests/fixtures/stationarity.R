args <- commandArgs(trailingOnly = TRUE)
values <- read.csv(args[1])$y
adf_lag <- as.integer(args[2])
kpss_lag <- as.integer(args[3])

adf <- urca::ur.df(values, type = "drift", lags = adf_lag, selectlags = "Fixed")
kpss <- urca::ur.kpss(values, type = "mu", use.lag = kpss_lag)
coef <- adf@testreg$coefficients["z.lag.1", ]
out <- c(adf = adf@teststat[1, "tau2"], gamma = coef[["Estimate"]], se = coef[["Std. Error"]],
         adf_n = sum(adf@testreg$df[1:2]), adf_df = adf@testreg$df[2], kpss = kpss@teststat[1],
         adf_cv5 = adf@cval["tau2", "5pct"], kpss_cv5 = kpss@cval[1, "5pct"])
cat(paste(names(out), collapse = ","), "\n", sep = "")
cat(paste(formatC(out, digits = 17, format = "g"), collapse = ","), "\n", sep = "")
