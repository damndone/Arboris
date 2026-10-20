library(jsonlite)
y <- read.csv('tests/fixtures/arma_garch_joint/oracle_v1/data_garch11_constant.csv')$y
s <- read.csv('tests/fixtures/arma_garch_joint/oracle_v1/series_garch11_constant.csv')
z <- s$residual_opg / sqrt(s$variance_opg)
lb <- Box.test(z, lag=10, type='Ljung-Box', fitdf=2)
sq <- Box.test(z^2, lag=10, type='Ljung-Box', fitdf=0)
e <- embed(z^2,11)
aux <- lm(e[,1] ~ e[,-1])
lm <- (nrow(e)-2)*summary(aux)$r.squared
write_json(list(version=R.version.string, residual_n=length(z), ljung_box=unname(lb$statistic),
 ljung_box_p=unname(lb$p.value), squared_ljung_box=unname(sq$statistic), squared_ljung_box_p=unname(sq$p.value),
 arch_lm=lm, arch_lm_p=pchisq(lm,10,lower.tail=FALSE)),
 'tests/fixtures/agent_completion/time_series/garch_reference_r.json', digits=17, auto_unbox=TRUE, pretty=TRUE)
