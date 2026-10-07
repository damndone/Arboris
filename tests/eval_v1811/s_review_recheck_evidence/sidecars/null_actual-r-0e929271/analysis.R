# Workbench 1.8.11
# project: sidecar
# run: executed
# lineage_hash: ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
# Coverage
# completed | model.ols | snapshot | FPC is supplied, but the frozen Workbench linearization engine does not apply FPC; native FPC would change the executed covariance. Workbench completed this step; numeric values come from a verified result sidecar, without native re-estimation.
# post | postestimation.wald | snapshot | Dependent post-estimation needs its own completed Workbench result sidecar; no fitted state is reconstructed. Workbench completed this step; numeric values come from a verified result sidecar, without native re-estimation.
# selected | data.subset | native | 
# independent | model.ols | native | 
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

data[["source"]] <- wb_read("data.csv", "5f8d0cc66fc9efdfd08e6a06640ea410d58671fe93ac5cac2ad90d6aa68de937", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
# Workbench completed this step: Sampling OLS completed in Workbench
data[["completed"]] <- wb_read("completed.csv", "5f8d0cc66fc9efdfd08e6a06640ea410d58671fe93ac5cac2ad90d6aa68de937", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
checks[[1]] <- as.numeric(nrow(data[["completed"]]))
stopifnot(identical(names(data[["completed"]]), c("stratum", "psu", "y", "x1", "x2", "weight", "fpc", "subpop")))
wb_result_bridge <- tempfile(fileext=".py")
writeLines("import base64\nimport json\nimport os\nfrom pathlib import Path\nimport sys\nfrom workbench.contracts.common.envelope import thaw_json\nfrom workbench.script_export.result_snapshot import ResultSnapshotRef, read_result_snapshot\n\nconfiguration = json.loads(base64.b64decode(sys.argv[2]))\nreference = ResultSnapshotRef(**configuration['reference'])\nvalues = read_result_snapshot(Path(sys.argv[1]), reference, expected_binding=configuration['binding'])\nfor name, distribution in configuration['distributions'].items():\n    if values['statistics'][name]['distribution'] != distribution:\n        raise AssertionError('Result sidecar reference distribution differs')\nif sys.argv[3] == 'r':\n    print(json.dumps(thaw_json(values), ensure_ascii=False, allow_nan=False))\nelif sys.argv[3] == 'stata':\n    lines = []\n    for index, path in enumerate(configuration['queries']):\n        value = values\n        for key in path:\n            value = value[key]\n        if value is not None and type(value) not in (int, float):\n            raise AssertionError('Result sidecar query is not numeric')\n        token = '.' if value is None else repr(value)\n        lines.append('scalar wb_result_' + str(configuration['index']) + '_' + str(index) + ' = ' + token)\n    lines.append('scalar wb_result_valid_' + str(configuration['index']) + ' = 1')\n    fd = os.open(sys.argv[4], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)\n    with os.fdopen(fd, 'w', encoding='utf-8') as handle:\n        handle.write('\\n'.join(lines) + '\\n')\nelse:\n    raise AssertionError('Unsupported result bridge mode')\n",wb_result_bridge,useBytes=TRUE)
wb_result_json <- system2("python3",c(shQuote(wb_result_bridge),shQuote(base),"eyJyZWZlcmVuY2UiOiB7ImZpbGVuYW1lIjogImNvbXBsZXRlZF9yZXN1bHQuanNvbiIsICJzaGEyNTYiOiAiMmViYjlhYjdmYWFkZGVmM2ExYTFjNGEzMDc0Zjg2MWUxZDUxYTBlYjgwMjBlNDU1ODQzMTJlMzZiMzEwMGQ1NCIsICJzY2hlbWFfdmVyc2lvbiI6IDF9LCAiYmluZGluZyI6IHsicHJvamVjdF9pZCI6ICJzaWRlY2FyIiwgInJ1bl9pZCI6ICJleGVjdXRlZCIsICJsaW5lYWdlX2hhc2giOiAiZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZiIsICJzdGVwX2lkIjogImNvbXBsZXRlZCIsICJraW5kIjogIm1vZGVsIiwgIm9wZXJhdGlvbiI6ICJtb2RlbC5vbHMiLCAicGFyYW1ldGVyc19zaGEyNTYiOiAiYWM1ZDZiMzc1YWRhOTIwYTBmM2MyZDI5NzFmM2I4ZTk5NTA0YWYwN2ExMjY0MTE1MjUwYzA1NDg0N2FiNmZiMiIsICJpbnB1dHMiOiBbInNvdXJjZSJdLCAibW9kZWxzIjogW119LCAicXVlcmllcyI6IFtbIm5vYnMiXSwgWyJjb2VmZmljaWVudHMiLCAiSW50ZXJjZXB0Il0sIFsiY29lZmZpY2llbnRzIiwgIngxIl0sIFsiY29lZmZpY2llbnRzIiwgIngyIl0sIFsic3RkX2Vycm9ycyIsICJJbnRlcmNlcHQiXSwgWyJzdGRfZXJyb3JzIiwgIngxIl0sIFsic3RkX2Vycm9ycyIsICJ4MiJdLCBbInN0YXRpc3RpY3MiLCAiSW50ZXJjZXB0IiwgInZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJJbnRlcmNlcHQiLCAiZGYiXSwgWyJzdGF0aXN0aWNzIiwgIkludGVyY2VwdCIsICJwX3ZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJ4MSIsICJ2YWx1ZSJdLCBbInN0YXRpc3RpY3MiLCAieDEiLCAiZGYiXSwgWyJzdGF0aXN0aWNzIiwgIngxIiwgInBfdmFsdWUiXSwgWyJzdGF0aXN0aWNzIiwgIngyIiwgInZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJ4MiIsICJkZiJdLCBbInN0YXRpc3RpY3MiLCAieDIiLCAicF92YWx1ZSJdXSwgImRpc3RyaWJ1dGlvbnMiOiB7IkludGVyY2VwdCI6ICJ0IiwgIngxIjogInQiLCAieDIiOiAidCJ9LCAiaW5kZXgiOiAxfQ==","r"),stdout=TRUE,stderr=TRUE)
if (!is.null(attr(wb_result_json,"status")) && attr(wb_result_json,"status")!=0) stop(paste(wb_result_json,collapse="\n"))
wb_result_values1 <- jsonlite::fromJSON(paste(wb_result_json,collapse="\n"),simplifyVector=FALSE)
checks[[2]] <- as.numeric(wb_result_values1[["nobs"]])
checks[[3]] <- as.numeric(wb_result_values1[["coefficients"]][["Intercept"]])
checks[[4]] <- as.numeric(wb_result_values1[["coefficients"]][["x1"]])
checks[[5]] <- as.numeric(wb_result_values1[["coefficients"]][["x2"]])
checks[[6]] <- as.numeric(wb_result_values1[["std_errors"]][["Intercept"]])
checks[[7]] <- as.numeric(wb_result_values1[["std_errors"]][["x1"]])
checks[[8]] <- as.numeric(wb_result_values1[["std_errors"]][["x2"]])
checks[[9]] <- as.numeric(wb_result_values1[["statistics"]][["Intercept"]][["value"]])
checks[[10]] <- as.numeric(wb_result_values1[["statistics"]][["Intercept"]][["df"]])
checks[[11]] <- as.numeric(wb_result_values1[["statistics"]][["Intercept"]][["p_value"]])
checks[[12]] <- as.numeric(wb_result_values1[["statistics"]][["x1"]][["value"]])
checks[[13]] <- as.numeric(wb_result_values1[["statistics"]][["x1"]][["df"]])
checks[[14]] <- as.numeric(wb_result_values1[["statistics"]][["x1"]][["p_value"]])
checks[[15]] <- as.numeric(wb_result_values1[["statistics"]][["x2"]][["value"]])
checks[[16]] <- as.numeric(wb_result_values1[["statistics"]][["x2"]][["df"]])
checks[[17]] <- as.numeric(wb_result_values1[["statistics"]][["x2"]][["p_value"]])
# Workbench completed this step: Actual persisted design Wald
data[["post"]] <- data[["completed"]]
wb_result_json <- system2("python3",c(shQuote(wb_result_bridge),shQuote(base),"eyJyZWZlcmVuY2UiOiB7ImZpbGVuYW1lIjogInBvc3RfcmVzdWx0Lmpzb24iLCAic2hhMjU2IjogIjFjNzkyZmI3YjljOTg1YmI3NWVlODg2ZGQ5Yjg3NGYxZDcwOTFkMjk4YmI0Njc4YmZiMjA5MmQwZjAxMmJhZDIiLCAic2NoZW1hX3ZlcnNpb24iOiAxfSwgImJpbmRpbmciOiB7InByb2plY3RfaWQiOiAic2lkZWNhciIsICJydW5faWQiOiAiZXhlY3V0ZWQiLCAibGluZWFnZV9oYXNoIjogImZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmYiLCAic3RlcF9pZCI6ICJwb3N0IiwgImtpbmQiOiAicG9zdGVzdGltYXRpb24iLCAib3BlcmF0aW9uIjogInBvc3Rlc3RpbWF0aW9uLndhbGQiLCAicGFyYW1ldGVyc19zaGEyNTYiOiAiZWFlMGMyYzIzNmQyNmRlMWQ2ZjQ4ZDk2MmNlZjU3N2UyMzYwOWJmZGFmNmFiZTJjMjQ5NWUzMGUxYjcyZjhjZSIsICJpbnB1dHMiOiBbImNvbXBsZXRlZCJdLCAibW9kZWxzIjogWyJjb21wbGV0ZWQiXX0sICJxdWVyaWVzIjogW1sic3RhdGlzdGljcyIsICJ0ZXN0IiwgInZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJ0ZXN0IiwgImRmIl0sIFsic3RhdGlzdGljcyIsICJ0ZXN0IiwgImRmX2Rlbm9taW5hdG9yIl0sIFsic3RhdGlzdGljcyIsICJ0ZXN0IiwgInBfdmFsdWUiXV0sICJkaXN0cmlidXRpb25zIjogeyJ0ZXN0IjogIkYifSwgImluZGV4IjogMn0=","r"),stdout=TRUE,stderr=TRUE)
if (!is.null(attr(wb_result_json,"status")) && attr(wb_result_json,"status")!=0) stop(paste(wb_result_json,collapse="\n"))
wb_result_values2 <- jsonlite::fromJSON(paste(wb_result_json,collapse="\n"),simplifyVector=FALSE)
checks[[18]] <- as.numeric(wb_result_values2[["statistics"]][["test"]][["value"]])
checks[[19]] <- as.numeric(wb_result_values2[["statistics"]][["test"]][["df"]])
checks[[20]] <- as.numeric(wb_result_values2[["statistics"]][["test"]][["df_denominator"]])
checks[[21]] <- as.numeric(wb_result_values2[["statistics"]][["test"]][["p_value"]])
data[["selected"]] <- data[["post"]]
data[["selected"]] <- data[["selected"]][, c("y", "x1", "x2"), drop=FALSE]
checks[[22]] <- as.numeric(nrow(data[["selected"]]))
stopifnot(identical(names(data[["selected"]]), c("y", "x1", "x2")))
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

wb_model_frame4 <- data[["selected"]]
wb_aliases <- list()
wb_frame <- wb_model_frame4
wb_fit <- lm(`y` ~ `x1` + `x2`, data=wb_frame)
wb_cov <- vcov(wb_fit)
wb_df <- df.residual(wb_fit)
results[["independent"]] <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)
checks[[23]] <- as.numeric(results[["independent"]][["beta"]][["Intercept"]])
checks[[24]] <- as.numeric(results[["independent"]][["beta"]][["x1"]])
checks[[25]] <- as.numeric(results[["independent"]][["beta"]][["x2"]])
checks[[26]] <- as.numeric(results[["independent"]][["se"]][["Intercept"]])
checks[[27]] <- as.numeric(results[["independent"]][["se"]][["x1"]])
checks[[28]] <- as.numeric(results[["independent"]][["se"]][["x2"]])
checks[[29]] <- as.numeric(results[["independent"]]$nobs)
# Closing self-checks
wb_check(checks[[1]], 80, 0.0, 0.0, "completed:nrows")
wb_check(checks[[2]], 80, 0.0, 0.0, "completed:nobs")
wb_check(checks[[3]], 4.652711573943123, 1e-08, 1e-06, "completed:coefficients")
wb_check(checks[[4]], 1.475820771771979, 1e-08, 1e-06, "completed:coefficients")
wb_check(checks[[5]], -0.40404481777033774, 1e-08, 1e-06, "completed:coefficients")
wb_check(checks[[6]], 1.5955241455226616, 1e-08, 1e-05, "completed:std_errors")
wb_check(checks[[7]], 0.17732404110690134, 1e-08, 1e-05, "completed:std_errors")
wb_check(checks[[8]], 0.08888234469730581, 1e-08, 1e-05, "completed:std_errors")
wb_check(checks[[9]], 2.9161022645752492, 1e-08, 1e-05, "completed:statistics.value")
wb_check(checks[[10]], 8, 0.0, 0.0, "completed:statistics.df")
wb_check(checks[[11]], 0.019406798019796175, 1e-06, 0.0, "completed:statistics.p_value")
wb_check(checks[[12]], 8.322733694537604, 1e-08, 1e-05, "completed:statistics.value")
wb_check(checks[[13]], 8, 0.0, 0.0, "completed:statistics.df")
wb_check(checks[[14]], 3.2813378097179405e-05, 1e-06, 0.0, "completed:statistics.p_value")
wb_check(checks[[15]], -4.545838874371921, 1e-08, 1e-05, "completed:statistics.value")
wb_check(checks[[16]], 8, 0.0, 0.0, "completed:statistics.df")
wb_check(checks[[17]], 0.0018846599328036571, 1e-06, 0.0, "completed:statistics.p_value")
wb_check(checks[[18]], 88.6728244577567, 1e-08, 1e-05, "post:statistics.value")
wb_check(checks[[19]], 2, 0.0, 0.0, "post:statistics.df")
wb_check(checks[[20]], 7.0, 0.0, 0.0, "post:statistics.df_denominator")
wb_check(checks[[21]], 1.0669105752740756e-05, 1e-06, 0.0, "post:statistics.p_value")
wb_check(checks[[22]], 80, 0.0, 0.0, "selected:nrows")
wb_check(checks[[23]], 4.596321816357483, 1e-08, 1e-06, "independent:coefficients")
wb_check(checks[[24]], 1.497109631010229, 1e-08, 1e-06, "independent:coefficients")
wb_check(checks[[25]], -0.4181990460548318, 1e-08, 1e-06, "independent:coefficients")
wb_check(checks[[26]], 0.6751924283923509, 1e-08, 1e-05, "independent:std_errors")
wb_check(checks[[27]], 0.09246563897577949, 1e-08, 1e-05, "independent:std_errors")
wb_check(checks[[28]], 0.08312412958648425, 1e-08, 1e-05, "independent:std_errors")
wb_check(checks[[29]], 80, 0.0, 0.0, "independent:nobs")
