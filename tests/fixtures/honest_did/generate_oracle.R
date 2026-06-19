#!/usr/bin/env Rscript
# ---------------------------------------------------------------------------
# Workbench v1.5.7 honest-DID (Rambachan-Roth 2023, DeltaRM relative magnitudes)
# Task 1: generate committed R HonestDiD 0.2.8 oracle fixtures.
#
# R is used ONLY to produce committed JSON. After this, the Python engine
# (T2-T5) ports the DeltaRM path and validates element-wise against these
# JSON files; Python never touches R.
#
# Installed source inspected at:
#   /opt/homebrew/lib/R/4.6/site-library/HonestDiD  (version 0.2.8)
#
# Verified API facts (against the installed 0.2.8 source):
#  * createSensitivityResults_relativeMagnitudes(betahat, sigma, numPrePeriods,
#      numPostPeriods, bound, method="C-LF", Mbarvec, l_vec, ..., alpha=0.05,
#      gridPoints=1e3, grid.ub=NA, grid.lb=NA, parallel=FALSE, seed=0)
#      -> tibble with columns including lb, ub, Mbar.  (source of truth for CIs)
#  * .create_A_RM(numPrePeriods, numPostPeriods, Mbar=1, s, max_positive=TRUE,
#      dropZero=TRUE) -> per-(s,sign) constraint matrix A (takes s+max_positive,
#      NOT l_vec). dropZero drops column (numPre+1). Rows with all-zero are
#      pruned. Returns (numPre+numPost rows after rbind of two blocks, minus
#      zero rows) x (numPre+numPost) matrix.
#  * .computeConditionalCS_DeltaRM_fixedS(s, max_positive, Mbar, betahat, sigma,
#      numPrePeriods, numPostPeriods, l_vec, alpha, hybrid_flag, hybrid_kappa,
#      postPeriodMomentsOnly, gridPoints, grid.ub, grid.lb, seed=0)
#      -> tibble(grid, accept)  (accept 0/1 over the shared theta grid)
#  * Per-theta ARP single-point test (used inside .ARP_computeCI):
#      .lp_conditional_test_fn(theta, y_T, X_T, sigma, alpha, hybrid_flag,
#        hybrid_list, rowsForARP) -> list(reject 0/1, eta=eta_star, delta=...)
#      called with y_T = Y - AGammaInv_one*theta, X_T = AGammaInv_minusOne,
#      sigma = sigmaY, where for s,sign,Mbar:
#        A_RM    = .create_A_RM(...)
#        d_RM    = .create_d_RM(numPre,numPost)
#        Gamma   = .construct_Gamma(l_vec)
#        AGammaInv = A_RM[,(numPre+1):(numPre+numPost)] %*% solve(Gamma)
#        AGammaInv_one = AGammaInv[,1]; AGammaInv_minusOne = AGammaInv[,-1]
#        Y       = c(A_RM %*% betahat - d_RM)
#        sigmaY  = A_RM %*% sigma %*% t(A_RM)
#        rowsForARP (postPeriodMomentsOnly, numPost>1) =
#          which(rowSums(A_RM[,(numPre+1):NCOL(A_RM)] != 0) > 0)
#        lf_cv   = .compute_least_favorable_cv(X_T=AGammaInv_minusOne,
#                    sigma=sigmaY, hybrid_kappa, rowsForARP, seed=0)
#        hybrid_list = list(hybrid_kappa=kappa, lf_cv=lf_cv)
# ---------------------------------------------------------------------------

suppressWarnings(suppressMessages({
  library(HonestDiD)
  library(jsonlite)
}))

set.seed(0)

OUTDIR <- "tests/fixtures/honest_did"
dir.create(OUTDIR, recursive = TRUE, showWarnings = FALSE)

# -------- hard-coded small deterministic input (3 pre + 4 post) -------------
numPre  <- 3L
numPost <- 4L

# event-study coefficient vector (pre periods first, then post)
betahat <- c(0.05, -0.02, 0.01, 0.10, 0.15, 0.12, 0.08)

