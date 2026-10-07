args <- commandArgs(trailingOnly=TRUE)
data <- read.csv(file.path(args[1], "data.csv"))
fit <- glm(y ~ x1 + x2, data=data, family=MASS::negative.binomial(theta=2),
           control=glm.control(epsilon=1e-16, maxit=1000))
information <- crossprod(model.matrix(fit), model.matrix(fit) * (fitted(fit)/(1+.5*fitted(fit))))
result <- list(coefficients=unname(coef(fit)), covariance=unname(solve(information)),
               std_error=unname(sqrt(diag(solve(information)))),
               iterations=fit$iter, converged=fit$converged, epsilon=1e-16,
               version=R.version.string)
jsonlite::write_json(result, file.path(args[1], "r.json"), digits=NA, pretty=TRUE, auto_unbox=TRUE)
print(result)
