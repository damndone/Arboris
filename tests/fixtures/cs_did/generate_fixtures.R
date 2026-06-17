# Oracle generator for cs_did. Requires: did, DRDID, jsonlite.
# Reads tests/fixtures/cs_did/panel.csv ; writes att_gt.json, drdid_inffunc.json, aggte.json.
# panel.csv is produced by the deterministic Python snippet in the plan (Task 1 Step 1):
#   60 units x periods 1..6, first_treat in {0(never),3,4,5}, covariate x1, outcome y.
# Run from the worktree root:  /opt/homebrew/bin/Rscript tests/fixtures/cs_did/generate_fixtures.R
suppressMessages({library(did); library(DRDID); library(jsonlite)})

d <- read.csv("tests/fixtures/cs_did/panel.csv")

# ---- att_gt point estimates: 3 methods x 2 control groups (varying base, no anticipation) ----
emit_attgt <- function(method, control) {
  r <- att_gt(yname = "y", tname = "period", idname = "unit", gname = "first_treat",
              xformla = ~x1, data = d, est_method = method, control_group = control,
              base_period = "varying", anticipation = 0, bstrap = FALSE, cband = FALSE)
  list(group = r$group, t = r$t, att = r$att, se = r$se, n = r$n)
}
att_gt_out <- list()
for (m in c("dr", "ipw", "reg")) for (cg in c("nevertreated", "notyettreated"))
  att_gt_out[[paste(m, cg, sep = "_")]] <- emit_attgt(m, cg)
write_json(att_gt_out, "tests/fixtures/cs_did/att_gt.json", digits = 12, auto_unbox = TRUE)

# ---- Per-cell DRDID influence functions: cell (g=4, base=3, t=4), never-treated ----
# dr -> drdid_panel ; ipw -> std_ipw_did_panel ; reg -> reg_did_panel
# (these are exactly what did::att_gt calls for each est_method on a 2-period panel cell).
cell <- subset(d, first_treat %in% c(0, 4) & period %in% c(3, 4))
c0 <- cell[cell$period == 3, c("unit", "y", "x1", "first_treat")]   # base period
c1 <- cell[cell$period == 4, c("unit", "y")]                        # outcome period
m  <- merge(c0, c1, by = "unit", suffixes = c("_0", "_1"))
m  <- m[order(m$unit), ]
D  <- as.integer(m$first_treat == 4)
X  <- model.matrix(~x1, data = m)
emit_if <- function(fit) list(att = fit$ATT, se = fit$se,
                              inf_func = as.numeric(fit$att.inf.func))
inf_out <- list(
  unit = m$unit,
  dr  = emit_if(drdid_panel(y1 = m$y_1, y0 = m$y_0, D = D, covariates = X, inffunc = TRUE)),
  ipw = emit_if(std_ipw_did_panel(y1 = m$y_1, y0 = m$y_0, D = D, covariates = X, inffunc = TRUE)),
  reg = emit_if(reg_did_panel(y1 = m$y_1, y0 = m$y_0, D = D, covariates = X, inffunc = TRUE))
)
write_json(inf_out, "tests/fixtures/cs_did/drdid_inffunc.json", digits = 12, auto_unbox = TRUE)

# ---- Aggregations: simple / dynamic / group / calendar, per est_method ----
# never-treated, varying base, anticipation 0. Structured under method keys so the
# shared aggregation-SE machinery (wif/get_agg_inf_func/getSE) is regression-frozen
# for ipw and reg too, not only the dr oracle (v1.5.6 hardening round 2, Fix #2).
emit_aggte <- function(method) {
  r <- att_gt(yname = "y", tname = "period", idname = "unit", gname = "first_treat",
              xformla = ~x1, data = d, est_method = method,
              control_group = "nevertreated", base_period = "varying",
              anticipation = 0, bstrap = FALSE, cband = FALSE)
  agg <- function(type) {
    a <- aggte(r, type = type, bstrap = FALSE)
    list(overall = a$overall.att, overall_se = a$overall.se,
         egt = a$egt, att_egt = a$att.egt, se_egt = a$se.egt)
  }
  list(simple = agg("simple"), dynamic = agg("dynamic"),
       group = agg("group"), calendar = agg("calendar"))
}
aggte_out <- list()
for (m in c("dr", "ipw", "reg")) aggte_out[[m]] <- emit_aggte(m)
write_json(aggte_out, "tests/fixtures/cs_did/aggte.json", digits = 12, auto_unbox = TRUE)

