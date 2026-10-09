# Supplementary REML population margins; original ML and FAIL evidence untouched.
suppressPackageStartupMessages({library(lme4);library(jsonlite)})
one <- function(path, random) {
 d <- read.csv(path); d <- d[complete.cases(d[,c("y","arm","time","x","g")]),]
 fit <- lmer(as.formula(paste("y~arm*time+x+",random)),d,REML=TRUE,
   control=lmerControl(optimizer="bobyqa",optCtrl=list(rhoend=1e-12,maxfun=1e6)))
 b <- fixef(fit); V <- as.matrix(vcov(fit))
 one_effect <- function(variable) {
  L <- setNames(rep(0,length(b)),names(b)); L[variable] <- 1
  if(variable=="time") L["armb:time"] <- mean(d$arm=="b")
  h <- 1e-4; plus <- minus <- d; plus[[variable]] <- plus[[variable]]+h; minus[[variable]] <- minus[[variable]]-h
  list(estimate=unname(sum(L*b)),std_error=as.numeric(sqrt(t(L)%*%V%*%L)),
       prediction_derivative=mean((predict(fit,newdata=plus,re.form=NA)-predict(fit,newdata=minus,re.form=NA))/(2*h)))
 }
 effects <- list(time=one_effect("time"),x=one_effect("x"))
 list(fit_method="REML",random_structure=random,converged=is.null(fit@optinfo$conv$lme4$messages),singular=isSingular(fit),
      margins=list(average=effects,at_means=effects))
}
result <- list(environment=list(R=R.version.string,lme4=as.character(packageVersion("lme4"))),
 random_intercept=one("tests/fixtures/admission/linear_mixed_effects/data.csv","(1|g)"),
 random_slope=one("tests/fixtures/postestimation/lmm_v1811/random_slope.csv","(1+time|g)"))
writeLines(toJSON(result,auto_unbox=TRUE,digits=NA,pretty=TRUE),"tests/fixtures/postestimation/lmm_v1813/native_reml_margins_r.json")
