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

cat("Fixtures written: att_gt.json, drdid_inffunc.json, aggte.json\n")
