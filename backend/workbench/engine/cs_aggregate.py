from __future__ import annotations

import numpy as np

# Aggregations of ATT(g,t) into the four did::aggte summaries (point estimates).
# Faithful port of did:::compute.aggte weighting:
#   pg (cohort weight) = mean(weights.ind * (gvar == g)) = n_g / N. In every R
#   aggregate the pg's enter only through ratios over a keeper set that shares the
#   common 1/N factor, so cohort sizes n_g (bundle.weights["n_g"]) reproduce R
#   exactly. Eligibility of a cell is decided by the valid-mask (m["valid"]).
#
#   group:    egt(g)  = mean of ATT(g,t) over valid post cells (event_time >= 0).
#             overall = sum_g n_g*egt(g) / sum_g n_g over groups with >=1 valid post cell.
#   dynamic:  egt(e)  = sum_{g in G_e} (n_g/sum n_h) ATT(g,g+e), G_e = valid cells at e.
#             overall = mean of egt(e) over e >= 0 (the reported post event-times).
#   calendar: egt(t)  = sum_{g<=t, valid} (n_g/sum n_h) ATT(g,t), t >= min cohort.
#             overall = mean of egt(t).
#   simple:   overall = sum_{valid, t>=g} n_g ATT(g,t) / sum_{valid, t>=g} n_g
#             (cell-weighted mean over ALL post cells; no per-label output).

VALID_KINDS = ("simple", "dynamic", "group", "calendar")


# ---------------------------------------------------------------------------
# Aggregation influence functions (port of did:::wif / get_agg_inf_func / getSE)
#
# R works entirely at the INDIVIDUAL (entity) level: inffunc1 has one row per
# sampling unit, `wif` builds an (N, |keepers|) weight-influence matrix from each
# entity's cohort membership, and getSE clusters via rowsum() only at the very end.
# We mirror that: build the per-label IF at the entity-row level of
# bundle.influence_func, then (when clustered) sum within clusters before the SE.
#
# pg (cohort share) = mean(weights.ind * (gvar == g)) over ALL N entities = n_g/N
# (N includes never-treated). This is NOT bundle.weights["p_g"], which divides by
# the treated total — so we recompute pg here as n_g / n_total.
# ---------------------------------------------------------------------------


def _pg_map(bundle):
    """Cohort shares pg[g] = n_g / N (R's mean(weights.ind*(gvar==g)))."""
    n_total = float(bundle.aux["n_total"])
    if n_total == 0.0:
        raise CSAggregateError("CS_AGG_DEGENERATE: zero total sampling units.")
    return {float(g): float(n) / n_total for g, n in bundle.weights["n_g"].items()}


def _wif(keeper_groups, pg_map, row_cohort):
    """Port of did:::wif. Returns the (N, len(keepers)) weight-influence matrix.

      Spg      = sum_k pg[g_k]
      centered[:,j] = 1{row_cohort == g_j} - pg[g_j]          (weights.ind == 1)
      if1      = centered / Spg
      if2      = rowSums(centered) outer (pg[keepers] / Spg^2)
      wif      = if1 - if2
    """
    pg_keep = np.array([pg_map[g] for g in keeper_groups], dtype=float)
    Spg = float(pg_keep.sum())
    # centered: (N, J)
    centered = (row_cohort[:, None] == np.array(keeper_groups)[None, :]).astype(float)
    centered -= pg_keep[None, :]
    if1 = centered / Spg
    if2 = centered.sum(axis=1)[:, None] * (pg_keep / (Spg ** 2))[None, :]
    return if1 - if2


def _agg_inf_func(influence_func, whichones, w_agg, att, wif):
    """Port of did:::get_agg_inf_func.

      thisinffunc = inffunc1[, whichones] %*% w_agg  + wif %*% att[whichones]
    Operates at the entity-row level; clustering/SE happen downstream.
    """
    comp = influence_func[:, whichones] @ np.asarray(w_agg, dtype=float)
    if wif is not None:
        comp = comp + wif @ np.asarray([att[k] for k in whichones], dtype=float)
    return comp


