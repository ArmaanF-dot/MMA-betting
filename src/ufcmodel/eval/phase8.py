"""Phase 8 evaluation: the simulator (M4) walk-forward, direct method/round models as its rivals, and posterior predictive checks.

Everything is walk-forward: for each fold the judging weights, the two finish scalars and the direct models are fit on bouts
before the fold only.
"""
from collections import defaultdict
from datetime import date

import lightgbm as lgb
import numpy as np

from ufcmodel.eval import metrics as M
from ufcmodel.features.asof import ALL_COLS, ANTI_IDX
from ufcmodel.judging.round_score import fit_judging
from ufcmodel.sim.simulator import Params, calibrate, simulate

N_SIMS = 800
CALIB_BOUTS = 300
PAIR = ["sig_for", "sig_against", "power", "chin", "damage", "td_for", "td_against", "sub_for", "sub_against", "ctrl_for",
        "pace_slope", "ko_win", "sub_win", "ko_loss", "sub_loss", "age", "dec_win", "avg_minutes"]
SIX = ["A_KO", "A_SUB", "A_DEC", "B_KO", "B_SUB", "B_DEC"]
ROUNDS = ["R1", "R2", "R3", "R4", "R5", "Distance"]
MCLF = dict(n_estimators=150, learning_rate=0.04, num_leaves=6, min_child_samples=60, subsample=0.8, subsample_freq=1,
            colsample_bytree=0.7, reg_lambda=8.0, random_state=0, verbose=-1, n_jobs=1)


def _cat(m):
    return {"KO/TKO": 0, "Submission": 1, "Decision": 2}.get(m)


def six_label(r):
    c = _cat(r["method"])
    if c is None or r["y"] not in (0.0, 1.0):
        return None
    return c if r["y"] == 1.0 else 3 + c


def round_label(r):
    c = _cat(r["method"])
    if c is None:
        return None
    if c == 2:
        return 5
    return int(r["end_round"]) - 1 if r["end_round"] and 1 <= r["end_round"] <= 5 else None


def finish_ratios(rows, p, seed=0, div_k=20, weights=None):
    """Per-division finish multiplier: observed finish rate over the simulator's, shrunk to the global level with div_k
    pseudo-bouts. `rows` are recent feature rows with a known method. Adopted after the round-5 test (see decisions.md).
    `weights` (one per row, default 1) lets recent bouts count more, so the multipliers follow a drift in finish rates."""
    acc, rg = defaultdict(lambda: [0.0, 0.0, 0.0]), np.random.default_rng(seed + 1)
    for k, r in enumerate(rows):
        w = 1.0 if weights is None else float(weights[k])
        acc[r["wc"]][0] += w * float(r["method"] in ("KO/TKO", "Submission"))
        acc[r["wc"]][1] += w * (1 - simulate(r["fa"], r["fb"], r["g15"], r["sched"], p, 300, rg)["p_distance"])
        acc[r["wc"]][2] += w
    n_all = sum(v[2] for v in acc.values())
    mo, ms = sum(v[0] for v in acc.values()) / n_all, sum(v[1] for v in acc.values()) / n_all
    return {wc: float(np.clip((v[0] + div_k * mo) / (v[1] + div_k * ms), 0.6, 1.6)) for wc, v in acc.items()}


def with_ratio(p, ratio, wc):
    m = ratio.get(wc, 1.0) if ratio else 1.0
    return p if m == 1.0 else Params(**{**p.__dict__, "c_ko": p.c_ko * m, "c_sub": min(p.c_sub * m, 0.99)})


