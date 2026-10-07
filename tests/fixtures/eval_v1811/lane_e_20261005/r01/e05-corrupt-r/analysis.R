# Workbench 1.8.11
# project: script
# run: 20261005_091811_675151_95c6f12b
# lineage_hash: 44cdd1794406cf58e7845d729b4a21bf1c8ddacba382ef059f60da06f836b26d
# Coverage
# step_76b2427e32344554a37924aa | data.cleaning | native | 
# step_eca26cfbad39adff69c00721 | data.subset | native | 
# step_226b4b10776b3612293e8e34 | data.feature_recipe | native | 
# step_5bb28f6498e4698e7347d1d5 | data.cleaning | native | 
# step_59722572b3c11a55aa32ba09 | model.ols | native | 
# step_522468aadb113d7b603dca9b | postestimation.wald | native | 
data <- list()
results <- list()
checks <- list()
args <- commandArgs(FALSE)
script <- sub("^--file=", "", args[grepl("^--file=", args)])
base <- dirname(normalizePath(script))
wb_read <- function(name, digest, fmt, options=list()) {
  path <- file.path(base, name)
  hash <- system2("shasum", c("-a", "256", shQuote(path)), stdout=TRUE)
  if (length(hash) != 1L || substr(hash,1,64) != digest) stop(paste("SHA256 mismatch:", name))
  switch(fmt,
    csv=do.call(read.csv, c(list(file=path, check.names=FALSE, stringsAsFactors=FALSE, blank.lines.skip=FALSE, na.strings=c("", "NA")), options)),
    dta=as.data.frame(haven::read_dta(path)), sav=as.data.frame(haven::read_sav(path)), xlsx=openxlsx::read.xlsx(path, sheet=if(is.null(options$sheet)) 1 else options$sheet, check.names=FALSE, skipEmptyRows=FALSE, skipEmptyCols=FALSE),
    parquet=as.data.frame(arrow::read_parquet(path)), stop("Unsupported source format"))
}
wb_check <- function(actual, expected, absolute, relative, label) {
  if (length(actual)!=1 || !is.finite(actual) || abs(actual-expected)>absolute+relative*abs(expected))
    stop(paste(label, actual, "!=", expected))
}

data[["source_82b3c8c1d9e8aa2c806987d4"]] <- wb_read("source_1ce21051b81091ccc6d9f8b2.dta", "1ce21051b81091ccc6d9f8b22102b1560bc1b11924f2076b1e94db0b3b002e2f", "dta", list())
data[["step_76b2427e32344554a37924aa"]] <- data[["source_82b3c8c1d9e8aa2c806987d4"]]
checks[[1]] <- as.numeric(nrow(data[["step_76b2427e32344554a37924aa"]]))
stopifnot(identical(names(data[["step_76b2427e32344554a37924aa"]]), c("g", "x", "z", "keep", "y")))
data[["step_eca26cfbad39adff69c00721"]] <- data[["step_76b2427e32344554a37924aa"]]
data[["step_eca26cfbad39adff69c00721"]] <- data[["step_eca26cfbad39adff69c00721"]][which((!is.na(data[["step_eca26cfbad39adff69c00721"]][["keep"]]) & (data[["step_eca26cfbad39adff69c00721"]][["keep"]] == 1))), , drop=FALSE]
data[["step_eca26cfbad39adff69c00721"]] <- data[["step_eca26cfbad39adff69c00721"]][, c("g", "x", "z", "keep", "y"), drop=FALSE]
checks[[2]] <- as.numeric(nrow(data[["step_eca26cfbad39adff69c00721"]]))
stopifnot(identical(names(data[["step_eca26cfbad39adff69c00721"]]), c("g", "x", "z", "keep", "y")))
data[["step_226b4b10776b3612293e8e34"]] <- data[["step_eca26cfbad39adff69c00721"]]
stopifnot(is.numeric(data[["step_226b4b10776b3612293e8e34"]][["x"]]))
stopifnot(is.numeric(data[["step_226b4b10776b3612293e8e34"]][["z"]]))
data[["step_226b4b10776b3612293e8e34"]][["xz"]] <- (data[["step_226b4b10776b3612293e8e34"]][["x"]] * data[["step_226b4b10776b3612293e8e34"]][["z"]])
checks[[3]] <- as.numeric(nrow(data[["step_226b4b10776b3612293e8e34"]]))
stopifnot(identical(names(data[["step_226b4b10776b3612293e8e34"]]), c("g", "x", "z", "keep", "y", "xz")))
data[["step_5bb28f6498e4698e7347d1d5"]] <- data[["step_226b4b10776b3612293e8e34"]]
checks[[4]] <- as.numeric(nrow(data[["step_5bb28f6498e4698e7347d1d5"]]))
stopifnot(identical(names(data[["step_5bb28f6498e4698e7347d1d5"]]), c("g", "x", "z", "keep", "y", "xz")))
wb_model <- function(fit, covariance=vcov(fit), df=NULL, distribution="z", aliases=NULL, likelihood=TRUE) {
  beta <- coef(fit)
  names <- names(beta)
  if (!is.null(aliases)) names <- vapply(names, function(n) if (n %in% names(aliases)) aliases[[n]] else n, character(1))
  names <- gsub("`", "", names, fixed=TRUE)
  names[names=="(Intercept)"] <- "Intercept"
  names(beta) <- names
  se <- sqrt(diag(covariance)); names(se) <- names
  statistic <- beta/se
  p <- if (distribution=="t") 2*pt(-abs(statistic),df) else 2*pnorm(-abs(statistic))
  list(beta=beta,se=se,statistic=statistic,p=p,covariance=covariance,names=names,df=df,
       distribution=distribution,nobs=nobs(fit),fit=fit,loglik=if(likelihood) as.numeric(logLik(fit)) else NULL,link=if(is.null(fit$family$link)) "identity" else fit$family$link, design=model.matrix(fit),sample=rownames(model.frame(fit)))
}