def _se(entity_if, row_cluster, n_total):
    """Port of did:::getSE (analytical, bstrap=FALSE).

    Unclustered: sqrt(mean(if^2)/n) = sqrt(sum(if^2)) / n.
    Extra cluster: S = rowsum(if, cv); sqrt(sum(S^2)) / n.  Here n is the number of
    INDIVIDUALS (entity rows), matching R (getSE's n = length(thisinffunc)).
    """
    n = float(n_total)
    uniq = np.unique(row_cluster)
    if len(uniq) == len(row_cluster):
        clustered = entity_if            # identity (cluster == entity)
    else:
        clustered = np.array([entity_if[row_cluster == c].sum() for c in uniq])
    return float(np.sqrt(np.sum(clustered ** 2)) / n)


class CSAggregateError(ValueError):
    """CS_AGG_* failure (bad kind / degenerate aggregation)."""


def _valid_cells(bundle):
    """List of (k, g, t, event_time, att) for valid cells, in metadata order."""
    out = []
    for k, m in enumerate(bundle.cell_metadata):
        if m.get("valid"):
            out.append((k, float(m["g"]), float(m["t"]),
                        float(m["event_time"]), float(bundle.estimates[k])))
    return out


def _normalize(raw: np.ndarray, *, ctx: str) -> np.ndarray:
    """Divide weights by their sum, raising CS_AGG_DEGENERATE on a zero denominator
    (rather than producing silent nan/inf)."""
    total = float(raw.sum())
    if total == 0.0:
        raise CSAggregateError(
            f"CS_AGG_DEGENERATE: zero cohort-weight denominator while aggregating {ctx}.")
    return raw / total


def aggregate(bundle, kind: str) -> dict:
    """Aggregate ATT(g,t) per did::aggte. Returns point estimates only (no SE).

    Returns dict:
      {"kind", "overall": float|None, "label": [...], "estimate": [...],
       "weights_used": {...}, "overall_weights": {...}}

    `weights_used` and `overall_weights` express each aggregate as an explicit
    linear combination of CELL ATTs so Task 8 can rebuild each aggregate's
    influence function (plus its own estimand-weight / wif correction term).

    `weights_used` (per-label decomposition) has the SAME shape for every kind:
        {label: {"cells": [k...], "att_weights": [w...]}}
    where each `k` indexes a column of `bundle.influence_func` (and an entry of
    `bundle.estimates`); the per-label estimate is `sum_j w_j * estimates[cells_j]`,
    and the weights sum to 1 within each label. For `simple` it is empty (no labels).

    `overall_weights` describes how `overall` is formed and has THREE kind-specific
    shapes (all intentional — key off `kind`):
      - simple:            {"cells": [k...],  "att_weights": [w...]}
            overall is a direct n_g-weighted combination of cell ATTs (no labels).
      - dynamic, calendar: {"labels": [...],  "label_weights": [w...]}
            overall is a (uniform) weighted mean of the per-label estimates; combine
            with `weights_used[label]` to expand back to cells.
      - group:             {"groups": [g...], "group_weights": [w...]}
            overall is TWO-STAGE: sum_g group_weights[g] * (the within-group mean
            given by weights_used[g]["att_weights"] over weights_used[g]["cells"]).
    """
    if kind not in VALID_KINDS:
        raise CSAggregateError(f"CS_AGG_BAD_KIND: '{kind}' not in {VALID_KINDS}")

    n_g = {float(g): float(n) for g, n in bundle.weights["n_g"].items()}
    cells = _valid_cells(bundle)
    # Upstream invariant: every valid cell's cohort appears in weights["n_g"].
    # Guard it explicitly so a future divergence raises a structured CS_AGG_* error
    # instead of a bare KeyError mid-aggregation.
    missing = sorted({g for (_, g, _, _, _) in cells if g not in n_g})
    if missing:
        raise CSAggregateError(
            f"CS_AGG_DEGENERATE: valid cell cohort(s) {missing} absent from "
            "bundle.weights['n_g']; cannot weight aggregation.")

    if kind == "simple":
        out = _simple(cells, n_g)
    elif kind == "group":
        out = _group(cells, n_g)
    elif kind == "dynamic":
        out = _dynamic(cells, n_g)
    elif kind == "calendar":
        out = _calendar(cells, n_g)
    else:
        raise CSAggregateError(f"CS_AGG_BAD_KIND: '{kind}'")  # unreachable
    _attach_influence(bundle, out)
    return out


