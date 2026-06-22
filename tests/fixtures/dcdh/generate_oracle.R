#!/usr/bin/env Rscript
# =============================================================================
# Workbench v1.5.9 — de Chaisemartin-D'Haultfoeuille (DIDmultiplegtDYN) oracle.
#
# RUN FROM WORKTREE ROOT:  Rscript tests/fixtures/dcdh/generate_oracle.R
#
# Requires: DIDmultiplegtDYN (tested 2.3.4) + polars (its hard dependency, from
# rpolars.r-universe.dev — NOT on CRAN). polars MUST be library()-loaded before
# did_multiplegt_dyn() or it errors with "object 'pl' not found". The Python test
# suite NEVER calls R — it reads the committed CSV + JSON produced here.
#
# LOCKED 口径 (saved into every JSON's metadata, NOT just here): no covariates;
# effects=L; placebo=P; same_switchers=TRUE; cluster=~id; fixed seed.
#
# OBJECT SHAPE (decoded from 2.3.4): m$results$Effects / $Placebos / $ATE are
# matrices with columns: Estimate, SE, "LB CI", "UB CI", N, Switchers, N.w,
# Switchers.w. Rows Effect_1..L / Placebo_1..P / Av_tot_eff. With same_switchers=
# TRUE the Switchers count is constant across effect horizons (only switchers
# observed at every horizon enter). "Switchers" = switcher count (our n_switchers);
# "N" = observation count.
# =============================================================================
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(jsonlite) })

L <- 3L; P <- 2L; SEED <- 909L
PKG_VERSION <- as.character(packageVersion("DIDmultiplegtDYN"))
out_dir <- "tests/fixtures/dcdh"

fit_dyn <- function(d) {
  set.seed(SEED)
  # NOTE: did_multiplegt_dyn deparses the `effects`/`placebo` LITERAL expression
  # (not its value), so a variable like `L` errors "Positive integer required".
  # Pass literals; keep L/P (= 3/2) only for metadata + extract. Keep in sync.
  did_multiplegt_dyn(df = d, outcome = "y", group = "id", time = "year",
                     treatment = "d", effects = 3, placebo = 2,
                     cluster = "id", same_switchers = TRUE, graph_off = TRUE)
}

col <- function(tab, name) as.numeric(tab[, name])

extract <- function(m) {
  eff <- m$results$Effects
  plb <- m$results$Placebos
  ate <- m$results$ATE
  list(
    effect_estimate = col(eff, "Estimate"), effect_se = col(eff, "SE"),
    effect_n = col(eff, "Switchers"),
    placebo_estimate = col(plb, "Estimate"), placebo_se = col(plb, "SE"),
    placebo_n = col(plb, "Switchers"),
    overall_estimate = as.numeric(ate[1, "Estimate"]),
    overall_se = as.numeric(ate[1, "SE"])
  )
}

write_fixture <- function(d, name) {
  m <- fit_dyn(d); ex <- extract(m)
  obj <- c(list(fixture = name,
                metadata = list(effects = L, placebos = P, same_switchers = TRUE,
                                cluster = "id", seed = SEED,
                                package_version = PKG_VERSION)),
           ex)
  write_json(obj, file.path(out_dir, paste0("dyn_", name, ".json")),
             digits = 16, auto_unbox = TRUE, pretty = TRUE)
  write.csv(d[, c("id", "year", "d", "y")],
            file.path(out_dir, paste0("panel_", name, ".csv")), row.names = FALSE)
  cat(sprintf("[%s] effects=%d placebos=%d switchers=%g\n", name,
              length(ex$effect_estimate), length(ex$placebo_estimate), ex$effect_n[1]))
}

# PANEL 1 — non-absorbing main: 120 units, years 1..8, baseline d=0. Units switch
# up 0->1 at staggered years {3,4,5}; ids divisible by 6 switch BACK 1->0 two
# periods later (genuine non-absorbing). The remaining units (fy=NA) never switch
# = not-yet/never controls. True effect 0.8.
make_nonabsorbing <- function() {
  set.seed(909); N <- 120L; Tn <- 8L; ids <- 1:N
  fy <- c(3, 4, 5, NA, NA)[((ids - 1) %% 5) + 1]
  d <- expand.grid(id = ids, year = 1:Tn); d$fy <- fy[d$id]
  d$d <- as.integer(!is.na(d$fy) & d$year >= d$fy)
  back <- (d$id %% 6 == 0) & !is.na(d$fy) & d$year >= d$fy + 2
  d$d[back] <- 0L
  fe_id <- rnorm(N)[d$id]; fe_yr <- (1:Tn)[d$year] * 0.1
  d$y <- fe_id + fe_yr + 0.8 * d$d + rnorm(nrow(d), sd = 0.3)
  d[order(d$id, d$year), ]
}
# PANEL 2 — baseline=1 / down-switchers: a few units start treated and switch
# 1->0, mixed with baseline=0 up-switchers. Tests exclusion accounting.
make_baseline1 <- function() {
  d <- make_nonabsorbing()
  flip <- d$id %in% c(2, 7, 12, 17)
  d$d[flip] <- ifelse(d$year[flip] <= 4, 1L, 0L)
  d[order(d$id, d$year), ]
}
# PANEL 3 — placebo: same switch structure, NO treatment effect (coef 0).
make_placebo <- function() {
  set.seed(909); N <- 120L; Tn <- 8L; ids <- 1:N
  fy <- c(3, 4, 5, NA, NA)[((ids - 1) %% 5) + 1]
  d <- expand.grid(id = ids, year = 1:Tn); d$fy <- fy[d$id]
  d$d <- as.integer(!is.na(d$fy) & d$year >= d$fy)
  back <- (d$id %% 6 == 0) & !is.na(d$fy) & d$year >= d$fy + 2
  d$d[back] <- 0L
  fe_id <- rnorm(N)[d$id]; fe_yr <- (1:Tn)[d$year] * 0.1
  d$y <- fe_id + fe_yr + 0.0 * d$d + rnorm(nrow(d), sd = 0.3)
  d[order(d$id, d$year), ]
}

write_fixture(make_nonabsorbing(), "nonabsorbing")
write_fixture(make_baseline1(),    "baseline1")
write_fixture(make_placebo(),      "placebo")
cat("DONE.\n")