def sim_walk_forward(d, folds, decisions, n_sims=N_SIMS, seed=0, calib_bouts=150, div_adjust=True, div_bouts=1200, div_k=20, half_life=None):
    out = {}
    for name, start, end in folds:
        w, kappa, _ = fit_judging(decisions, start)
        pool = [i for i in np.where(d.date < start)[0]
                if d.rows[i]["stats_missing"] == 0 and d.rows[i]["method"] in ("KO/TKO", "Submission", "Decision") and d.rows[i]["sched"]]
        sample = [d.rows[i] for i in pool[-calib_bouts:]]
        p = calibrate(sample, Params(w=w, kappa=kappa), seed=seed) if len(sample) >= 100 else Params(w=w, kappa=kappa)
        ratio = {}
        if div_adjust and len(pool) >= 300:
            recent = pool[-div_bouts:]
            wts = None if not half_life else [0.5 ** ((date.fromisoformat(start) - date.fromisoformat(d.date[i])).days / half_life) for i in recent]
            ratio = finish_ratios([d.rows[i] for i in recent], p, seed, div_k, wts)
        for i in np.where(d.mask(start, end))[0]:
            r = d.rows[i]
            rng = np.random.default_rng(abs(hash(r["bout_id"])) % (2**32))
            o = simulate(r["fa"], r["fb"], r["g15"], r["sched"], with_ratio(p, ratio, r["wc"]), n_sims, rng)
            decisive = o["p_a"] + o["p_b"]
            o["p"] = o["p_a"] / decisive if decisive > 0 else 0.5
            # strike checks are against fights that went the distance, so use only the simulations that did
            keep = o["dec"] if o["dec"].sum() >= 30 else np.ones_like(o["dec"])
            o["sig_q"] = (np.percentile(o["sig_a"][keep], [10, 90]), np.percentile(o["sig_b"][keep], [10, 90]))
            o["sig_mean"] = (float(o["sig_a"][keep].mean()), float(o["sig_b"][keep].mean()))
            for k in ("sig_a", "sig_b", "dec", "rounds_alive"):
                o.pop(k)
            out[i] = o
        out.setdefault("params", {})[name] = (round(p.c_ko, 3), round(p.c_sub, 3), round(p.decay, 2), round(p.vol, 2), p.sigma, np.round(p.w, 2).tolist(), kappa)
    return out


def _pair_block(rows):
    block = []
    for r in rows:
        v = []
        for k in PAIR:
            a, b = r["fa"][k], r["fb"][k]
            v += [a + b, abs(a - b)]
        block.append(v)
    return np.array(block, float)


def _flip_six(y):
    return (y + 3) % 6


def direct_outcomes(d, folds, window=2005):
    """Direct multiclass models. six-class (winner x method) is symmetric by augmentation; round model is orientation-free."""
    P = _pair_block(d.rows)
    X_full = np.hstack([d.X, P])
    anti = np.zeros(X_full.shape[1], bool)
    anti[ANTI_IDX] = True
    sym_idx = [i for i in range(d.X.shape[1]) if i not in set(ANTI_IDX)] + list(range(d.X.shape[1], X_full.shape[1]))
    y6 = np.array([(-1 if (l := six_label(r)) is None else l) for r in d.rows])
    yr = np.array([(-1 if (l := round_label(r)) is None else l) for r in d.rows])
    six, rnd = {}, {}
    for name, start, end in folds:
        te = np.where(d.mask(start, end))[0]
        tr = np.where((d.year >= window) & (d.date < start))[0]
        t6 = tr[y6[tr] >= 0]
        Xa = X_full[t6]
        Xf = Xa.copy()
        Xf[:, anti] *= -1
        m6 = lgb.LGBMClassifier(objective="multiclass", **MCLF).fit(np.vstack([Xa, Xf]), np.concatenate([y6[t6], _flip_six(y6[t6])]))
        Xt = X_full[te]
        Xtf = Xt.copy()
        Xtf[:, anti] *= -1
        p1 = m6.predict_proba(Xt)
        p2 = m6.predict_proba(Xtf)[:, _flip_six(np.arange(6))]
        pm = (p1 + p2) / 2
        tr_r = tr[yr[tr] >= 0]
        mr = lgb.LGBMClassifier(objective="multiclass", **MCLF).fit(X_full[tr_r][:, sym_idx], yr[tr_r])
        pr = np.zeros((len(te), 6))
        pr[:, mr.classes_] = mr.predict_proba(Xt[:, sym_idx])
        for k, i in enumerate(te):
            six[i], rnd[i] = pm[k] / pm[k].sum(), pr[k]
    return six, rnd


