# Workbench 1.8.11
# project: fpc
# run: no_strata
# lineage_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
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

data[["source"]] <- wb_read("data.csv", "69319f501a76a1d01e5a8766c10155314622de5ec7d32a9cf7375bccb26f53fd", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
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
options(survey.lonely.psu="fail")
wb_fpc <- wb_frame[["unstratified_fpc"]]
stopifnot(is.numeric(wb_fpc),!is.logical(wb_fpc),length(wb_fpc)>0,all(is.finite(wb_fpc)),all(wb_fpc>=0))
wb_fpc_fraction <- all(wb_fpc<=1)
if (!wb_fpc_fraction) stopifnot(all(wb_fpc>1),all(wb_fpc==floor(wb_fpc)))
wb_fpc_groups <- split(seq_len(nrow(wb_frame)),rep("all",nrow(wb_frame)))
wb_fpc_units <- wb_frame[["psu"]]
for (wb_rows in wb_fpc_groups) {
  stopifnot(length(unique(wb_fpc[wb_rows]))==1)
  if (!wb_fpc_fraction) stopifnot(wb_fpc[wb_rows[1]]>=length(unique(wb_fpc_units[wb_rows])))
}
wb_design <- survey::svydesign(ids=~psu, weights=~weight, fpc=~unstratified_fpc, data=wb_frame, nest=TRUE)
wb_design_df <- survey::degf(wb_design)
wb_fit <- survey::svyglm(`y` ~ `x1` + `x2`, design=wb_design, family=gaussian())
wb_df <- wb_design_df
results[["model"]] <- wb_model(wb_fit,vcov(wb_fit),wb_df,"t",wb_aliases,likelihood=FALSE)
results[["model"]]$nobs <- nrow(wb_frame)
results[["model"]]$loglik <- NULL
results[["model"]]$df_method <- "design"
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
wb_check(checks[[1]], 4.652711573943111, 1e-08, 0, "model:coefficients")
wb_check(checks[[2]], 1.475820771771979, 1e-08, 0, "model:coefficients")
wb_check(checks[[3]], -0.40404481777033774, 1e-08, 0, "model:coefficients")
wb_check(checks[[4]], 0.9580953190762684, 1e-06, 0, "model:std_errors")
wb_check(checks[[5]], 0.11055666171669695, 1e-06, 0, "model:std_errors")
wb_check(checks[[6]], 0.06528488750127452, 1e-06, 0, "model:std_errors")
wb_check(checks[[7]], 80, 0.0, 0.0, "model:nobs")
wb_check(checks[[8]], 4.85620948281946, 1e-08, 1e-06, "model:statistics.value")
wb_check(checks[[9]], 0.00020951272720788543, 0, 1e-05, "model:statistics.p_value")
wb_check(checks[[10]], 15, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[11]], 13.348999045881026, 1e-08, 1e-06, "model:statistics.value")
wb_check(checks[[12]], 9.949156333710864e-10, 0, 1e-05, "model:statistics.p_value")
wb_check(checks[[13]], 15, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[14]], -6.188948671504562, 1e-08, 1e-06, "model:statistics.value")
wb_check(checks[[15]], 1.7334890679809512e-05, 0, 1e-05, "model:statistics.p_value")
wb_check(checks[[16]], 15, 0.0, 0.0, "model:statistics.df")
