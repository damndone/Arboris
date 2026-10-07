# Workbench 1.8.11
# project: review
# run: branch-isolation
# lineage_hash: 1111111111111111111111111111111111111111111111111111111111111111
# Coverage
# categorical | model.ols | native | 
# continuous | model.ols | native | 
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
    dta=haven::read_dta(path), sav=haven::read_sav(path), xlsx=readxl::read_excel(path),
    parquet=as.data.frame(arrow::read_parquet(path)), stop("Unsupported source format"))
}
wb_check <- function(actual, expected, absolute, relative, label) {
  if (length(actual)!=1 || !is.finite(actual) || abs(actual-expected)>absolute+relative*abs(expected))
    stop(paste(label, actual, "!=", expected))
}

data[["source"]] <- wb_read("data.csv", "0bea4e0503803b2c2abcc213d13f39d8a90afd7d4e346aa1ae854bcbae99482f", "csv", list())
wb_model <- function(fit, covariance=vcov(fit), df=NULL, distribution="z", aliases=NULL) {
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
       distribution=distribution,nobs=nobs(fit),fit=fit,loglik=as.numeric(logLik(fit)),link=if(is.null(fit$family$link)) "identity" else fit$family$link, design=model.matrix(fit),sample=rownames(model.frame(fit)))
}

