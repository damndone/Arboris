options(digits = 17)
df <- data.frame(
  treated = c(1,1,1,0,0,0),
  x = c(-1,0,1,-1.1,0.1,1.2),
  z = c(0,1,2,0,1,2)
)
fit <- glm(treated ~ x + z, data=df, family=binomial())
p <- predict(fit, type="response")
cat(sprintf("min,%.17g\n", min(p)))
cat(sprintf("max,%.17g\n", max(p)))
