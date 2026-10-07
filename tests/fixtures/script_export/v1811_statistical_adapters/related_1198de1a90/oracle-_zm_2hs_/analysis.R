# Workbench 1.8.11
# project: model-oracle
# run: glm_binomial
# lineage_hash: 1111111111111111111111111111111111111111111111111111111111111111
# Coverage
# model | model.glm | native | 
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
wb_fit <- glm(`binary` ~ `x` + `z`, data=wb_model_frame1, family=binomial(link="logit"), control=glm.control(epsilon=1e-12,maxit=100))
results[["model"]] <- wb_model(wb_fit, aliases=wb_aliases)
checks[[1]] <- as.numeric(results[["model"]][["beta"]][["Intercept"]])
checks[[2]] <- as.numeric(results[["model"]][["beta"]][["x"]])
checks[[3]] <- as.numeric(results[["model"]][["beta"]][["z"]])
checks[[4]] <- as.numeric(results[["model"]][["se"]][["Intercept"]])
checks[[5]] <- as.numeric(results[["model"]][["se"]][["x"]])
checks[[6]] <- as.numeric(results[["model"]][["se"]][["z"]])
checks[[7]] <- as.numeric(results[["model"]]$nobs)
stopifnot(results[["model"]][["distribution"]] == "z")
checks[[8]] <- as.numeric(results[["model"]][["statistic"]][["Intercept"]])
checks[[9]] <- as.numeric(results[["model"]][["p"]][["Intercept"]])
stopifnot(results[["model"]][["distribution"]] == "z")
checks[[10]] <- as.numeric(results[["model"]][["statistic"]][["x"]])
checks[[11]] <- as.numeric(results[["model"]][["p"]][["x"]])
stopifnot(results[["model"]][["distribution"]] == "z")
checks[[12]] <- as.numeric(results[["model"]][["statistic"]][["z"]])
checks[[13]] <- as.numeric(results[["model"]][["p"]][["z"]])
writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 0.21223972211737696, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[2]], 0.5621638375809234, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[3]], -0.2332565315867904, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[4]], 0.1120064519941844, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[5]], 0.11722060171045612, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[6]], 0.1200130109187133, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[7]], 350, 0.0, 0.0, "model:nobs")
wb_check(checks[[8]], 1.8948883598990967, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[9]], 0.0581071936076671, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[10]], 4.795776760893202, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[11]], 1.6204566658066975e-06, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[12]], -1.9435936970598857, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[13]], 0.051944466503299425, 1e-06, 0.0, "model:statistics.p_value")
