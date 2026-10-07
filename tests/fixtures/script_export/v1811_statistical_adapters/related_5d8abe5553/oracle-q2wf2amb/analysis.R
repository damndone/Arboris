# Workbench 1.8.11
# project: survey
# run: native
# lineage_hash: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
# Coverage
# model | model.ols | native_with_equivalence_note | Full single-stage linearization design including supplied FPC and domain; coefficient and joint-test df preserve the executed Workbench convention.
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

data[["source"]] <- wb_read("data.csv", "eacb266ef543aef43a8488e410bf7c172241d6af18761eefb4d9494b4bcd5630", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
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
wb_frame <- wb_model_frame1[complete.cases(wb_model_frame1[, c("y", "x1", "x2"),drop=FALSE]),,drop=FALSE]
options(survey.lonely.psu="average")
wb_design <- survey::svydesign(ids=~psu, strata=~stratum, weights=~weight, data=wb_frame, nest=TRUE)
wb_design_df <- survey::degf(wb_design)
wb_fit <- survey::svyglm(`y` ~ `x1` + `x2`, design=wb_design, family=gaussian())
wb_df <- wb_design_df - length(coef(wb_fit)) + 1
results[["model"]] <- wb_model(wb_fit,vcov(wb_fit),wb_df,"t",wb_aliases,likelihood=FALSE)
results[["model"]]$nobs <- nrow(wb_frame)
results[["model"]]$loglik <- NULL
results[["model"]]$df_method <- "design_minus_p"
checks[[1]] <- as.numeric(results[["model"]][["beta"]][["Intercept"]])
checks[[2]] <- as.numeric(results[["model"]][["beta"]][["x1"]])
checks[[3]] <- as.numeric(results[["model"]][["beta"]][["x2"]])
checks[[4]] <- as.numeric(results[["model"]][["se"]][["Intercept"]])
checks[[5]] <- as.numeric(results[["model"]][["se"]][["x1"]])
checks[[6]] <- as.numeric(results[["model"]][["se"]][["x2"]])
checks[[7]] <- as.numeric(results[["model"]]$nobs)
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[8]] <- as.numeric(results[["model"]][["statistic"]][["Intercept"]])
checks[[9]] <- as.numeric(results[["model"]][["p"]][["Intercept"]])
checks[[10]] <- as.numeric(results[["model"]][["df"]])
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[11]] <- as.numeric(results[["model"]][["statistic"]][["x1"]])
checks[[12]] <- as.numeric(results[["model"]][["p"]][["x1"]])
checks[[13]] <- as.numeric(results[["model"]][["df"]])
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[14]] <- as.numeric(results[["model"]][["statistic"]][["x2"]])
checks[[15]] <- as.numeric(results[["model"]][["p"]][["x2"]])
checks[[16]] <- as.numeric(results[["model"]][["df"]])
writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 4.767273406190223, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[2]], 1.4497508730782993, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[3]], -0.3932150269716552, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[4]], 1.9181699566528825, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[5]], 0.22676508126636166, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[6]], 0.08998008468090576, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[7]], 75, 0.0, 0.0, "model:nobs")
wb_check(checks[[8]], 2.4853237793948635, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[9]], 0.055477941548960685, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[10]], 5, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[11]], 6.393183928417093, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[12]], 0.0013871321631685222, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[13]], 5, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[14]], -4.370022859681721, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[15]], 0.007221909379973519, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[16]], 5, 0.0, 0.0, "model:statistics.df")
