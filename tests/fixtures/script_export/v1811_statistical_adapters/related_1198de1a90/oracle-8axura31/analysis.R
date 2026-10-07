# Workbench 1.8.11
# project: weighted
# run: analysis_robust
# lineage_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
# Coverage
# weighted | model.ols | native | 
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

data[["source"]] <- wb_read("data.csv", "0f643fba418a92bc7a08befa218425056e866314340e1148775107241af4e143", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
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
wb_fit <- lm(`y` ~ `x` + `z`, data=wb_frame, weights=wb_frame[["aw"]])
wb_cov <- vcov(wb_fit)
wb_df <- df.residual(wb_fit)
wb_cov <- sandwich::vcovHC(wb_fit, type="HC1")
results[["weighted"]] <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)
checks[[1]] <- as.numeric(results[["weighted"]][["beta"]][["Intercept"]])
checks[[2]] <- as.numeric(results[["weighted"]][["beta"]][["x"]])
checks[[3]] <- as.numeric(results[["weighted"]][["beta"]][["z"]])
checks[[4]] <- as.numeric(results[["weighted"]][["se"]][["Intercept"]])
checks[[5]] <- as.numeric(results[["weighted"]][["se"]][["x"]])
checks[[6]] <- as.numeric(results[["weighted"]][["se"]][["z"]])
checks[[7]] <- as.numeric(results[["weighted"]]$nobs)
stopifnot(results[["weighted"]][["distribution"]] == "t")
checks[[8]] <- as.numeric(results[["weighted"]][["statistic"]][["Intercept"]])
checks[[9]] <- as.numeric(results[["weighted"]][["p"]][["Intercept"]])
checks[[10]] <- as.numeric(results[["weighted"]][["df"]])
stopifnot(results[["weighted"]][["distribution"]] == "t")
checks[[11]] <- as.numeric(results[["weighted"]][["statistic"]][["x"]])
checks[[12]] <- as.numeric(results[["weighted"]][["p"]][["x"]])
checks[[13]] <- as.numeric(results[["weighted"]][["df"]])
stopifnot(results[["weighted"]][["distribution"]] == "t")
checks[[14]] <- as.numeric(results[["weighted"]][["statistic"]][["z"]])
checks[[15]] <- as.numeric(results[["weighted"]][["p"]][["z"]])
checks[[16]] <- as.numeric(results[["weighted"]][["df"]])
writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 1.085282749557345, 1e-08, 1e-06, "weighted:coefficients")
wb_check(checks[[2]], 0.6071313851092202, 1e-08, 1e-06, "weighted:coefficients")
wb_check(checks[[3]], -0.2043614817840667, 1e-08, 1e-06, "weighted:coefficients")
wb_check(checks[[4]], 0.05381710188201347, 1e-08, 1e-05, "weighted:std_errors")
wb_check(checks[[5]], 0.047990782329352236, 1e-08, 1e-05, "weighted:std_errors")
wb_check(checks[[6]], 0.05265012682205399, 1e-08, 1e-05, "weighted:std_errors")
wb_check(checks[[7]], 350, 0.0, 0.0, "weighted:nobs")
wb_check(checks[[8]], 20.166131426710358, 1e-08, 1e-05, "weighted:statistics.value")
wb_check(checks[[9]], 2.0907927325230813e-60, 1e-06, 0.0, "weighted:statistics.p_value")
wb_check(checks[[10]], 347.0, 0.0, 0.0, "weighted:statistics.df")
wb_check(checks[[11]], 12.650999955420295, 1e-08, 1e-05, "weighted:statistics.value")
wb_check(checks[[12]], 1.9970260538258507e-30, 1e-06, 0.0, "weighted:statistics.p_value")
wb_check(checks[[13]], 347.0, 0.0, 0.0, "weighted:statistics.df")
wb_check(checks[[14]], -3.8815002758638015, 1e-08, 1e-05, "weighted:statistics.value")
wb_check(checks[[15]], 0.00012425511795765678, 1e-06, 0.0, "weighted:statistics.p_value")
wb_check(checks[[16]], 347.0, 0.0, 0.0, "weighted:statistics.df")