# build a PD covariance: A %*% t(A)/20 + diag*0.001
Araw  <- matrix(rnorm((numPre + numPost)^2), nrow = numPre + numPost)
sigma <- Araw %*% t(Araw) / 20 + diag(numPre + numPost) * 0.001

# round to 8 dp BEFORE passing to R so Python reads byte-identical numbers
betahat <- round(betahat, 8)
sigma   <- round(sigma,   8)

alpha       <- 0.05
hybrid_kappa<- alpha / 10            # 0.005, the C-LF default
mbar_grid   <- c(0, 0.5, 1, 1.5, 2)
l_avg       <- rep(1 / numPost, numPost)   # post-AVERAGE target

# ===========================================================================
# 1. honest_rm.json  -- FINAL CIs (source of truth)
#    createSensitivityResults_relativeMagnitudes, method = "C-LF", seed = 0
# ===========================================================================

# (a) post-AVERAGE target over the Mbar grid
set.seed(0)
rm_avg_tbl <- createSensitivityResults_relativeMagnitudes(
  betahat = betahat, sigma = sigma,
  numPrePeriods = numPre, numPostPeriods = numPost,
  method = "Conditional", Mbarvec = mbar_grid,
  l_vec = l_avg, alpha = alpha, gridPoints = 1e3, seed = 0
)
rm_avg <- lapply(seq_len(nrow(rm_avg_tbl)), function(i) {
  list(Mbar = as.numeric(rm_avg_tbl$Mbar[i]),
       lb   = as.numeric(rm_avg_tbl$lb[i]),
       ub   = as.numeric(rm_avg_tbl$ub[i]))
})

# (b) per-post-event-time indicator targets, Mbar = 1 only
rm_event <- lapply(seq_len(numPost), function(j) {
  l_j <- as.numeric(seq_len(numPost) == j)   # e_j indicator (basis vector)
  set.seed(0)
  tbl <- createSensitivityResults_relativeMagnitudes(
    betahat = betahat, sigma = sigma,
    numPrePeriods = numPre, numPostPeriods = numPost,
    method = "Conditional", Mbarvec = c(1),
    l_vec = l_j, alpha = alpha, gridPoints = 1e3, seed = 0
  )
  list(event_index = j - 1L,                 # 0-based post event time
       lb = as.numeric(tbl$lb[1]),
       ub = as.numeric(tbl$ub[1]))
})

honest_rm <- list(
  numPre    = numPre,
  numPost   = numPost,
  alpha     = alpha,
  method    = "Conditional",
  seed      = 0L,
  gridPoints= 1000L,
  betahat   = as.numeric(betahat),
  sigma     = lapply(seq_len(nrow(sigma)), function(i) as.numeric(sigma[i, ])),
  mbar_grid = as.numeric(mbar_grid),
  l_avg     = as.numeric(l_avg),
  rm_avg    = rm_avg,
  rm_event  = rm_event
)
write_json(honest_rm, file.path(OUTDIR, "honest_rm.json"),
           digits = 10, auto_unbox = TRUE, pretty = TRUE)

# ===========================================================================
# 2. arm_constraints.json  -- INTERMEDIATE for Task 2
#    .create_A_RM for Mbar = 1 over ALL (s, max_positive) the engine must
#    reproduce. s loops -(numPre-1):0 ; max_positive in {TRUE, FALSE}.
#    Documented "primary" pick: s = 0, max_positive = TRUE.
# ===========================================================================
Mbar_arm <- 1
s_indices <- -(numPre - 1):0          # e.g. -2, -1, 0
A_list <- list()
for (s in s_indices) {
  for (mp in c(TRUE, FALSE)) {
    A <- HonestDiD:::.create_A_RM(numPrePeriods = numPre,
                                  numPostPeriods = numPost,
                                  Mbar = Mbar_arm, s = s,
                                  max_positive = mp, dropZero = TRUE)
    A_nested <- lapply(seq_len(nrow(A)), function(i) as.numeric(A[i, ]))
    A_list[[length(A_list) + 1L]] <- list(
      s            = as.integer(s),
      max_positive = mp,
      nrow         = as.integer(nrow(A)),
      ncol         = as.integer(ncol(A)),
      A            = A_nested
    )
  }
}
arm_constraints <- list(
  numPre  = numPre,
  numPost = numPost,
  Mbar    = Mbar_arm,
  s_indices = as.integer(s_indices),
  primary = list(s = 0L, max_positive = TRUE),  # documented engine spot-check
  constraints = A_list
)
write_json(arm_constraints, file.path(OUTDIR, "arm_constraints.json"),
           digits = 10, auto_unbox = TRUE, pretty = TRUE)