wb_aliases <- list("category2"="C(Q('category'))[T.2]", "category3"="C(Q('category'))[T.3]")
data[["source"]][["category"]] <- factor(data[["source"]][["category"]], levels=sort(unique(data[["source"]][["category"]])))
wb_frame <- data[["source"]]
wb_fit <- lm(`y` ~ `x` + `category`, data=wb_frame)
wb_cov <- vcov(wb_fit)
wb_df <- df.residual(wb_fit)
results[["categorical"]] <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)
checks[[1]] <- as.numeric(results[["categorical"]][["beta"]][["Intercept"]])
checks[[2]] <- as.numeric(results[["categorical"]][["beta"]][["C(Q('category'))[T.2]"]])
checks[[3]] <- as.numeric(results[["categorical"]][["beta"]][["C(Q('category'))[T.3]"]])
checks[[4]] <- as.numeric(results[["categorical"]][["beta"]][["x"]])
checks[[5]] <- as.numeric(results[["categorical"]][["se"]][["Intercept"]])
checks[[6]] <- as.numeric(results[["categorical"]][["se"]][["C(Q('category'))[T.2]"]])
checks[[7]] <- as.numeric(results[["categorical"]][["se"]][["C(Q('category'))[T.3]"]])
checks[[8]] <- as.numeric(results[["categorical"]][["se"]][["x"]])
checks[[9]] <- as.numeric(results[["categorical"]]$nobs)
stopifnot(results[["categorical"]][["distribution"]] == "t")
checks[[10]] <- as.numeric(results[["categorical"]][["statistic"]][["Intercept"]])
checks[[11]] <- as.numeric(results[["categorical"]][["p"]][["Intercept"]])
checks[[12]] <- as.numeric(results[["categorical"]][["df"]])
stopifnot(results[["categorical"]][["distribution"]] == "t")
checks[[13]] <- as.numeric(results[["categorical"]][["statistic"]][["C(Q('category'))[T.2]"]])
checks[[14]] <- as.numeric(results[["categorical"]][["p"]][["C(Q('category'))[T.2]"]])
checks[[15]] <- as.numeric(results[["categorical"]][["df"]])
stopifnot(results[["categorical"]][["distribution"]] == "t")
checks[[16]] <- as.numeric(results[["categorical"]][["statistic"]][["C(Q('category'))[T.3]"]])
checks[[17]] <- as.numeric(results[["categorical"]][["p"]][["C(Q('category'))[T.3]"]])
checks[[18]] <- as.numeric(results[["categorical"]][["df"]])
stopifnot(results[["categorical"]][["distribution"]] == "t")
checks[[19]] <- as.numeric(results[["categorical"]][["statistic"]][["x"]])
checks[[20]] <- as.numeric(results[["categorical"]][["p"]][["x"]])
checks[[21]] <- as.numeric(results[["categorical"]][["df"]])
wb_aliases <- list()
wb_frame <- data[["source"]]
wb_fit <- lm(`y` ~ `x` + `category`, data=wb_frame)
wb_cov <- vcov(wb_fit)
wb_df <- df.residual(wb_fit)
results[["continuous"]] <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)
checks[[22]] <- as.numeric(results[["continuous"]][["beta"]][["Intercept"]])
checks[[23]] <- as.numeric(results[["continuous"]][["beta"]][["x"]])
checks[[24]] <- as.numeric(results[["continuous"]][["beta"]][["category"]])
checks[[25]] <- as.numeric(results[["continuous"]][["se"]][["Intercept"]])
checks[[26]] <- as.numeric(results[["continuous"]][["se"]][["x"]])
checks[[27]] <- as.numeric(results[["continuous"]][["se"]][["category"]])
checks[[28]] <- as.numeric(results[["continuous"]]$nobs)
stopifnot(results[["continuous"]][["distribution"]] == "t")
checks[[29]] <- as.numeric(results[["continuous"]][["statistic"]][["Intercept"]])
checks[[30]] <- as.numeric(results[["continuous"]][["p"]][["Intercept"]])
checks[[31]] <- as.numeric(results[["continuous"]][["df"]])
stopifnot(results[["continuous"]][["distribution"]] == "t")
checks[[32]] <- as.numeric(results[["continuous"]][["statistic"]][["x"]])
checks[[33]] <- as.numeric(results[["continuous"]][["p"]][["x"]])
checks[[34]] <- as.numeric(results[["continuous"]][["df"]])
stopifnot(results[["continuous"]][["distribution"]] == "t")
checks[[35]] <- as.numeric(results[["continuous"]][["statistic"]][["category"]])
checks[[36]] <- as.numeric(results[["continuous"]][["p"]][["category"]])
checks[[37]] <- as.numeric(results[["continuous"]][["df"]])
writeLines(sprintf("%.17g",unlist(checks)),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 1.2708994017897324, 1e-08, 1e-06, "categorical:coefficients")
wb_check(checks[[2]], 0.7035527108942035, 1e-08, 1e-06, "categorical:coefficients")
wb_check(checks[[3]], 1.5708783411633434, 1e-08, 1e-06, "categorical:coefficients")
wb_check(checks[[4]], 0.3286601725683639, 1e-08, 1e-06, "categorical:coefficients")
wb_check(checks[[5]], 0.10937400678256705, 1e-08, 1e-05, "categorical:std_errors")
wb_check(checks[[6]], 0.1563678541895355, 1e-08, 1e-05, "categorical:std_errors")
wb_check(checks[[7]], 0.1535480729297494, 1e-08, 1e-05, "categorical:std_errors")
wb_check(checks[[8]], 0.0642479068074436, 1e-08, 1e-05, "categorical:std_errors")
wb_check(checks[[9]], 240, 0.0, 0.0, "categorical:nobs")
wb_check(checks[[10]], 11.619757190721288, 1e-08, 1e-05, "categorical:statistics.value")
wb_check(checks[[11]], 5.575649993018833e-25, 1e-06, 0.0, "categorical:statistics.p_value")
wb_check(checks[[12]], 236.0, 0.0, 0.0, "categorical:statistics.df")
wb_check(checks[[13]], 4.499343644131729, 1e-08, 1e-05, "categorical:statistics.value")
wb_check(checks[[14]], 1.070297878290555e-05, 1e-06, 0.0, "categorical:statistics.p_value")
wb_check(checks[[15]], 236.0, 0.0, 0.0, "categorical:statistics.df")
wb_check(checks[[16]], 10.230531137190138, 1e-08, 1e-05, "categorical:statistics.value")
wb_check(checks[[17]], 1.4335782806912002e-20, 1e-06, 0.0, "categorical:statistics.p_value")
wb_check(checks[[18]], 236.0, 0.0, 0.0, "categorical:statistics.df")
wb_check(checks[[19]], 5.115500082413364, 1e-08, 1e-05, "categorical:statistics.value")
wb_check(checks[[20]], 6.477886934670725e-07, 1e-06, 0.0, "categorical:statistics.p_value")
wb_check(checks[[21]], 236.0, 0.0, 0.0, "categorical:statistics.df")
wb_check(checks[[22]], 0.4566572648686139, 1e-08, 1e-06, "continuous:coefficients")
wb_check(checks[[23]], 0.33613214971634603, 1e-08, 1e-06, "continuous:coefficients")
wb_check(checks[[24]], 0.7861311171736707, 1e-08, 1e-06, "continuous:coefficients")
wb_check(checks[[25]], 0.1656192709774661, 1e-08, 1e-05, "continuous:std_errors")
wb_check(checks[[26]], 0.06297017907816094, 1e-08, 1e-05, "continuous:std_errors")
wb_check(checks[[27]], 0.07666303913940116, 1e-08, 1e-05, "continuous:std_errors")
wb_check(checks[[28]], 240, 0.0, 0.0, "continuous:nobs")
wb_check(checks[[29]], 2.757271313739486, 1e-08, 1e-05, "continuous:statistics.value")
wb_check(checks[[30]], 0.006282536599842314, 1e-06, 0.0, "continuous:statistics.p_value")
wb_check(checks[[31]], 237.0, 0.0, 0.0, "continuous:statistics.df")
wb_check(checks[[32]], 5.337957659277517, 1e-08, 1e-05, "continuous:statistics.value")
wb_check(checks[[33]], 2.1978864882588204e-07, 1e-06, 0.0, "continuous:statistics.p_value")
wb_check(checks[[34]], 237.0, 0.0, 0.0, "continuous:statistics.df")
wb_check(checks[[35]], 10.254369328408696, 1e-08, 1e-05, "continuous:statistics.value")
wb_check(checks[[36]], 1.1722180535591328e-20, 1e-06, 0.0, "continuous:statistics.p_value")
wb_check(checks[[37]], 237.0, 0.0, 0.0, "continuous:statistics.df")