def _attach_influence(bundle, out) -> None:
    """Augment a point-estimate result with analytical influence functions + SE.

    Adds (always present):
      "component_if": (N, n_labels) entity-row IF of the per-label estimates
                      (empty (N,0) for `simple`, which has no labels).
      "overall_if":   (N,) entity-row IF of the overall estimate (None if overall None).
      "se":           per-label analytical SE (aligned with out["label"]).
      "overall_se":   scalar overall SE (None if overall None).
    Task 9 (multiplier bootstrap) draws on component_if / overall_if directly.
    """
    kind = out["kind"]
    IF = bundle.influence_func                       # (N, K) entity rows
    att = bundle.estimates
    N = int(bundle.aux["n_total"])
    row_cohort = bundle.aux["row_cohort"]
    row_cluster = bundle.aux["row_cluster"]
    pg = _pg_map(bundle)
    cell_g = [float(m["g"]) for m in bundle.cell_metadata]

    def cohorts_of(ks):
        return [cell_g[k] for k in ks]

    # ----- per-label component IFs --------------------------------------------
    comp_cols, se_list = [], []
    if kind == "simple":
        out["component_if"] = np.zeros((N, 0))
        out["se"] = []
    else:
        for lab in out["label"]:
            wu = out["weights_used"][lab]
            ks, w = wu["cells"], np.array(wu["att_weights"], dtype=float)
            if kind == "group":
                # within-group: uniform weights, NO weight-estimation correction
                # (R passes wif=NULL for selective.se.inner) — the group share is
                # not re-estimated inside a single group's event-time mean.
                wif = None
            else:
                # dynamic / calendar: weights are pg-shares over the keeper cohorts;
                # those shares are estimated -> include R's wif term.
                wif = _wif(cohorts_of(ks), pg, row_cohort)
            comp = _agg_inf_func(IF, ks, w, att, wif)
            comp_cols.append(comp)
            se_list.append(_se(comp, row_cluster, N))
        out["component_if"] = (np.column_stack(comp_cols) if comp_cols
                               else np.zeros((N, 0)))
        out["se"] = se_list

    # ----- overall IF ----------------------------------------------------------
    if out["overall"] is None:
        out["overall_if"] = None
        out["overall_se"] = None
        return
    ow = out["overall_weights"]
    if kind == "simple":
        ks = ow["cells"]
        w = np.array(ow["att_weights"], dtype=float)
        wif = _wif(cohorts_of(ks), pg, row_cohort)
        overall_if = _agg_inf_func(IF, ks, w, att, wif)
    elif kind == "group":
        # two-stage: overall = sum_g group_weight[g] * within-group-mean(g).
        # R forms this directly over the GROUP-level estimates with a group-level
        # wif (keepers = the groups, pg = group shares pgg).  Equivalent to
        # composing the within-group (uniform, wif=NULL) IFs by the group weights,
        # then adding the group-level weight-correction term.
        groups = ow["groups"]
        gw = np.array(ow["group_weights"], dtype=float)
        # within-group component IFs (already wif=NULL), indexed by label order
        lab_idx = {lab: i for i, lab in enumerate(out["label"])}
        comp_by_group = out["component_if"]
        first_stage = sum(gw[j] * comp_by_group[:, lab_idx[g]]
                          for j, g in enumerate(groups))
        # group-level wif: keepers are the groups themselves; cohorts = the groups;
        # att = within-group means (the group label estimates).
        grp_att = np.array([out["estimate"][lab_idx[g]] for g in groups], dtype=float)
        wif = _wif([float(g) for g in groups], pg, row_cohort)
        overall_if = first_stage + wif @ grp_att
    else:  # dynamic / calendar: uniform mean of per-label estimates, wif=NULL
        labs = ow["labels"]
        lw = np.array(ow["label_weights"], dtype=float)
        lab_idx = {lab: i for i, lab in enumerate(out["label"])}
        overall_if = sum(lw[j] * out["component_if"][:, lab_idx[lab]]
                         for j, lab in enumerate(labs))
    out["overall_if"] = overall_if
    out["overall_se"] = _se(overall_if, row_cluster, N)


def _simple(cells, n_g) -> dict:
    keepers = [(k, g, att) for (k, g, t, e, att) in cells if t >= g]  # event_time >= 0
    if not keepers:
        return {"kind": "simple", "overall": None, "label": [], "estimate": [],
                "weights_used": {}, "overall_weights": {"cells": [], "att_weights": []}}
    ks = [k for (k, g, att) in keepers]
    raw = np.array([n_g[g] for (k, g, att) in keepers], dtype=float)
    w = _normalize(raw, ctx="simple overall")
    atts = np.array([att for (k, g, att) in keepers], dtype=float)
    overall = float(np.dot(w, atts))
    return {"kind": "simple", "overall": overall, "label": [], "estimate": [],
            "weights_used": {},
            "overall_weights": {"cells": ks, "att_weights": w.tolist()}}


