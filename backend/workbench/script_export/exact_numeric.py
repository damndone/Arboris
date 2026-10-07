"""Native double parsing without a decimal display roundtrip."""

R_FLOAT_PARSER = r'''# Native double parser
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
# End native double parser'''

R_CSV_PRECISION = r'''# Native CSV double precision
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
# End native CSV double precision'''


def r_float_parser(ctx):
    ctx.packages.add('jsonlite')
    if 'exact_float_parser' in ctx.helpers:
        return []
    ctx.helpers.add('exact_float_parser')
    return R_FLOAT_PARSER.splitlines()
