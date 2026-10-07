# VERIFICATION LEVEL: compare R epsilon=1e-14 with a further-converged NB GLM.
args <- commandArgs(trailingOnly=TRUE)
input <- normalizePath(args[[1]],mustWork=TRUE);output <- args[[2]]
stopifnot(!file.exists(output))
cat("GLM precision evidence output:",output,"\n")
library(MASS);library(jsonlite)
d <- read.csv(input)
rows <- lapply(c(1e-14,1e-16),function(eps) {
 f <- glm(y~x1+x2,data=d,family=negative.binomial(theta=1),control=glm.control(epsilon=eps,maxit=1000))
 list(epsilon=eps,coefficients=unname(coef(f)),std_error=unname(sqrt(diag(vcov(f,dispersion=1)))),ll=as.numeric(logLik(f)),iterations=f$iter)
})
write_json(list(meta=list(r_version=R.version.string,n=nrow(d)),cases=rows),output,auto_unbox=TRUE,pretty=TRUE,digits=NA)
