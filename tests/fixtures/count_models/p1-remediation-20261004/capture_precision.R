args <- commandArgs(trailingOnly=TRUE)
if (file.exists(args[2])) stop("Preserve existing native precision evidence")
data <- read.csv(args[1])
fit <- glm(y ~ x1 + x2, data=data, family=MASS::negative.binomial(theta=2),
           control=glm.control(epsilon=1e-16, maxit=1000))
information <- crossprod(model.matrix(fit), model.matrix(fit) * (fitted(fit)/(1+.5*fitted(fit))))
full <- function(value) sprintf("%.17g", value)
result <- list(coefficients=full(coef(fit)), std_error=full(sqrt(diag(solve(information)))),
               score=full(crossprod(model.matrix(fit), (data$y-fitted(fit))/(1+.5*fitted(fit)))),
               iterations=fit$iter, converged=fit$converged, epsilon=full(1e-16))
jsonlite::write_json(result, args[2], pretty=TRUE, auto_unbox=TRUE)
print(result)
