options(digits = 17)
treated <- c(0, 1, 2)
donors <- rbind(c(0,1,2), c(0,2,4), c(2,1,0))
objective <- function(theta) {
  weights <- c(theta[1], theta[2], 1-theta[1]-theta[2])
  sum((treated - as.numeric(weights %*% donors[,1:3]))^2)
}
gradient <- function(theta) {
  eps <- 1e-7
  c((objective(theta + c(eps, 0)) - objective(theta - c(eps, 0))) / (2*eps),
    (objective(theta + c(0, eps)) - objective(theta - c(0, eps))) / (2*eps))
}
fit <- constrOptim(c(1/3, 1/3), objective, grad=gradient,
  ui=rbind(c(1,0), c(0,1), c(-1,-1)), ci=c(0,0,-1), method="BFGS")
weights <- c(fit$par[1], fit$par[2], 1-sum(fit$par))
cat(sprintf("rmse,%.17g\n", sqrt(fit$value/3)))
cat(sprintf("weight_sum,%.17g\n", sum(weights)))
