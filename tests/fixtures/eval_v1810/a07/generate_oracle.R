# VERIFICATION LEVEL: grouped OLS, NeweyWest without prewhitening,
# Bartlett lag 4, N/(N-K) adjustment. Each group is sorted independently.
suppressPackageStartupMessages({library(sandwich); library(jsonlite)})
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 1, startsWith(args[1], "tests/fixtures/eval_v1810/"))
here <- args[1]
cat("output directory:", here, "\n")
dir.create(here, recursive = TRUE, showWarnings = FALSE)
d <- read.csv("tests/fixtures/hac/data.csv")
east <- transform(d, region = "east")
west <- transform(d, region = "west", y = 0.5 + 1.2 * y)
set.seed(20261004)
data <- rbind(east, west)
data <- data[sample.int(nrow(data)), ]
write.csv(data, file.path(here, "data.csv"), row.names = FALSE)
ordered <- east[order(east$year), ]
fit <- lm(y ~ x1 + x2, data = ordered)
b <- coef(fit); se <- sqrt(diag(NeweyWest(fit, lag = 4, prewhite = FALSE, adjust = TRUE)))
names(b)[1] <- "Intercept"; names(se)[1] <- "Intercept"
writeLines(toJSON(list(coefficients = as.list(b), std_error = as.list(se)),
                  auto_unbox = TRUE, digits = NA, pretty = TRUE), file.path(here, "oracle.json"))
