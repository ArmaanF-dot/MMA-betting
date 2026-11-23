"""Round 5 tests: softer feature selection, age x style curves, and finish recalibration. Development folds only.

Softer selection is judged out of sample in time: groups are chosen on the 2015-2021 folds only, then every configuration is
scored on 2022 to the holdout start. The current hard-selected set was chosen on all development folds, so it has a small
advantage, which makes any win by a challenger conservative.
"""
import json

import numpy as np

from ufcmodel.eval import metrics as M
from ufcmodel.eval import phase10 as P
from ufcmodel.eval.phase8 import round_label, six_label, sim_walk_forward
from ufcmodel.eval.phase10 import Data, _arr, holdout_start, make_folds, walk_forward
from ufcmodel.features.asof import GROUPS, build_features, load_raw
from ufcmodel.judging.round_score import load_decisions

SPLIT = "2022-01-01"


def _cols(groups):
    return [c for g in groups for c in GROUPS[g]]


def softer(con, out_json=None) -> str:
    raw, statics = load_raw(con)
    d = Data(build_features(raw, statics))
    folds = make_folds(holdout_start(d.rows), False)
    sel_folds = [f for f in folds if f[2] <= SPLIT]
    cur = json.load(open("config/feature_groups.json"))["keep"]
    ev = [i for i in np.where(d.dec & (d.date >= SPLIT) & (d.date < folds[-1][2]))[0]]
    y = d.y[ev]
    sel_idx = [i for i in np.where(d.dec & (d.date >= folds[0][1]) & (d.date < SPLIT))[0]]
    ysel = d.y[sel_idx]
    # relaxed greedy on the selection period: add the best group while it lowers log loss by at least 0.0005 (no interval rule)
    chosen, cur_loss, remaining, log = [], np.full(len(sel_idx), np.log(2)), list(GROUPS), []
    for _ in range(9):
        best = None
        for g in remaining:
            pr, _ = walk_forward("lr", _cols(chosen + [g]), d, sel_folds, (2010, 0.1))
            loss = M.per_bout_log_loss(_arr(d, pr, sel_idx), ysel)
            if best is None or loss.mean() < best[1].mean():
                best = (g, loss)
        gain = cur_loss.mean() - best[1].mean()
        log.append((best[0], best[1].mean(), gain))
        if gain < 0.0005:
            break
        chosen.append(best[0])
        cur_loss = best[1]
        remaining.remove(best[0])
    configs = {"current (hard rule, 3 groups)": ("lr", _cols(cur), None), "current + age_style": ("lr", _cols(cur + ["age_style"]), None),
               f"relaxed greedy ({len(chosen)} groups)": ("lr", _cols(chosen), None), "all groups, ridge": ("lr", _cols(GROUPS), "ridge"),
               "all groups, LightGBM": ("lgbm", _cols(GROUPS), None), "current, LightGBM": ("lgbm", _cols(cur), None)}
    res, base = {}, None
    for name, (kind, cols, mode) in configs.items():
        if mode == "ridge":   # strongest shrinkage: C picked per fold from a smaller grid
            old = P.C_GRID
            P.C_GRID = (0.001, 0.003, 0.01, 0.03)
            pr, _ = walk_forward("lr", cols, d, folds)
            P.C_GRID = old
        else:
            pr, _ = walk_forward(kind, cols, d, folds, (2010, 0.1))
        res[name] = M.per_bout_log_loss(_arr(d, pr, ev), y)
        base = res[name] if base is None else base
    L = ["# Softer feature selection and age x style curves", "",
         f"Groups chosen on the {sel_folds[0][1][:4]}-{int(SPLIT[:4]) - 1} folds only; scored on {SPLIT} to {folds[-1][2]} ({len(ev)} decisive bouts). "
         "Difference = configuration minus current, paired bootstrap 95% interval; negative is better.", "",
         f"Relaxed greedy picked (selection period): {', '.join(chosen)}. Steps: " + "; ".join(f"{g} {ll:.4f} ({gn:+.4f})" for g, ll, gn in log), "",
         "| Configuration | Log loss (scoring period) | Difference vs current [95% CI] | Verdict |", "|---|---|---|---|"]
    best_name = None
    for name, loss in res.items():
        if loss is base:
            L.append(f"| {name} | {loss.mean():.4f} | | |")
            continue
        m, lo, hi = M.paired_bootstrap_diff(loss, base)
        ok = hi < 0
        L.append(f"| {name} | {loss.mean():.4f} | {m:+.4f} [{lo:+.4f}, {hi:+.4f}] | {'better' if ok else ('worse' if lo > 0 else 'no clear difference')} |")
        if ok and (best_name is None or loss.mean() < res[best_name].mean()):
            best_name = name
    L += ["", f"Adopt: {best_name or 'nothing; the current selection stands'}.", ""]
    if out_json:
        json.dump({"adopt": best_name, "relaxed_groups": chosen}, open(out_json, "w"))
    return "\n".join(L)