def _group(cells, n_g) -> dict:
    groups = sorted({g for (k, g, t, e, att) in cells})
    labels, estimates, weights_used = [], [], {}
    group_theta, group_n = {}, {}
    for g in groups:
        post = [(k, att) for (k, gg, t, e, att) in cells if gg == g and t >= g]
        if not post:
            continue
        ks = [k for (k, att) in post]
        atts = np.array([att for (k, att) in post], dtype=float)
        w = np.full(len(post), 1.0 / len(post))  # mean over post cells
        theta = float(np.dot(w, atts))
        labels.append(g)
        estimates.append(theta)
        weights_used[g] = {"cells": ks, "att_weights": w.tolist()}
        group_theta[g] = theta
        group_n[g] = n_g[g]
    # overall = sum_g n_g theta(g) / sum_g n_g over groups with >=1 post cell
    if not labels:
        overall = None
        overall_weights = {"groups": [], "group_weights": []}
    else:
        tot = sum(group_n.values())
        if tot == 0.0:
            raise CSAggregateError(
                "CS_AGG_DEGENERATE: zero cohort-weight denominator while aggregating "
                "group overall.")
        gw = {g: group_n[g] / tot for g in labels}
        overall = float(sum(gw[g] * group_theta[g] for g in labels))
        overall_weights = {"groups": list(labels),
                           "group_weights": [gw[g] for g in labels]}
    return {"kind": "group", "overall": overall, "label": labels,
            "estimate": estimates, "weights_used": weights_used,
            "overall_weights": overall_weights}


def _dynamic(cells, n_g) -> dict:
    events = sorted({e for (k, g, t, e, att) in cells})
    labels, estimates, weights_used = [], [], {}
    theta_e = {}
    for e in events:
        sel = [(k, g, att) for (k, g, t, ee, att) in cells if ee == e]
        ks = [k for (k, g, att) in sel]
        raw = np.array([n_g[g] for (k, g, att) in sel], dtype=float)
        w = _normalize(raw, ctx=f"dynamic event-time {e}")
        atts = np.array([att for (k, g, att) in sel], dtype=float)
        theta = float(np.dot(w, atts))
        labels.append(e)
        estimates.append(theta)
        weights_used[e] = {"cells": ks, "att_weights": w.tolist()}
        theta_e[e] = theta
    post = [e for e in events if e >= 0]
    if post:
        overall = float(np.mean([theta_e[e] for e in post]))
        overall_weights = {"labels": post,
                           "label_weights": [1.0 / len(post)] * len(post)}
    else:
        overall = None
        overall_weights = {"labels": [], "label_weights": []}
    return {"kind": "dynamic", "overall": overall, "label": labels,
            "estimate": estimates, "weights_used": weights_used,
            "overall_weights": overall_weights}


def _calendar(cells, n_g) -> dict:
    min_g = min(g for (k, g, t, e, att) in cells)
    periods = sorted({t for (k, g, t, e, att) in cells if t >= min_g})
    labels, estimates, weights_used = [], [], {}
    theta_t = {}
    for t in periods:
        sel = [(k, g, att) for (k, g, tt, e, att) in cells if tt == t and g <= t]
        if not sel:
            continue
        ks = [k for (k, g, att) in sel]
        raw = np.array([n_g[g] for (k, g, att) in sel], dtype=float)
        w = _normalize(raw, ctx=f"calendar period {t}")
        atts = np.array([att for (k, g, att) in sel], dtype=float)
        theta = float(np.dot(w, atts))
        labels.append(t)
        estimates.append(theta)
        weights_used[t] = {"cells": ks, "att_weights": w.tolist()}
        theta_t[t] = theta
    if labels:
        overall = float(np.mean([theta_t[t] for t in labels]))
        overall_weights = {"labels": list(labels),
                           "label_weights": [1.0 / len(labels)] * len(labels)}
    else:
        overall = None
        overall_weights = {"labels": [], "label_weights": []}
    return {"kind": "calendar", "overall": overall, "label": labels,
            "estimate": estimates, "weights_used": weights_used,
            "overall_weights": overall_weights}
