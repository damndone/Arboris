# Run from repository root. Existing source CSVs are read-only.
suppressPackageStartupMessages({library(lme4); library(jsonlite)})
root <- "tests/fixtures/postestimation/lmm_v1813"
one <- function(path, random) {
 d <- read.csv(path); d <- d[complete.cases(d[,c("y","arm","time","x","g")]),]
 control <- lmerControl(optimizer="bobyqa",optCtrl=list(rhoend=1e-12,maxfun=1e6))
 full <- lmer(as.formula(paste("y~arm*time+x+",random)),d,REML=FALSE,control=control)
 reduced <- lmer(as.formula(paste("y~arm*time+",random)),d,REML=FALSE,control=control)
 b <- fixef(full); V <- as.matrix(vcov(full)); share <- mean(d$arm=="b")
 contrast <- function(variable) {
  L <- setNames(rep(0,length(b)),names(b)); L[variable] <- 1
  if(variable=="time") L["armb:time"] <- share
  # Independent response prediction difference: population, random effects excluded.
  h <- 1e-4; plus <- minus <- d; plus[[variable]] <- plus[[variable]]+h; minus[[variable]] <- minus[[variable]]-h
  fd <- mean((predict(full,newdata=plus,re.form=NA)-predict(full,newdata=minus,re.form=NA))/(2*h))
  list(estimate=unname(sum(L*b)),std_error=as.numeric(sqrt(t(L)%*%V%*%L)),prediction_derivative=fd)
 }
 statistic <- 2*(as.numeric(logLik(full))-as.numeric(logLik(reduced)))
 list(nobs=nobs(full),same_sample=identical(rownames(model.frame(full)),rownames(model.frame(reduced))),
      random_structure=random,converged=is.null(full@optinfo$conv$lme4$messages)&&is.null(reduced@optinfo$conv$lme4$messages),
      singular=isSingular(full)||isSingular(reduced),loglik_full=as.numeric(logLik(full)),loglik_restricted=as.numeric(logLik(reduced)),
      statistic=statistic,df=1,p_value=pchisq(statistic,1,lower.tail=FALSE),arm_b_share=share,
      margins=list(x=contrast("x"),time=contrast("time")))
}
packages <- c("lme4","jsonlite","glmmTMB","marginaleffects","MASS")
inventory <- setNames(lapply(packages,function(p) if(requireNamespace(p,quietly=TRUE)) as.character(packageVersion(p)) else NA_character_),packages)
output <- list(environment=list(R=R.version.string,packages=inventory),
 random_intercept=one("tests/fixtures/admission/linear_mixed_effects/data.csv","(1|g)"),
 random_slope=one("tests/fixtures/postestimation/lmm_v1811/random_slope.csv","(1+time|g)"))
writeLines(toJSON(output,auto_unbox=TRUE,digits=NA,pretty=TRUE),file.path(root,"native_r.json"))