wb_model_frame5 <- data[["step_5bb28f6498e4698e7347d1d5"]]
wb_aliases <- list()
wb_frame <- wb_model_frame5
wb_fit <- lm(`y` ~ `x` + `z` + `xz`, data=wb_frame)
wb_cov <- vcov(wb_fit)
wb_df <- df.residual(wb_fit)
wb_groups <- wb_frame[rownames(model.frame(wb_fit)), "g"]
wb_cov <- sandwich::vcovCL(wb_fit, cluster=wb_groups, type="HC1", cadjust=TRUE)
wb_df <- length(unique(wb_groups))-1
results[["step_59722572b3c11a55aa32ba09"]] <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)
checks[[5]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["beta"]][["Intercept"]])
checks[[6]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["beta"]][["x"]])
checks[[7]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["beta"]][["z"]])
checks[[8]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["beta"]][["xz"]])
checks[[9]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["se"]][["Intercept"]])
checks[[10]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["se"]][["x"]])
checks[[11]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["se"]][["z"]])
checks[[12]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["se"]][["xz"]])
checks[[13]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]]$nobs)
stopifnot(results[["step_59722572b3c11a55aa32ba09"]][["distribution"]] == "t")
checks[[14]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["statistic"]][["Intercept"]])
checks[[15]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["p"]][["Intercept"]])
checks[[16]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["df"]])
stopifnot(results[["step_59722572b3c11a55aa32ba09"]][["distribution"]] == "t")
checks[[17]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["statistic"]][["x"]])
checks[[18]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["p"]][["x"]])
checks[[19]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["df"]])
stopifnot(results[["step_59722572b3c11a55aa32ba09"]][["distribution"]] == "t")
checks[[20]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["statistic"]][["z"]])
checks[[21]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["p"]][["z"]])
checks[[22]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["df"]])
stopifnot(results[["step_59722572b3c11a55aa32ba09"]][["distribution"]] == "t")
checks[[23]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["statistic"]][["xz"]])
checks[[24]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["p"]][["xz"]])
checks[[25]] <- as.numeric(results[["step_59722572b3c11a55aa32ba09"]][["df"]])
wb_single <- function(model, estimate, se) {
  value <- estimate/se
  p <- if (model$distribution=="t") 2*pt(-abs(value),model$df) else 2*pnorm(-abs(value))
  list(value=value,p_value=p,df=model$df,df_denominator=NULL,distribution=model$distribution)
}
wb_wald <- function(model, R, target) {
  gap <- R %*% model$beta-target
  if (qr(R)$rank!=nrow(R)) stop("Dependent Wald restrictions")
  W <- as.numeric(t(gap) %*% solve(R %*% model$covariance %*% t(R),gap));q <- nrow(R)
  finite <- model$distribution=="t"; value <- if(finite) W/q else W
  denominator <- if(finite) model$df else NULL
  if(finite && identical(model$df_method,"design") && q>1) {
    denominator <- model$df-q+1
    if(denominator<=0) stop("Too few survey design degrees of freedom")
    value <- W*denominator/(model$df*q)
  }
  p <- if(finite) pf(value,q,denominator,lower.tail=FALSE) else pchisq(value,q,lower.tail=FALSE)
  list(beta=list(),se=list(),statistics=list(test=list(value=value,p_value=p,df=q,df_denominator=denominator,distribution=if(finite) "F" else "chi2")))
}
wb_lincom <- function(model, vector, constant) {
  estimate <- sum(vector*model$beta)+constant
  se <- sqrt(as.numeric(t(vector) %*% model$covariance %*% vector))
  list(beta=list(estimate=estimate),se=list(estimate=se),statistics=list(test=wb_single(model,estimate,se)))
}
wb_nlcom <- function(model, fn) {
  point <- model$beta;estimate <- fn(point)
  gradient <- vapply(seq_along(point),function(i) { h <- 6e-6*max(1,abs(point[i]));hi <- lo <- point;hi[i] <- hi[i]+h;lo[i] <- lo[i]-h;(fn(hi)-fn(lo))/(2*h) }, numeric(1))
  se <- sqrt(as.numeric(t(gradient) %*% model$covariance %*% gradient))
  list(beta=list(estimate=estimate),se=list(estimate=se),statistics=list(test=wb_single(model,estimate,se)))
}
wb_lr <- function(full,restricted) {
  if (is.null(full$loglik)||is.null(restricted$loglik)) stop("Likelihood unavailable")
  if (!identical(full$sample,restricted$sample)) stop("LR estimation samples differ")
  if (!all(restricted$names %in% full$names)||length(full$names)<=length(restricted$names)) stop("Models are not nested")
  value <- max(0,2*(full$loglik-restricted$loglik));df <- length(full$beta)-length(restricted$beta)
  list(beta=list(),se=list(),statistics=list(test=list(value=value,p_value=pchisq(value,df,lower.tail=FALSE),df=df,df_denominator=NULL,distribution="chi2")))
}
wb_links <- list(identity=function(eta) list(rep(1,length(eta)),rep(0,length(eta))),
  logit=function(eta) {p <- plogis(eta);list(p*(1-p),p*(1-p)*(1-2*p))},
  probit=function(eta) list(dnorm(eta),-eta*dnorm(eta)),log=function(eta) list(exp(eta),exp(eta)))
