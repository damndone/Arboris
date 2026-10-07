# Workbench 1.8.11
# project: review
# run: numeric-unit
# lineage_hash: 3333333333333333333333333333333333333333333333333333333333333333
# Coverage
# model | model.ols | native | 
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
    dta=haven::read_dta(path), sav=haven::read_sav(path), xlsx=openxlsx::read.xlsx(path, sheet=if(is.null(options$sheet)) 1 else options$sheet, check.names=FALSE, skipEmptyRows=FALSE, skipEmptyCols=FALSE),
    parquet=as.data.frame(arrow::read_parquet(path)), stop("Unsupported source format"))
}
wb_check <- function(actual, expected, absolute, relative, label) {
  if (length(actual)!=1 || !is.finite(actual) || abs(actual-expected)>absolute+relative*abs(expected))
    stop(paste(label, actual, "!=", expected))
}

data[["source"]] <- wb_read("data.csv", "0bea4e0503803b2c2abcc213d13f39d8a90afd7d4e346aa1ae854bcbae99482f", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
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

wb_model_frame1 <- data[["source"]]
wb_aliases <- list()
wb_frame <- wb_model_frame1
wb_frame <- wb_frame[order(wb_frame[["time"]]),,drop=FALSE]
wb_fit <- lm(`y` ~ `x`, data=wb_frame)
wb_cov <- vcov(wb_fit)
wb_df <- df.residual(wb_fit)
wb_cov <- sandwich::NeweyWest(wb_fit, lag=2, prewhite=FALSE, adjust=TRUE)
results[["model"]] <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)
checks[[1]] <- as.numeric(results[["model"]][["beta"]][["Intercept"]])
checks[[2]] <- as.numeric(results[["model"]][["beta"]][["x"]])
checks[[3]] <- as.numeric(results[["model"]][["se"]][["Intercept"]])
checks[[4]] <- as.numeric(results[["model"]][["se"]][["x"]])
checks[[5]] <- as.numeric(results[["model"]]$nobs)
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[6]] <- as.numeric(results[["model"]][["statistic"]][["Intercept"]])
checks[[7]] <- as.numeric(results[["model"]][["p"]][["Intercept"]])
checks[[8]] <- as.numeric(results[["model"]][["df"]])
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[9]] <- as.numeric(results[["model"]][["statistic"]][["x"]])
checks[[10]] <- as.numeric(results[["model"]][["p"]][["x"]])
checks[[11]] <- as.numeric(results[["model"]][["df"]])
writeLines(sprintf("%.17g",unlist(checks)),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 2.029731891227981, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[2]], 0.2870153773878842, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[3]], 0.06617361483917072, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[4]], 0.07147968356724231, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[5]], 240, 0.0, 0.0, "model:nobs")
wb_check(checks[[6]], 30.672827775255588, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[7]], 1.1803518241590357e-84, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[8]], 238.0, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[9]], 4.015342025372613, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[10]], 7.959985423803175e-05, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[11]], 238.0, 0.0, 0.0, "model:statistics.df")