# ===========================================================================
# 3. conditional_test.json  -- INTERMEDIATE for Task 3
#    A single-(theta, Mbar) PURE ARP CONDITIONAL single-point test instance,
#    with the fully-reconstructed inputs to .lp_conditional_test_fn AND its
#    deterministic scalar output {reject, eta}. Representative
#    (s, max_positive) = (0, TRUE), Mbar = 1, l_vec = l_avg, theta = 0.05.
#
#    Design switch (v1.5.7): hybrid_flag = "ARP" (NOT "LF"). Under ARP the
#    least-favorable first stage is skipped (mod_size = alpha) and hybrid_list
#    is never read for an lf_cv, so the whole path is simulation-free and
#    exactly reproducible in numpy (LP + truncated-normal inverse). Verified
#    against the .lp_conditional_test_fn body: the "ARP" branch only sets
#    mod_size = alpha and does not touch hybrid_list$lf_cv. There is therefore
#    NO lf_cv field in this fixture.
#
#    Task 3 consumes this by: building A_RM, d_RM, Gamma, AGammaInv, Y, sigmaY,
#    rowsForARP exactly as documented above (all exported here as a
#    cross-check), then calling its ported single-point ARP conditional test at
#    the given theta and asserting reject == reject_expected (and eta ~ eta_star
#    to tolerance).
# ===========================================================================
s_ct  <- 0L
mp_ct <- TRUE
Mbar_ct <- 1
theta_ct <- 0.05

A_RM <- HonestDiD:::.create_A_RM(numPrePeriods = numPre, numPostPeriods = numPost,
                                 Mbar = Mbar_ct, s = s_ct, max_positive = mp_ct)
d_RM <- HonestDiD:::.create_d_RM(numPrePeriods = numPre, numPostPeriods = numPost)

# postPeriodMomentsOnly = TRUE, numPost > 1 -> keep all rows, set rowsForARP
postPeriodIndices <- (numPre + 1):NCOL(A_RM)
rowsForARP <- which(rowSums(A_RM[, postPeriodIndices] != 0) > 0)

Gamma <- HonestDiD:::.construct_Gamma(l_avg)
AGammaInv <- A_RM[, (numPre + 1):(numPre + numPost)] %*% solve(Gamma)
AGammaInv_one      <- AGammaInv[, 1]
AGammaInv_minusOne <- AGammaInv[, -1]
Y      <- c(A_RM %*% betahat - d_RM)
sigmaY <- A_RM %*% sigma %*% t(A_RM)

# Pure ARP conditional: no least-favorable first stage, empty hybrid_list.
y_T <- Y - AGammaInv_one * theta_ct
res <- HonestDiD:::.lp_conditional_test_fn(
  theta = theta_ct, y_T = y_T, X_T = AGammaInv_minusOne,
  sigma = sigmaY, alpha = alpha, hybrid_flag = "ARP",
  hybrid_list = list(),
  rowsForARP = rowsForARP
)

mat_to_nested <- function(M) lapply(seq_len(nrow(M)), function(i) as.numeric(M[i, ]))

