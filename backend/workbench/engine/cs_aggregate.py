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
        return _simple(cells, n_g)
    if kind == "group":
        return _group(cells, n_g)
    if kind == "dynamic":
        return _dynamic(cells, n_g)
    if kind == "calendar":
        return _calendar(cells, n_g)
    raise CSAggregateError(f"CS_AGG_BAD_KIND: '{kind}'")  # unreachable


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
