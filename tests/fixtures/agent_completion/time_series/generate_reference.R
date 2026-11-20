library(urca)
library(jsonlite)
d <- read.csv("tests/fixtures/agent_completion/time_series/input.csv")
a <- ur.df(d$y, type="drift", lags=4, selectlags="Fixed")
k <- ur.kpss(d$y, type="mu", use.lag=4)
b <- Box.test(d$innovation, lag=10, type="Ljung-Box", fitdf=1)
# Native regression oracle for the uncentered squared-innovation LM.
z <- embed(d$innovation^2, 11)
lmfit <- lm(z[,1] ~ z[,-1])
rawLM <- nrow(z)*summary(lmfit)$r.squared
out <- list(version=R.version.string, urca=as.character(packageVersion("urca")),
 adf=unname(a@teststat[1,"tau2"]), kpss=unname(k@teststat),
 ljung_box=unname(b$statistic), ljung_box_p=unname(b$p.value),
 arch_lm_raw=rawLM, arch_lm_ddof1=rawLM*(nrow(z)-1)/nrow(z))
write_json(out, "tests/fixtures/agent_completion/time_series/reference_r.json", auto_unbox=TRUE, digits=17, pretty=TRUE)