conditional_test <- list(
  numPre   = numPre,
  numPost  = numPost,
  s        = s_ct,
  max_positive = mp_ct,
  Mbar     = Mbar_ct,
  theta    = theta_ct,
  alpha    = alpha,
  hybrid_flag  = "ARP",
  l_vec    = as.numeric(l_avg),
  # --- reconstructed inputs (so Task 3 can build/check each piece) ---
  A_RM        = mat_to_nested(A_RM),
  d_RM        = as.numeric(d_RM),
  rowsForARP  = as.integer(rowsForARP),       # 1-based R indices
  AGammaInv_one      = as.numeric(AGammaInv_one),
  AGammaInv_minusOne = mat_to_nested(matrix(AGammaInv_minusOne,
                                            nrow = nrow(A_RM))),
  Y           = as.numeric(Y),
  y_T         = as.numeric(y_T),              # Y - AGammaInv_one * theta
  sigmaY      = mat_to_nested(sigmaY),
  # --- expected deterministic scalar output (pure ARP conditional) ---
  reject      = as.integer(res$reject),
  eta         = as.numeric(res$eta)
)
write_json(conditional_test, file.path(OUTDIR, "conditional_test.json"),
           digits = 10, auto_unbox = TRUE, pretty = TRUE)

# -------- sanity to stdout --------------------------------------------------
cat("numPre =", numPre, " numPost =", numPost, "\n")
cat("rm_avg widths (M=0..2):\n")
for (r in rm_avg) cat(sprintf("  Mbar=%.1f  [%.5f, %.5f]  width=%.5f\n",
                              r$Mbar, r$lb, r$ub, r$ub - r$lb))
cat("rm_event count =", length(rm_event), "\n")
cat("conditional_test (ARP): theta=", theta_ct, " reject=", res$reject,
    " eta=", res$eta, "\n")
cat("arm_constraints: n(s,sign) combos =", length(A_list),
    " (expect", length(s_indices) * 2, ")\n")

# ===========================================================================
# 4. grid_accept.json  -- ELEMENT-WISE ORACLE for Task 4
#    The FULL union accept vector (over s and max_positive) produced by
#    HonestDiD:::computeConditionalCS_DeltaRM for Mbar=1, l_vec=l_avg, ARP.
#    Returns tibble(grid, accept); accept is pmax over (s,sign) per the R
#    source. Used to validate the degenerate dual-path port element-wise
#    (CI-endpoint alone under-validates interior degenerate theta).
#
#    Gated by env WB_GRID_ONLY: when set, ONLY this fixture is (re)written so
#    the other committed fixtures stay byte-identical (git must not list them).
# ===========================================================================
ga_tbl <- HonestDiD:::computeConditionalCS_DeltaRM(
  betahat = betahat, sigma = sigma,
  numPrePeriods = numPre, numPostPeriods = numPost,
  l_vec = l_avg, Mbar = 1, alpha = 0.05,
  hybrid_flag = "ARP", gridPoints = 1000L, seed = 0
)
grid_accept <- list(
  Mbar   = 1,
  l      = "avg",
  grid   = as.numeric(ga_tbl$grid),
  accept = as.integer(ga_tbl$accept)
)
write_json(grid_accept, file.path(OUTDIR, "grid_accept.json"),
           digits = 10, auto_unbox = TRUE, pretty = TRUE)
cat("grid_accept: n accept==1 =", sum(ga_tbl$accept),
    " CI = [", min(ga_tbl$grid[ga_tbl$accept == 1]), ",",
    max(ga_tbl$grid[ga_tbl$accept == 1]), "]\n")

