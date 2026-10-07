# Workbench 1.8.11
# project: snapshot
# run: 20261005_091814_542545_c0b3eebc
# lineage_hash: f7f9bba0dce2c1d99252e3b4b8bb19f639bb62ea8d99ef16d7ca32fb003c185e
# Coverage
# step_6485f17b68a0f4bdeb945eed | data.cleaning | native | 
# step_ba8d0be27e6993bae63a245d | model.negative_binomial | snapshot | Only estimated-dispersion NB2 is validated; NB1 and fixed-alpha inference require Workbench. Workbench completed this step; numeric values come from a verified result sidecar, without native re-estimation.
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

# Native double parser
wb_parse_float <- function(text) {
  text <- gsub("_", "", text, fixed=TRUE)
  text <- sub("^\\+", "", text)
  text <- sub("^\\.", "0.", text)
  text <- sub("^-\\.", "-0.", text)
  text <- sub("^(-?)0+(?=[0-9])", "\\1", text, perl=TRUE)
  text <- sub("\\.$", ".0", text)
  text <- sub("\\.([eE])", ".0\\1", text)
  jsonlite::fromJSON(paste0("[", paste(text, collapse=","), "]"))
}
# End native double parser
# Native CSV double precision
wb_csv_precision <- function(frame, name, options=list()) {
  columns <- which(vapply(frame, is.double, logical(1)))
  if (!length(columns)) return(frame)
  raw <- do.call(read.csv, c(list(file=file.path(base,name), check.names=FALSE,
    stringsAsFactors=FALSE, blank.lines.skip=FALSE, na.strings=c("", "NA"),
    colClasses="character"), options))
  stopifnot(identical(dim(raw), dim(frame)), identical(names(raw), names(frame)))
  for (column in columns) {
    rows <- which(!is.na(frame[[column]]))
    if (!length(rows)) next
    token <- trimws(raw[[column]][rows])
    valid <- grepl("^[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?$", token, perl=TRUE)
    nonfinite <- tolower(token) %in% c("inf", "+inf", "-inf", "infinity", "+infinity", "-infinity")
    if (any(!valid & !nonfinite)) stop("CSV numeric token cannot be reproduced exactly")
    if (any(valid)) frame[[column]][rows[valid]] <- wb_parse_float(token[valid])
  }
  frame
}
# End native CSV double precision
data[["source_462a6947c68c9e6cd1a5b9c6"]] <- wb_read("source_c2e8eadde188587d9f35b7a9.csv", "c2e8eadde188587d9f35b7a9b05600ec8998a525e03774138b88e4553091909f", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
data[["source_462a6947c68c9e6cd1a5b9c6"]] <- wb_csv_precision(data[["source_462a6947c68c9e6cd1a5b9c6"]], "source_c2e8eadde188587d9f35b7a9.csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
data[["step_6485f17b68a0f4bdeb945eed"]] <- data[["source_462a6947c68c9e6cd1a5b9c6"]]
checks[[1]] <- as.numeric(nrow(data[["step_6485f17b68a0f4bdeb945eed"]]))
stopifnot(identical(names(data[["step_6485f17b68a0f4bdeb945eed"]]), c("y", "x1", "x2")))
# Workbench completed this step: negative_binomial (primary)
data[["step_ba8d0be27e6993bae63a245d"]] <- wb_read("step_ba8d0be27e6993bae63a245d.csv", "150a72b0bfecc03f769f08980be7f04400bfc24a208b704d5f2b0bb30c2391ee", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
data[["step_ba8d0be27e6993bae63a245d"]] <- wb_csv_precision(data[["step_ba8d0be27e6993bae63a245d"]], "step_ba8d0be27e6993bae63a245d.csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
checks[[2]] <- as.numeric(nrow(data[["step_ba8d0be27e6993bae63a245d"]]))
stopifnot(identical(names(data[["step_ba8d0be27e6993bae63a245d"]]), c("y", "x1", "x2")))
wb_result_bridge <- tempfile(fileext=".py")
writeLines("import base64\nimport json\nimport os\nfrom pathlib import Path\nimport sys\nfrom workbench.contracts.common.envelope import thaw_json\nfrom workbench.script_export.result_snapshot import ResultSnapshotRef, read_result_snapshot\n\nconfiguration = json.loads(base64.b64decode(sys.argv[2]))\nreference = ResultSnapshotRef(**configuration['reference'])\nvalues = read_result_snapshot(Path(sys.argv[1]), reference, expected_binding=configuration['binding'])\nfor name, distribution in configuration['distributions'].items():\n    if values['statistics'][name]['distribution'] != distribution:\n        raise AssertionError('Result sidecar reference distribution differs')\nif sys.argv[3] == 'r':\n    print(json.dumps(thaw_json(values), ensure_ascii=False, allow_nan=False))\nelif sys.argv[3] == 'stata':\n    lines = []\n    for index, path in enumerate(configuration['queries']):\n        value = values\n        for key in path:\n            value = value[key]\n        if value is not None and type(value) not in (int, float):\n            raise AssertionError('Result sidecar query is not numeric')\n        token = '.' if value is None else repr(value)\n        lines.append('scalar wb_result_' + str(configuration['index']) + '_' + str(index) + ' = ' + token)\n    lines.append('scalar wb_result_valid_' + str(configuration['index']) + ' = 1')\n    fd = os.open(sys.argv[4], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)\n    with os.fdopen(fd, 'w', encoding='utf-8') as handle:\n        handle.write('\\n'.join(lines) + '\\n')\nelse:\n    raise AssertionError('Unsupported result bridge mode')\n",wb_result_bridge,useBytes=TRUE)
wb_result_json <- system2("python3",c(shQuote(wb_result_bridge),shQuote(base),"eyJyZWZlcmVuY2UiOiB7ImZpbGVuYW1lIjogInN0ZXBfYmE4ZDBiZTI3ZTY5OTNiYWU2M2EyNDVkLmpzb24iLCAic2hhMjU2IjogIjk3Y2JjZjgyMDliN2I5YTc5YjExMmUzOWQwMjRmMDE5OTJjNDkyMjQ0MjUwNTQ2MmFjMjcxMTMzYTU4M2IwZTUiLCAic2NoZW1hX3ZlcnNpb24iOiAxfSwgImJpbmRpbmciOiB7InByb2plY3RfaWQiOiAic25hcHNob3QiLCAicnVuX2lkIjogIjIwMjYxMDA1XzA5MTgxNF81NDI1NDVfYzBiM2VlYmMiLCAibGluZWFnZV9oYXNoIjogImY3ZjliYmEwZGNlMmMxZDk5MjUyZTNiNGI4YmIxOWY2MzliYjYyZWE4ZDk5ZWYxNmQ3Y2EzMmZiMDAzYzE4NWUiLCAic3RlcF9pZCI6ICJzdGVwX2JhOGQwYmUyN2U2OTkzYmFlNjNhMjQ1ZCIsICJraW5kIjogIm1vZGVsIiwgIm9wZXJhdGlvbiI6ICJtb2RlbC5uZWdhdGl2ZV9iaW5vbWlhbCIsICJwYXJhbWV0ZXJzX3NoYTI1NiI6ICJjZGZiMDE5YzI0NTVkM2Q5Y2VkYWViNzY0MDY0MGY5YmRmMWE3ODViM2U0ZjQ1OGUzNTcyMWY3NmUxZTU4N2UxIiwgImlucHV0cyI6IFsic3RlcF82NDg1ZjE3YjY4YTBmNGJkZWI5NDVlZWQiXSwgIm1vZGVscyI6IFtdfSwgInF1ZXJpZXMiOiBbWyJub2JzIl0sIFsiY29lZmZpY2llbnRzIiwgIkludGVyY2VwdCJdLCBbImNvZWZmaWNpZW50cyIsICJ4MSJdLCBbImNvZWZmaWNpZW50cyIsICJ4MiJdLCBbInN0ZF9lcnJvcnMiLCAiSW50ZXJjZXB0Il0sIFsic3RkX2Vycm9ycyIsICJ4MSJdLCBbInN0ZF9lcnJvcnMiLCAieDIiXSwgWyJzdGF0aXN0aWNzIiwgIkludGVyY2VwdCIsICJ2YWx1ZSJdLCBbInN0YXRpc3RpY3MiLCAiSW50ZXJjZXB0IiwgInBfdmFsdWUiXSwgWyJzdGF0aXN0aWNzIiwgIngxIiwgInZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJ4MSIsICJwX3ZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJ4MiIsICJ2YWx1ZSJdLCBbInN0YXRpc3RpY3MiLCAieDIiLCAicF92YWx1ZSJdXSwgImRpc3RyaWJ1dGlvbnMiOiB7IkludGVyY2VwdCI6ICJ6IiwgIngxIjogInoiLCAieDIiOiAieiJ9LCAiaW5kZXgiOiAyfQ==","r"),stdout=TRUE,stderr=TRUE)
if (!is.null(attr(wb_result_json,"status")) && attr(wb_result_json,"status")!=0) stop(paste(wb_result_json,collapse="\n"))
wb_result_values2 <- jsonlite::fromJSON(paste(wb_result_json,collapse="\n"),simplifyVector=FALSE)
checks[[3]] <- as.numeric(wb_result_values2[["nobs"]])
checks[[4]] <- as.numeric(wb_result_values2[["coefficients"]][["Intercept"]])
checks[[5]] <- as.numeric(wb_result_values2[["coefficients"]][["x1"]])
checks[[6]] <- as.numeric(wb_result_values2[["coefficients"]][["x2"]])
checks[[7]] <- as.numeric(wb_result_values2[["std_errors"]][["Intercept"]])
checks[[8]] <- as.numeric(wb_result_values2[["std_errors"]][["x1"]])
checks[[9]] <- as.numeric(wb_result_values2[["std_errors"]][["x2"]])
checks[[10]] <- as.numeric(wb_result_values2[["statistics"]][["Intercept"]][["value"]])
checks[[11]] <- as.numeric(wb_result_values2[["statistics"]][["Intercept"]][["p_value"]])
checks[[12]] <- as.numeric(wb_result_values2[["statistics"]][["x1"]][["value"]])
checks[[13]] <- as.numeric(wb_result_values2[["statistics"]][["x1"]][["p_value"]])
checks[[14]] <- as.numeric(wb_result_values2[["statistics"]][["x2"]][["value"]])
checks[[15]] <- as.numeric(wb_result_values2[["statistics"]][["x2"]][["p_value"]])
writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 1000, 0.0, 0.0, "step_6485f17b68a0f4bdeb945eed:nrows")
wb_check(checks[[2]], 1000, 0.0, 0.0, "step_ba8d0be27e6993bae63a245d:nrows")
wb_check(checks[[3]], 1000, 0.0, 0.0, "step_ba8d0be27e6993bae63a245d:nobs")
wb_check(checks[[4]], 0.41794987220602414, 1e-08, 1e-06, "step_ba8d0be27e6993bae63a245d:coefficients")
wb_check(checks[[5]], 0.2972288232352733, 1e-08, 1e-06, "step_ba8d0be27e6993bae63a245d:coefficients")
wb_check(checks[[6]], -0.2544118335916357, 1e-08, 1e-06, "step_ba8d0be27e6993bae63a245d:coefficients")
wb_check(checks[[7]], 0.033988692547635736, 1e-08, 1e-05, "step_ba8d0be27e6993bae63a245d:std_errors")
wb_check(checks[[8]], 0.031235162030611035, 1e-08, 1e-05, "step_ba8d0be27e6993bae63a245d:std_errors")
wb_check(checks[[9]], 0.03237676639037322, 1e-08, 1e-05, "step_ba8d0be27e6993bae63a245d:std_errors")
wb_check(checks[[10]], 12.296732850793251, 1e-08, 1e-05, "step_ba8d0be27e6993bae63a245d:statistics.value")
wb_check(checks[[11]], 9.431229712147405e-35, 1e-06, 0.0, "step_ba8d0be27e6993bae63a245d:statistics.p_value")
wb_check(checks[[12]], 9.515840607581403, 1e-08, 1e-05, "step_ba8d0be27e6993bae63a245d:statistics.value")
wb_check(checks[[13]], 1.8024962829839534e-21, 1e-06, 0.0, "step_ba8d0be27e6993bae63a245d:statistics.p_value")
wb_check(checks[[14]], -7.857851847344506, 1e-08, 1e-05, "step_ba8d0be27e6993bae63a245d:statistics.value")
wb_check(checks[[15]], 3.907771102641985e-15, 1e-06, 0.0, "step_ba8d0be27e6993bae63a245d:statistics.p_value")
