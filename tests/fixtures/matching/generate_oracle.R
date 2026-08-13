options(digits = 17)
matching_oracle <- function(df) {
  fit <- glm(treated ~ x + z, data=df, family=binomial())
  p <- predict(fit, type="response")
  geometry <- scale(df[c("x", "z")], center=FALSE, scale=apply(df[c("x", "z")], 2, sd))
  available <- which(df$treated == 0)
  pairs <- matrix(integer(), ncol=2)
  for (treated_position in which(df$treated == 1)) {
    euclidean <- apply(geometry[available, , drop=FALSE], 1, function(row) {
      sqrt(sum((geometry[treated_position, ] - row)^2))
    })
    logit_distance <- abs(qlogis(p[treated_position]) - qlogis(p[available]))
    selected_index <- order(euclidean, logit_distance, available)[1]
    control_position <- available[selected_index]
    pairs <- rbind(pairs, c(treated_position - 1L, control_position - 1L))
    available <- available[-selected_index]
  }
  effects <- vapply(seq_len(nrow(pairs)), function(i) {
    df$outcome[pairs[i, 1] + 1L] - df$outcome[pairs[i, 2] + 1L]
  }, numeric(1))
  list(p=p, pairs=pairs, att=mean(effects))
}

balanced <- data.frame(
  outcome = c(10,12,14,8,10,12),
  treated = c(1,1,1,0,0,0),
  x = c(-1,0,1,-1.1,0.1,1.2),
  z = c(0,1,2,0,1,2)
)
geometry_discriminator <- data.frame(
  outcome = c(10,12,14,16,1,2,3,4,5,6),
  treated = c(1,1,1,1,0,0,0,0,0,0),
  x = c(-0.013998599759631629,-1.5382139091060396,1.0380751179165828,0.10013574110923433,0.44825808887285307,-0.9598332818072399,-0.815963048068025,0.7623276701968569,2.380433330194279,0.543836123631552),
  z = c(1.7286634209616565,-0.5089825207066017,-0.43454360621327803,0.8938077430233872,0.4153788882413647,-0.747563623089855,-0.39953666243048835,-1.4153678855978593,-1.9933229565460022,1.696201083531503)
)
balanced_oracle <- matching_oracle(balanced)
geometry_oracle <- matching_oracle(geometry_discriminator)
balanced_pairs <- paste(apply(balanced_oracle$pairs, 1, function(row) sprintf("[%d,%d]", row[1], row[2])), collapse=",")
geometry_pairs <- paste(apply(geometry_oracle$pairs, 1, function(row) sprintf("[%d,%d]", row[1], row[2])), collapse=",")
cat(sprintf(
  '{"balanced":{"propensity_min":%.17g,"propensity_max":%.17g,"att":%.17g,"pairs":[%s]},"geometry_discriminator":{"att":%.17g,"pairs":[%s]}}\n',
  min(balanced_oracle$p), max(balanced_oracle$p), balanced_oracle$att, balanced_pairs,
  geometry_oracle$att, geometry_pairs
))