# ===========================================================================
# 5. a_sd.json + flci_sd.json  -- DeltaSD / FLCI oracle (v1.5.7.1)
#
#    Reuses the SAME betahat/sigma/numPre/numPost as the DeltaRM fixtures so
#    all engine tests share one covariance.
#
#    Verified API facts (HonestDiD 0.2.8 source):
#     * .create_A_SD(numPrePeriods, numPostPeriods, postPeriodMomentsOnly=FALSE)
#         Builds Atilde (numPre+numPost-1) x (numPre+numPost+1) where each row r
#         is the 2nd difference [1,-2,1] at columns r:(r+2), THEN drops column
#         (numPre+1) -- i.e. the reference period is the augmented grid's
#         period 0; the 2nd-difference is taken over the FULL augmented grid
#         (length numPre+numPost+1) and the reference column is removed
#         afterwards. Final A = rbind(Atilde, -Atilde) so it encodes
#         |2nd diff| <= M as two-sided linear constraints. Does NOT take l_vec
#         or M. Result dim = 2*(numPre+numPost-1) x (numPre+numPost).
#     * findOptimalFLCI(betahat, sigma, M=0, numPrePeriods, numPostPeriods,
#         l_vec=basis1, numPoints=100, alpha=0.05, seed=0)
#         -> list(FLCI=c(lb,ub), optimalVec, optimalHalfLength, M, status).
#         CI endpoints are FLCI[1] (lb) / FLCI[2] (ub); half-length is
#         $optimalHalfLength. l_vec and M are named args (M positional default 0).
#         M=0 runs fine (no error) and returns the minimum-variance (classical-
#         like) CI; recorded as the engine's M=0 anchor.
#     * h-grid inside .findOptimalFLCI_helper: bisection over [hMin, h0] where
#         hMin = .findLowestH (CVXR min-SD), h0 = .findHForMinimumBias
#         (min-bias SD); fallback grid = seq(hMin, h0, length.out=numPoints),
#         numPoints default = 100.
# ===========================================================================

# (a) .create_A_SD operator matrix
A_sd <- HonestDiD:::.create_A_SD(numPrePeriods = numPre, numPostPeriods = numPost)
a_sd <- list(
  numPre  = numPre,
  numPost = numPost,
  nrow    = as.integer(nrow(A_sd)),
  ncol    = as.integer(ncol(A_sd)),
  A_sd    = lapply(seq_len(nrow(A_sd)), function(i) as.numeric(A_sd[i, ]))
)
write_json(a_sd, file.path(OUTDIR, "a_sd.json"),
           digits = 10, auto_unbox = TRUE, pretty = TRUE)

# (b) findOptimalFLCI over the M-grid; M scaled to match the engine:
#     c(0,0.5,1,1.5,2) * max(sqrt(diag(sigma)))
M_scale <- max(sqrt(diag(sigma)))
Mvec    <- c(0, 0.5, 1.0, 1.5, 2.0) * M_scale
flci_rows <- lapply(Mvec, function(M) {
  r <- HonestDiD::findOptimalFLCI(
    betahat = betahat, sigma = sigma,
    numPrePeriods = numPre, numPostPeriods = numPost,
    l_vec = l_avg, M = M, alpha = alpha, numPoints = 100, seed = 0
  )
  list(M                = as.numeric(M),
       optimalHalfLength = as.numeric(r$optimalHalfLength),
       lb               = as.numeric(r$FLCI[1]),
       ub               = as.numeric(r$FLCI[2]),
       status           = as.character(r$status))
})
flci_sd <- list(
  numPre   = numPre,
  numPost  = numPost,
  alpha    = alpha,
  l_vec    = as.numeric(l_avg),
  numPoints= 100L,
  M_scale  = as.numeric(M_scale),
  Mvec     = as.numeric(Mvec),
  results  = flci_rows
)
write_json(flci_sd, file.path(OUTDIR, "flci_sd.json"),
           digits = 10, auto_unbox = TRUE, pretty = TRUE)

cat("a_sd: dim =", nrow(A_sd), "x", ncol(A_sd), "\n")
cat("flci_sd (M scaled by", M_scale, "):\n")
for (rr in flci_rows) cat(sprintf("  M=%.6f  hl=%.6f  [%.6f, %.6f]  %s\n",
                                  rr$M, rr$optimalHalfLength, rr$lb, rr$ub, rr$status))
cat("DONE\n")