wb_margins <- function(model,variables,at) {
  X <- model$design;if (at=="means") X <- matrix(colMeans(X),nrow=1)
  beta <- model$beta;derivatives <- wb_links[[model$link]](as.numeric(X %*% beta))
  mean_first <- mean(derivatives[[1]]);curvature <- colMeans(derivatives[[2]]*X)
  estimates <- errors <- statistics <- list()
  for (name in variables) {
    j <- match(name,model$names);estimate <- mean_first*beta[j];gradient <- curvature*beta[j];gradient[j] <- gradient[j]+mean_first
    se <- sqrt(as.numeric(t(gradient) %*% model$covariance %*% gradient))
    estimates[[name]] <- estimate;errors[[name]] <- se;statistics[[name]] <- wb_single(model,estimate,se)
  }
  list(beta=estimates,se=errors,statistics=statistics,nobs=model$nobs)
}

wb_m <- results[["step_59722572b3c11a55aa32ba09"]]
wb_R <- matrix(0,nrow=2,ncol=length(wb_m$beta))
wb_R[1, match("x",wb_m$names)] <- 1.0
wb_R[2, match("xz",wb_m$names)] <- 1.0
results[["step_522468aadb113d7b603dca9b"]] <- wb_wald(wb_m, wb_R, c(0.0, 0.0))
results[["step_522468aadb113d7b603dca9b"]]$nobs <- results[["step_59722572b3c11a55aa32ba09"]]$nobs
checks[[26]] <- as.numeric(results[["step_522468aadb113d7b603dca9b"]]$nobs)
checks[[27]] <- as.numeric(results[["step_522468aadb113d7b603dca9b"]]$statistics[["test"]][["value"]])
checks[[28]] <- as.numeric(results[["step_522468aadb113d7b603dca9b"]]$statistics[["test"]][["p_value"]])
checks[[29]] <- as.numeric(results[["step_522468aadb113d7b603dca9b"]]$statistics[["test"]][["df"]])
checks[[30]] <- as.numeric(results[["step_522468aadb113d7b603dca9b"]]$statistics[["test"]][["df_denominator"]])
stopifnot(results[["step_522468aadb113d7b603dca9b"]]$statistics[["test"]]$distribution == "F")
writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 640, 0.0, 0.0, "step_76b2427e32344554a37924aa:nrows")
wb_check(checks[[2]], 320, 0.0, 0.0, "step_eca26cfbad39adff69c00721:nrows")
wb_check(checks[[3]], 320, 0.0, 0.0, "step_226b4b10776b3612293e8e34:nrows")
wb_check(checks[[4]], 320, 0.0, 0.0, "step_5bb28f6498e4698e7347d1d5:nrows")
wb_check(checks[[5]], 0.9675178036793878, 1e-08, 1e-06, "step_59722572b3c11a55aa32ba09:coefficients")
wb_check(checks[[6]], 0.587233907457428, 1e-08, 1e-06, "step_59722572b3c11a55aa32ba09:coefficients")
wb_check(checks[[7]], -0.1324647468019746, 1e-08, 1e-06, "step_59722572b3c11a55aa32ba09:coefficients")
wb_check(checks[[8]], 0.2877185211968429, 1e-08, 1e-06, "step_59722572b3c11a55aa32ba09:coefficients")
wb_check(checks[[9]], 0.06938744595036184, 1e-08, 1e-05, "step_59722572b3c11a55aa32ba09:std_errors")
wb_check(checks[[10]], 0.05939583283342683, 1e-08, 1e-05, "step_59722572b3c11a55aa32ba09:std_errors")
wb_check(checks[[11]], 0.05576371929506281, 1e-08, 1e-05, "step_59722572b3c11a55aa32ba09:std_errors")
wb_check(checks[[12]], 0.060837730532374686, 1e-08, 1e-05, "step_59722572b3c11a55aa32ba09:std_errors")
wb_check(checks[[13]], 320, 0.0, 0.0, "step_59722572b3c11a55aa32ba09:nobs")
wb_check(checks[[14]], 13.943701060441503, 1e-08, 1e-05, "step_59722572b3c11a55aa32ba09:statistics.value")
wb_check(checks[[15]], 1.974202786152289e-11, 1e-06, 0.0, "step_59722572b3c11a55aa32ba09:statistics.p_value")
wb_check(checks[[16]], 19.0, 0.0, 0.0, "step_59722572b3c11a55aa32ba09:statistics.df")
wb_check(checks[[17]], 9.886786318903908, 1e-08, 1e-05, "step_59722572b3c11a55aa32ba09:statistics.value")
wb_check(checks[[18]], 6.320519792921724e-09, 1e-06, 0.0, "step_59722572b3c11a55aa32ba09:statistics.p_value")
wb_check(checks[[19]], 19.0, 0.0, 0.0, "step_59722572b3c11a55aa32ba09:statistics.df")
wb_check(checks[[20]], -2.375464701360096, 1e-08, 1e-05, "step_59722572b3c11a55aa32ba09:statistics.value")
wb_check(checks[[21]], 0.028205935498091514, 1e-06, 0.0, "step_59722572b3c11a55aa32ba09:statistics.p_value")
wb_check(checks[[22]], 19.0, 0.0, 0.0, "step_59722572b3c11a55aa32ba09:statistics.df")
wb_check(checks[[23]], 4.729277681450231, 1e-08, 1e-05, "step_59722572b3c11a55aa32ba09:statistics.value")
wb_check(checks[[24]], 0.00014595711024510102, 1e-06, 0.0, "step_59722572b3c11a55aa32ba09:statistics.p_value")
wb_check(checks[[25]], 19.0, 0.0, 0.0, "step_59722572b3c11a55aa32ba09:statistics.df")
wb_check(checks[[26]], 320, 0.0, 0.0, "step_522468aadb113d7b603dca9b:nobs")
wb_check(checks[[27]], 69.64771978987594, 1e-08, 1e-05, "step_522468aadb113d7b603dca9b:statistics.value")
wb_check(checks[[28]], 1.7914693344639517e-09, 1e-06, 0.0, "step_522468aadb113d7b603dca9b:statistics.p_value")
wb_check(checks[[29]], 2, 0.0, 0.0, "step_522468aadb113d7b603dca9b:statistics.df")
wb_check(checks[[30]], 19.0, 0.0, 0.0, "step_522468aadb113d7b603dca9b:statistics.df_denominator")