def _mask(p, sched):
    p = p.copy()
    if sched != 5:
        p[3:5] = 0
    return p / p.sum()


def _metrics(d, sim, idx):
    i6 = [i for i in idx if i in sim and six_label(d.rows[i]) is not None]
    ir = [i for i in idx if i in sim and round_label(d.rows[i]) is not None]
    ir = [i for i in ir if not (d.rows[i]["sched"] != 5 and round_label(d.rows[i]) in (3, 4))]
    y6 = np.array([six_label(d.rows[i]) for i in i6])
    p6 = np.array([sim[i]["six"] / sim[i]["six"].sum() for i in i6])
    yr = np.array([round_label(d.rows[i]) for i in ir])
    pr = np.array([_mask(sim[i]["round"], d.rows[i]["sched"]) for i in ir])
    yd = (yr == 5).astype(float)
    return dict(ll6=-np.log(np.clip(p6[np.arange(len(y6)), y6], 1e-9, 1)), llr=-np.log(np.clip(pr[np.arange(len(yr)), yr], 1e-9, 1)),
                lld=M.per_bout_log_loss(pr[:, 5], yd), ece=M.ece(pr[:, 5], yd), exp=float(pr[:, 5].mean()), obs=float(yd.mean()))


def finish_variants(con):
    raw, statics = load_raw(con)
    d = Data(build_features(raw, statics))
    folds = make_folds(holdout_start(d.rows), False)
    dec = load_decisions(con)
    idx = [i for i in np.where(d.date >= folds[0][1])[0] if d.date[i] < folds[-1][2]]
    variants = {"current (last 300 bouts)": {}, "last 150 bouts": dict(calib_bouts=150), "300 + division multipliers": dict(div_adjust=True),
                "150 + division multipliers": dict(calib_bouts=150, div_adjust=True)}
    out = {name: _metrics(d, sim_walk_forward(d, folds, dec, **kw), idx) for name, kw in variants.items()}
    base = out["current (last 300 bouts)"]
    L = ["# Finish recalibration test", "", f"Development folds 2015 to {folds[-1][2]}. Simulator variants differ only in how the finish scalars "
         "are calibrated. Differences are against the current setting (paired bootstrap, negative is better).", "",
         "| Variant | 6-class winner x method | Round of finish | Goes the distance | ECE (distance) | Expected vs actual distance rate |",
         "|---|---|---|---|---|---|"]
    best = None
    for name, m in out.items():
        cells = []
        for k in ("ll6", "llr", "lld"):
            if m is base:
                cells.append(f"{m[k].mean():.4f}")
            else:
                dm, lo, hi = M.paired_bootstrap_diff(m[k], base[k])
                cells.append(f"{m[k].mean():.4f} ({dm:+.4f} [{lo:+.4f}, {hi:+.4f}])")
        L.append(f"| {name} | " + " | ".join(cells) + f" | {m['ece']:.3f} | {m['exp']:.1%} vs {m['obs']:.1%} |")
        if m is not base:
            ok = M.paired_bootstrap_diff(m["lld"], base["lld"])[2] < 0 and M.paired_bootstrap_diff(m["llr"], base["llr"])[2] < 0
            if ok and (best is None or m["lld"].mean() < out[best]["lld"].mean()):
                best = name
    L += ["", f"Adopt: {best or 'nothing; the current calibration stands'} (needs both round-of-finish and goes-the-distance log loss to improve, "
          "each with an interval below zero).", ""]
    return "\n".join(L), best, variants.get(best)