def base_rates(d, folds, window=2005):
    six, rnd, dist = {}, {}, {}
    for name, start, end in folds:
        tr = np.where((d.year >= window) & (d.date < start))[0]
        c6 = np.ones(6) * 2
        for i in tr:
            l = six_label(d.rows[i])
            if l is not None:
                c6[l] += 1
                c6[(l + 3) % 6] += 1   # symmetric: each result also counts for the other corner
        cr = {3: np.ones(6), 5: np.ones(6)}
        for i in tr:
            l = round_label(d.rows[i])
            if l is not None:
                cr[5 if d.rows[i]["sched"] == 5 else 3][l] += 1
        for i in np.where(d.mask(start, end))[0]:
            six[i] = c6 / c6.sum()
            q = cr[5 if d.rows[i]["sched"] == 5 else 3].copy()
            rnd[i] = q / q.sum()
    return six, rnd


def _mask_rounds(p, sched):
    p = p.copy()
    if sched != 5:
        p[3:5] = 0
    return p / p.sum()


def _mc_ll(P, y):
    P = np.clip(np.asarray(P), 1e-9, 1)
    return float(-np.mean(np.log(P[np.arange(len(y)), y])))


def evaluate_phase8(d, sim, direct_six, direct_rnd, base_six, base_rnd, comp, idx_eval) -> str:
    L = ["# Phase 8: simulator and judging model (public per-round data)", "",
         "Generated by `python -m ufcmodel phase8`. Walk-forward: judging weights, finish scalars and direct models are refit per fold on bouts before it.", "",
         "## What this is, and is not",
         "- A round-level Monte Carlo simulator, not the spec's second-by-second positional semi-Markov model: positions need tagged "
         "sequences. Skills come from the as-of opponent-adjusted rates; fatigue is the fighter's late-round slope; damage accumulates "
         "within the fight; finish hazards use two scalars calibrated to the training finish rates.",
         "- Judging: logistic on summed round stat differences predicts the decision winner; a temperature makes three independent "
         "judges reproduce decision-winner probabilities. No per-round judge scores exist, so 10-8 rounds and judge tendencies are not modelled.", ""]
    idx = [i for i in idx_eval if i in sim and isinstance(i, (int, np.integer))]
    idx6 = [i for i in idx if six_label(d.rows[i]) is not None]
    L += [f"Evaluation set: {len(idx)} bouts from the first fold to the end of the development folds ({len(idx6)} with a winner and a "
          "KO/submission/decision method).", ""]
    # win probability
    dec = [i for i in idx if d.dec[i]]
    y = d.y[dec]
    L += ["## Win probability", "", "| Model | n | Log loss | Brier | Accuracy | AUC | ECE |", "|---|---|---|---|---|---|---|"]
    models = {"M4 simulator": {i: sim[i]["p"] for i in dec}, "B1 Elo": comp["elo"], "B2 logistic": comp["lr"], "B3 LightGBM": comp["lgbm"]}
    ll = {}
    for nm, p in models.items():
        pa = np.array([p[i] for i in dec])
        ll[nm] = M.per_bout_log_loss(pa, y)
        L.append(f"| {nm} | {len(dec)} | {M.log_loss(pa, y):.4f} | {M.brier(pa, y):.4f} | {M.accuracy(pa, y):.3f} | {M.auc(pa, y):.3f} | {M.ece(pa, y):.3f} |")
    L += ["", "Paired bootstrap, simulator minus other (positive = simulator worse):", ""]
    for nm in ("B1 Elo", "B2 logistic", "B3 LightGBM"):
        m, lo, hi = M.paired_bootstrap_diff(ll["M4 simulator"], ll[nm])
        L.append(f"- vs {nm}: {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")
    L.append("")
    # method (six-class), 3-class marginal
    y6 = np.array([six_label(d.rows[i]) for i in idx6])
    sets = {"Simulator": np.array([sim[i]["six"] / sim[i]["six"].sum() for i in idx6]),
            "Direct LightGBM": np.array([direct_six[i] for i in idx6]), "Base rates": np.array([base_six[i] for i in idx6])}
    L += ["## Winner and method (6 classes: A or B by KO/TKO, submission or decision)", "", "| Model | 6-class log loss | 3-class method log loss |", "|---|---|---|"]
    y3 = y6 % 3
    for nm, P in sets.items():
        P3 = P[:, :3] + P[:, 3:]
        L.append(f"| {nm} | {_mc_ll(P, y6):.4f} | {_mc_ll(P3, y3):.4f} |")
    L.append("")
    # rounds
    idxr = [i for i in idx if round_label(d.rows[i]) is not None]
    yr = np.array([round_label(d.rows[i]) for i in idxr])
    valid = np.array([not (d.rows[i]["sched"] != 5 and yy in (3, 4)) for i, yy in zip(idxr, yr)])
    idxr, yr = [i for i, v in zip(idxr, valid) if v], yr[valid]
    rsets = {"Simulator": np.array([_mask_rounds(sim[i]["round"], d.rows[i]["sched"]) for i in idxr]),
             "Direct LightGBM": np.array([_mask_rounds(direct_rnd[i], d.rows[i]["sched"]) for i in idxr]),
             "Base rates": np.array([base_rnd[i] for i in idxr])}
    L += ["## Round of finish (R1 to R5 or goes the distance)", "", "| Model | n | 6-class log loss |", "|---|---|---|"]
    for nm, P in rsets.items():
        L.append(f"| {nm} | {len(idxr)} | {_mc_ll(P, yr):.4f} |")
    L.append("")
    # goes the distance
    yd = (yr == 5).astype(float)
    L += ["## Probability the bout goes the distance", "", "| Model | Log loss | ECE |", "|---|---|---|"]
    rel = {}
    for nm, P in rsets.items():
        pd_ = P[:, 5]
        rel[nm] = M.reliability(pd_, yd)
        L.append(f"| {nm} | {M.log_loss(pd_, yd):.4f} | {M.ece(pd_, yd):.3f} |")
    L += ["", "Reliability of the simulator's goes-the-distance probability (deciles):", "", "| Decile | Predicted | Observed |", "|---|---|---|"]
    for k, r in enumerate(rel["Simulator"], 1):
        L.append(f"| {k} | {r['mean_p']:.3f} | {r['observed']:.3f} |")
    L.append("")
    # posterior predictive: strikes landed
    byw = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for i in idx:
        r = d.rows[i]
        if r["sig_obs_a"] is None or r["sig_obs_b"] is None or r["method"] != "Decision":
            continue
        for obs, q, mean in ((r["sig_obs_a"], sim[i]["sig_q"][0], sim[i]["sig_mean"][0]), (r["sig_obs_b"], sim[i]["sig_q"][1], sim[i]["sig_mean"][1])):
            row = byw[r["wc"]]
            row[0] += 1
            row[1] += q[0] <= obs <= q[1]
            row[2] += obs
            row[3] += mean
    L += ["## Posterior predictive check: significant strikes landed (fights that went the distance)", "",
          "Coverage = share of actual fighter totals inside the simulator's 10th to 90th percentile; a calibrated model gives about 80%. "
          "Mean ratio = mean predicted / mean actual.", "", "| Division | n fighter-fights | 10-90% coverage | Mean predicted / actual |", "|---|---|---|---|"]
    tot = [0, 0, 0.0, 0.0]
    for wc, v in sorted(byw.items()):
        if v[0] >= 100:
            L.append(f"| {wc} | {v[0]} | {v[1] / v[0]:.0%} | {v[3] / v[2]:.2f} |")
        for k in range(4):
            tot[k] += v[k]
    if tot[0]:
        L.append(f"| All | {tot[0]} | {tot[1] / tot[0]:.0%} | {tot[3] / tot[2]:.2f} |")
    L += ["", "Per-fold calibrated constants (c_ko, c_sub, hazard decay per round, strike volume scale, fight-pace sd, judging weights [sig/10, kd, td, ctrl/60, sub], kappa):", ""]
    for k, v in sim.get("params", {}).items():
        L.append(f"- {k}: {v}")
    return "\n".join(L + [""])