# ---- Clustered CRVE oracle (deterministic, built from inf functions) ----
# did forces bstrap=TRUE with clustervars, so there is no native analytical
# clustered SE. We build a deterministic cluster-robust SE from the SAME
# influence functions did exposes (already 1e-8-validated unclustered):
#   S_c = sum_{i in c} psi_i ;  se = sqrt(sum_c S_c^2) / N   (N = #entities).
# Unclustered identity: each entity its own cluster => reduces to did's getSE.
# (Verified: with cl = 1..N this reproduces did's native overall.se / se.egt
#  to machine precision for dr dynamic, confirming both the formula and the
#  inf-func row order used below.)
#
# IMPORTANT deviations from the original plan snippet, made after empirically
# probing did 2.5.0 internals (the unmodified snippet would error):
#  (1) Accessor names. did 2.5.0 does NOT expose $overall.inf.func /
#      $egt.inf.func. Per aggregation type the names differ:
#        simple   -> simple.att            (overall only, no per-egt)
#        dynamic  -> dynamic.inf.func      + dynamic.inf.func.e   (N x n_egt)
#        group    -> selective.inf.func    + selective.inf.func.g (N x n_egt)
#        calendar -> calendar.inf.func     + calendar.inf.func.t  (N x n_egt)
#      We therefore pick them GENERICALLY: the overall IF is the element that
#      is a length-N vector (1 column); the per-egt IF is the element whose
#      column count equals length(a$egt) (NULL when absent, e.g. simple).
#  (2) Row order. att_gt/aggte sort entities into cohort blocks, so the IF
#      rows are in unique(r$DIDparams$data$unit) order (== time_invariant_data
#      $unit), NOT sort(unique(unit)). We align the cluster id vector to THAT
#      order. Verified length(cl) == N == length(overall IF) before emitting.
cluster_of_unit <- unique(d[, c("unit", "cluster")])
cluster_of_unit <- cluster_of_unit[order(cluster_of_unit$unit), ]
emit_clustered <- function(method) {
  r <- att_gt(yname = "y", tname = "period", idname = "unit", gname = "first_treat",
              xformla = ~x1, data = d, est_method = method,
              control_group = "nevertreated", base_period = "varying",
              anticipation = 0, bstrap = FALSE, cband = FALSE)
  # Entity row order of the influence functions (verified == IF row order).
  ids <- unique(r$DIDparams$data$unit)
  N   <- length(ids)
  cl  <- cluster_of_unit$cluster[match(ids, cluster_of_unit$unit)]
  stopifnot(length(cl) == N, !any(is.na(cl)))
  crve <- function(inf) {                       # inf: length-N entity IF
    inf <- as.numeric(inf)
    stopifnot(length(inf) == N)                 # row alignment guard
    S <- rowsum(inf, cl)                         # (n_clusters,)
    sqrt(sum(S^2)) / N
  }
  # Generic IF picker: overall = the length-N vector element; per-egt = the
  # element with ncol == length(egt) (NULL when none, e.g. type="simple").
  pick_overall <- function(iflist) {
    for (nm in names(iflist)) {
      m <- as.matrix(iflist[[nm]])
      if (ncol(m) == 1L && nrow(m) == N) return(as.numeric(m))
    }
    NULL
  }
  pick_egt <- function(iflist, n_egt) {
    if (is.null(n_egt) || n_egt < 1L) return(NULL)
    for (nm in names(iflist)) {
      m <- as.matrix(iflist[[nm]])
      if (nrow(m) == N && ncol(m) == n_egt) return(m)
    }
    NULL
  }
  agg <- function(type) {
    a <- aggte(r, type = type, bstrap = FALSE)
    overall_if <- pick_overall(a$inf.function)
    n_egt <- if (is.null(a$egt)) 0L else length(a$egt)
    egt_if <- pick_egt(a$inf.function, n_egt)    # matrix (N x n_egt) or NULL
    se_egt <- if (is.null(egt_if)) NULL else apply(egt_if, 2, crve)
    list(overall = a$overall.att,
         overall_se = if (is.null(overall_if)) NULL else crve(overall_if),
         egt = a$egt, se_egt = se_egt)
  }
  # per-cell clustered CRVE SE: crve() of each att_gt influence-function column
  # (r$inffunc is N x K, columns aligned to r$group / r$t).
  att_gt_se <- apply(r$inffunc, 2, crve)
  list(n = N, n_clusters = length(unique(cl)),
       simple = agg("simple"), dynamic = agg("dynamic"),
       group = agg("group"), calendar = agg("calendar"),
       att_gt = list(group = r$group, t = r$t, se = att_gt_se))
}
clustered_out <- list()
for (m in c("dr", "ipw", "reg")) clustered_out[[m]] <- emit_clustered(m)
write_json(clustered_out, "tests/fixtures/cs_did/aggte_clustered.json",
           digits = 12, auto_unbox = TRUE, null = "null")

cat("Fixtures written: att_gt.json, drdid_inffunc.json, aggte.json, aggte_clustered.json\n")
